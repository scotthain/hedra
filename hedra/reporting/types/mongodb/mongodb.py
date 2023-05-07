import uuid
from typing import List, Dict
from hedra.logging import HedraLogger
from hedra.reporting.experiment.experiments_collection import ExperimentMetricsCollectionSet
from hedra.reporting.processed_result.types.base_processed_result import BaseProcessedResult
from hedra.reporting.metric.stage_streams_set import StageStreamsSet
from hedra.reporting.metric import MetricsSet
from .mongodb_config import MongoDBConfig


try:
    from motor.motor_asyncio import AsyncIOMotorClient
    has_connector = True

except Exception:
    AsyncIOMotorClient = None
    has_connector = False



class MongoDB:

    def __init__(self, config: MongoDBConfig) -> None:
        self.host = config.host
        self.username = config.username
        self.password = config.password
        self.database_name = config.database

        self.events_collection = config.events_collection
        self.metrics_collection = config.metrics_collection
        self.streams_collection = config.streams_collection

        self.experiments_collection = config.experiments_collection
        self.variants_collection = f'{config.experiments_collection}_variants'
        self.mutations_collection = f'{config.experiments_collection}_mutations'

        self.shared_metrics_collection = f'{self.metrics_collection}_common'
        self.errors_collection = f'{self.metrics_collection}_errors'
        self.custom_metrics_collection = f'{self.metrics_collection}_custom'

        self.connection: AsyncIOMotorClient = None
        self.database = None

        self.session_uuid = str(uuid.uuid4())
        self.metadata_string: str = None
        self.logger = HedraLogger()
        self.logger.initialize()

    async def connect(self):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Connecting to MongoDB instance at - {self.host} - Database: {self.database_name}')

        if self.username and self.password:
            connection_string = f'mongodb://{self.username}:{self.password}@{self.host}/{self.database_name}'
        
        else:
            connection_string = f'mongodb://{self.host}/{self.database_name}'

        self.connection = AsyncIOMotorClient(connection_string)
        self.database = self.connection[self.database_name]

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Connected to MongoDB instance at - {self.host} - Database: {self.database_name}')

    async def submit_streams(self, stream_metrics: Dict[str, StageStreamsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Streams to Bucket - {self.streams_collection}')

        records = []
        for stage_name, stream in stream_metrics.items():
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Streams - {stage_name}:{stream.stream_set_id}')
            
            for group_name, group in stream.grouped.items():
                records.append({
                    'name': f'{stage_name}_streams',
                    'stage': stage_name,
                    'group': group_name,
                    **group
                })

        await self.database[self.metrics_collection].insert_many(records)

    async def submit_experiments(self, experiment_metrics: ExperimentMetricsCollectionSet): 
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Experiments to Collection - {self.experiments_collection}')
        await self.database[self.events_collection].insert_many(experiment_metrics.experiments)

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Experiments to Collection - {self.experiments_collection}')

    async def submit_variants(self, experiment_metrics: ExperimentMetricsCollectionSet): 
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Variants to Collection - {self.variants_collection}')
        await self.database[self.events_collection].insert_many(experiment_metrics.variants)

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Variants to Collection - {self.variants_collection}')

    async def submit_mutations(self, experiment_metrics: ExperimentMetricsCollectionSet): 
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Mutations to Collection - {self.mutations_collection}')
        await self.database[self.events_collection].insert_many(experiment_metrics.mutations)

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Mutations to Collection - {self.mutations_collection}')

    async def submit_events(self, events: List[BaseProcessedResult]): 
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Events to Collection - {self.events_collection}')
        await self.database[self.events_collection].insert_many(
            [event.record for event in events]
        )

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Events to Collection - {self.events_collection}')

    async def submit_common(self, metrics_sets: List[MetricsSet]):
        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Shared Metrics to Bucket - {self.shared_metrics_collection}')
        await self.database[self.shared_metrics_collection].insert_many([
            {
                'name': metrics_set.name,
                'stage': metrics_set.stage,
                'group': 'common',
                **metrics_set.common_stats
            } for metrics_set in metrics_sets
        ])

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Shared Metrics to Bucket - {self.shared_metrics_collection}')

    async def submit_metrics(self, metrics: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Metrics to Bucket - {self.metrics_collection}')

        records = []
        for metrics_set in metrics:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')
            
            for group_name, group in metrics_set.groups.items():
                records.append({
                    'group': group_name,
                    **group.record
                })

        await self.database[self.metrics_collection].insert_many(records)

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Metrics to Bucket - {self.metrics_collection}')

    async def submit_custom(self, metrics_sets: List[MetricsSet]):

        records = []
        for metrics_set in metrics_sets:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Shared Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')
            records.append({
                'name': metrics_set.name,
                'stage': metrics_set.stage,
                'group': 'custom',
                **{
                    custom_metric_name: custom_metric.metric_value for custom_metric_name, custom_metric in metrics_set.custom_metrics.items()
                }
            })

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Custom Metrics to Bucket - {self.custom_metrics_collection}')

        await self.database[self.custom_metrics_collection].insert_many(records)

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Custom Metrics to Bucket - {self.custom_metrics_collection}')

    async def submit_errors(self, metrics: List[MetricsSet]):

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitting Error Metrics to Bucket - {self.errors_collection}')

        for metrics_set in metrics:
            await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Submitting Shared Metrics Set - {metrics_set.name}:{metrics_set.metrics_set_id}')

            await self.database[self.errors_collection].insert_many([
                {
                    'name': metrics_set.name,
                    'stage': metrics_set.stage,
                    'error_message': error.get('message'),
                    'error_count': error.get('count')
                } for error in metrics_set.errors
            ])

        await self.logger.filesystem.aio['hedra.reporting'].info(f'{self.metadata_string} - Submitted Error Metrics to Bucket - {self.errors_collection}')

    async def close(self):
        await self.logger.filesystem.aio['hedra.reporting'].debug(f'{self.metadata_string} - Closing session - {self.session_uuid}')