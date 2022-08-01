# # This is an ugly patch for: https://github.com/aio-libs/aiopg/issues/837
# import selectors  # isort:skip # noqa: F401

# selectors._PollLikeSelector.modify = (  # type: ignore
#     selectors._BaseSelectorImpl.modify  # type: ignore
# )

from typing import List
import uuid

from numpy import float32, float64, int16, int32, int64
from hedra.reporting.events.types.base_event import BaseEvent
from hedra.reporting.metric import MetricsSet


try:
    import sqlalchemy
    from sqlalchemy.dialects.postgresql import UUID
    from sqlalchemy.schema import CreateTable
    from aiopg.sa import create_engine
    from .postgres_config import PostgresConfig
    has_connector = True

except Exception:
    UUID = None
    sqlalchemy = None
    create_engine = None
    PostgresConfig = None
    has_connector = False


class Postgres:

    def __init__(self, config: PostgresConfig) -> None:
        self.host = config.host
        self.database = config.database
        self.username = config.username
        self.password = config.password
        self.events_table_name = config.events_table
        self.metrics_table_name = config.metrics_table
        self.group_metrics_table_name = f'{self.group_metrics_table_name}_group_metrics'
        self.errors_table_name = f'{self.metrics_table_name}_errors'
        self.custom_fields = config.custom_fields
        
        self._engine = None
        self._connection = None
        self.metadata = sqlalchemy.MetaData()
        self._events_table = None
        self._metrics_table = None
        self._group_metrics_table = None
        self._errors_table = None
        self._metrics_errors_table = None
        self._custom_metrics_tables = {}

    async def connect(self):
        self._engine = await create_engine(
            user=self.username,
            database=self.database,
            host=self.host,
            password=self.password
        )

        self._connection = await self._engine.acquire()

    async def submit_events(self, events: List[BaseEvent]):
        
        async with self._connection.begin() as transaction:

            for event in events:

                if self._events_table is None:
                    events_table = sqlalchemy.Table(
                        self.events_table_name,
                        self.metadata,
                        sqlalchemy.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
                        sqlalchemy.Column('name', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('stage', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('time', sqlalchemy.Float),
                        sqlalchemy.Column('succeeded', sqlalchemy.Boolean),
                    )
                    
                    await self._connection.execute(CreateTable(events_table, if_not_exists=True))

                    self._events_table = events_table
                
                await self._connection.execute(self._events_table.insert(values=event.record))
            
            await transaction.commit()

    async def submit_common(self, metrics_sets: List[MetricsSet]):

        async with self._connection.begin() as transaction:
            
            if self._group_metrics_table is None:

                group_metrics_table = sqlalchemy.Table(
                    self.group_metrics_table_name,
                    self.metadata,
                    sqlalchemy.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
                    sqlalchemy.Column('name', sqlalchemy.VARCHAR(255)),
                    sqlalchemy.Column('stage', sqlalchemy.VARCHAR(255)),
                    sqlalchemy.Column('group', sqlalchemy.VARCHAR(255)),
                    sqlalchemy.Column('total', sqlalchemy.BIGINT),
                    sqlalchemy.Column('succeeded', sqlalchemy.BIGINT),
                    sqlalchemy.Column('failed', sqlalchemy.BIGINT),
                    sqlalchemy.Column('actions_per_second', sqlalchemy.FLOAT)
                )

                await self._connection.execute(CreateTable(group_metrics_table, if_not_exists=True))
                self._group_metrics_table = group_metrics_table

            for metrics_set in metrics_sets:
                await self._connection.execute(
                    self._metrics_table.insert(values={
                        'name': metrics_set.name,
                        'stage': metrics_set.stage,
                        'group': 'common',
                        **metrics_set.common_stats
                    })
                )

            await transaction.commit()

    async def submit_metrics(self, metrics: List[MetricsSet]):

        async with self._connection.begin() as transaction:

            for metrics_set in metrics:

                if self._metrics_table is None:

                    metrics_table = sqlalchemy.Table(
                        self.metrics_table_name,
                        self.metadata,
                        sqlalchemy.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
                        sqlalchemy.Column('name', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('stage', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('group', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('median', sqlalchemy.FLOAT),
                        sqlalchemy.Column('mean', sqlalchemy.FLOAT),
                        sqlalchemy.Column('variance', sqlalchemy.FLOAT),
                        sqlalchemy.Column('stdev', sqlalchemy.FLOAT),
                        sqlalchemy.Column('minimum', sqlalchemy.FLOAT),
                        sqlalchemy.Column('maximum', sqlalchemy.FLOAT)
                    )

                    for quantile in metrics_set.quantiles:
                        metrics_table.append_column(
                            sqlalchemy.Column(f'{quantile}', sqlalchemy.FLOAT)
                        )

                    for custom_field_name, sql_alchemy_type in metrics_set.custom_schemas:
                        metrics_table.append_column(custom_field_name, sql_alchemy_type) 

                    await self._connection.execute(CreateTable(metrics_table, if_not_exists=True))
                    self._metrics_table = metrics_table

                for group_name, group in metrics_set.groups.items():
                    await self._connection.execute(
                        self._metrics_table.insert(values={
                            **group.record,
                            'group': group_name
                        })
                    )

            await transaction.commit()

    async def submit_custom(self, metrics_sets: List[MetricsSet]):

        async with self._connection.begin() as transaction:
            
            for metrics_set in metrics_sets:
                for custom_group_name, group in metrics_set.custom_metrics.items():

                    custom_table_name = f'{self.metrics_table_name}_{custom_group_name}'

                    if self._custom_metrics_tables.get(custom_table_name) is None:
                        custom_metrics_table = sqlalchemy.Table(
                            custom_table_name,
                            self.metadata,
                            sqlalchemy.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
                            sqlalchemy.Column('name', sqlalchemy.VARCHAR(255)),
                            sqlalchemy.Column('stage', sqlalchemy.VARCHAR(255)),
                            sqlalchemy.Column('group', sqlalchemy.VARCHAR(255)),
                        )

                        for field, value in group.items():

                            if isinstance(value, (int, int16, int32, int64)):
                                custom_metrics_table.append_column(
                                    sqlalchemy.Column(field, sqlalchemy.Integer)
                                )

                            elif isinstance(value, (float, float32, float64)):
                                custom_metrics_table.append_column(
                                    sqlalchemy.Column(field, sqlalchemy.Float)
                                )

                        await self._connection.execute(CreateTable(custom_metrics_table, if_not_exists=True))
                        self._custom_metrics_tables[custom_table_name] = custom_metrics_table

                    await self._connection.execute(
                        self._custom_metrics_tables[custom_table_name].insert(values={
                            'name': metrics_set.name,
                            'stage': metrics_set.stage,
                            'group': custom_group_name,
                            **group
                        })
                    )

            await transaction.commit()

    async def submit_errors(self, metrics_sets: List[MetricsSet]):

        async with self._connection.begin() as transaction:
            for metrics_set in metrics_sets:

                if self._errors_table is None:
                    errors_table = sqlalchemy.Table(
                        self.errors_table_name,
                        self.metadata,
                        sqlalchemy.Column('id', UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
                        sqlalchemy.Column('name', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('stage', sqlalchemy.VARCHAR(255)),
                        sqlalchemy.Column('error_message', sqlalchemy.TEXT),
                        sqlalchemy.Column('error_count', sqlalchemy.Integer)
                    )  


                    await self._connection.execute(CreateTable(errors_table, if_not_exists=True))
                    self._errors_table = errors_table

                for error in metrics_set.errors:
                    await self._connection.execute(
                        self._metrics_errors_table.insert(values={
                            'name': metrics_set.name,
                            'stage': metrics_set.stage,
                            'error_message': error.get('message'),
                            'error_count': error.get('count')
                        })
                    )

            await transaction.commit()
        
    async def close(self):
        await self._connection.close()
        self._engine.terminate()
        await self._engine.wait_closed()



    
