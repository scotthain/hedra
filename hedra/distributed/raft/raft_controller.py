import asyncio
import time
import random
from collections import (
    defaultdict,
    deque,
    OrderedDict
)
from hedra.distributed.env import (
    Env, 
    MonitorEnv,
    RaftEnv,
    load_env
)
from hedra.distributed.env.time_parser import TimeParser
from hedra.distributed.hooks.client_hook import client
from hedra.distributed.hooks.server_hook import server
from hedra.distributed.models.raft.raft_message import (
    RaftMessage
)
from hedra.distributed.types import Call
from hedra.distributed.models.raft.election_state import ElectionState
from hedra.distributed.models.raft.logs import Entry, NodeState
from hedra.distributed.monitoring import Monitor
from hedra.distributed.service.controller import Controller
from hedra.distributed.snowflake.snowflake_generator import (
    SnowflakeGenerator
)
from hedra.logging import (
    HedraLogger,
    logging_manager
)
from hedra.tools.helpers import cancel
from typing import (
    Optional, 
    Union, 
    Deque,
    Dict, 
    Tuple, 
    List,
    Any
)

from .constants import FLEXIBLE_PAXOS_QUORUM
from .log_queue import LogQueue


class RaftController(Controller[Monitor]):

    def __init__(
        self,
        host: str,
        port: int,
        env: Optional[Env]=None,
        cert_path: Optional[str]=None,
        key_path: Optional[str]=None,
        logs_directory: Optional[str]=None,
        workers: int=0,
    ) -> None:
        
        if workers <= 1:
            engine = 'async'

        else:
            engine = 'process'

        if env is None:
            env = load_env(Env)

        if logs_directory is None:
            logs_directory = env.MERCURY_SYNC_LOGS_DIRECTORY

        raft_env = load_env(RaftEnv) 

        super().__init__(
            host,
            port,
            cert_path=cert_path,
            key_path=key_path,
            workers=workers,
            env=env,
            engine=engine,
            plugins={
                'monitor': Monitor
            }
        )

        self._term_number = 0
        self._term_votes = defaultdict(
            lambda: defaultdict(
                lambda: 0
            )
        )

        self._max_election_timeout = TimeParser(
            raft_env.MERCURY_SYNC_RAFT_ELECTION_MAX_TIMEOUT
        ).time

        self._min_election_timeout = max(
            self._max_election_timeout * 0.5,
            1
        )

        self._election_poll_interval = TimeParser(
            raft_env.MERCURY_SYNC_RAFT_ELECTION_POLL_INTERVAL
        ).time

        self._logs_update_poll_interval = TimeParser(
            raft_env.MERCURY_SYNC_RAFT_LOGS_UPDATE_POLL_INTERVAL
        ).time
        
        self._election_status = ElectionState.READY
        self._raft_node_status = NodeState.FOLLOWER
        self._active_election_waiter: Union[asyncio.Future, None] = None
        self._latest_election: Dict[int, int] = {}
        self._term_leaders: List[Tuple[str, int]] = [
            (self.host, self.port)
        ]
        
        self._running = False

        self._logs = LogQueue()
        self._previous_entry_index = 0
        self._last_timestamp = 0
        self._last_commit_timestamp = 0
        self._term_number = 0

        self._raft_monitor_task: Union[asyncio.Task, None] = None
        self._tasks_queue: Deque[asyncio.Task] = deque()
        self._entry_id_generator = SnowflakeGenerator(self._instance_id)

        logging_manager.logfiles_directory = logs_directory
        logging_manager.update_log_level(
            'info'
        )

        self._logger = HedraLogger()
        self._logger.initialize()

        monitor_env: MonitorEnv = load_env(MonitorEnv)

        self.boot_wait = TimeParser(
            monitor_env.MERCURY_SYNC_BOOT_WAIT
        ).time

        self._cleanup_interval = TimeParser(
            env.MERCURY_SYNC_CLEANUP_INTERVAL
        ).time

        self._pending_election_waiter: Union[asyncio.Future, None]  = None
        
    async def start(
        self,
        cert_path: Optional[str]=None,
        key_path: Optional[str]=None
    ):

        self._running = True
        
        await self._logger.filesystem.aio.create_logfile('hedra.distributed.log')
        self._logger.filesystem.create_filelogger('hedra.distributed.log')

        loop = asyncio.get_event_loop()
        self._last_commit_timestamp = loop.time()

        await self.start_server(
            cert_path=cert_path,
            key_path=key_path
        )

        await asyncio.sleep(self.boot_wait)
        
        await asyncio.gather(*[
            monitor.start(
                skip_boot_wait=True
            ) for monitor in self._plugins['monitor'].each()
        ])

        self._timeout = random.uniform(
            self._min_election_timeout,
            self._max_election_timeout
        )

    async def register(
        self,
        host: str,
        port: int         
    ):
        await asyncio.gather(*[
            monitor.register(
                host,
                port
            ) for monitor in self._plugins['monitor'].each()
        ])

        self._raft_monitor_task = asyncio.create_task(
            self._run_raft_monitor()
        )
        
        self._cleanup_task = asyncio.create_task(
            self._cleanup_pending_raft_tasks()
        )

    @server()
    async def receive_vote_request(
        self,
        shard_id: int,
        raft_message: RaftMessage
    ) -> Call[RaftMessage]:
          
        source_host = raft_message.source_host
        source_port = raft_message.source_port

        term_number = raft_message.term_number

        elected_host: Union[str, None] = None
        elected_port: Union[int, None] = None

        if self._election_status in [ElectionState.ACTIVE, ElectionState.PENDING]:
            # There is already an election in play
            election_result = RaftMessage(
                host=source_host,
                port=source_port,
                election_status=ElectionState.PENDING,
                term_number=term_number
            )
            

        elif term_number > self._term_number:

            self._election_status = ElectionState.ACTIVE
            # The requesting node is ahead. They're elected the leader by default.
            elected_host = source_host
            elected_port = source_port
            self._term_number = term_number

        elif term_number == self._term_number:
            # The term numbers match, we can choose a candidate.

            self._election_status = ElectionState.ACTIVE
            members: List[Tuple[str, int]] = []

            for monitor in self._plugins['monitor'].each():
                members.extend([
                    address for address, status in monitor._node_statuses.items() if status == 'healthy'
                ])

            elected_host, elected_port = random.choice(
                list(set(members))
            )

        else:

            election_result = RaftMessage(
                host=source_host,
                port=source_port,
                election_status=ElectionState.REJECTED,
                term_number=term_number
            )
            
        
        if elected_host == source_host and elected_port == source_port:
            
            election_result = RaftMessage(
                host=source_host,
                port=source_port,
                election_status=ElectionState.ACCEPTED,
                term_number=term_number
            )
        
        elif elected_host is not None and elected_port is not None:

            election_result = RaftMessage(
                host=source_host,
                port=source_port,
                election_status=ElectionState.REJECTED,
                term_number=term_number
            )

        return election_result
    
    @server()
    async def receive_log_update(
        self,
        shard_id: int,
        message: RaftMessage
    ) -> Call[RaftMessage]:
        entries_count = len(message.entries)

        if entries_count < 0:
            return RaftMessage(
                host=message.host,
                port=message.port,
                source_host=self.host,
                source_port=self.port,
                election_status=self._election_status,
                raft_node_status=self._raft_node_status
            )
        
        # We can use the Snowflake ID to sort since all records come from the 
        # leader.
        entries: List[Entry] = list(
            sorted(
                message.entries,
                key=lambda entry: entry.entry_id
            )
        )

        error = self._logs.update(entries)

        if isinstance(error, Exception):

            elected_leader = self._term_leaders[-1]

            return RaftMessage(
                host=message.host,
                port=message.port,
                source_host=self.host,
                source_port=self.port,
                election_status=self._election_status,
                raft_node_status=self._raft_node_status,
                error=str(error),
                elected_leader=elected_leader,
                term_number=self._term_number
            )

        return RaftMessage(
            host=message.host,
            port=message.port,
            source_host=self.host,
            source_port=self.port,
            election_status=self._election_status,
            raft_node_status=self._raft_node_status
        )

    @client('receive_vote_request')
    async def request_vote(
        self,
        host: str,
        port: int
    ) -> Call[RaftMessage]:
        
        return RaftMessage(
            host=host,
            port=port,
            source_host=self.host,
            source_port=self.port,
            election_status=self._election_status,
            raft_node_status=self._raft_node_status
        )
    
    @client('receive_log_update')
    async def submit_log_update(
        self,
        host: str,
        port: int,
        entries: List[Dict[str, Any]]
    ) -> Call[RaftMessage]:
        
        return RaftMessage(
            host=host,
            port=port,
            source_host=self.host,
            source_port=self.port,
            election_status=self._election_status,
            raft_node_status=self._raft_node_status,
            entries=[
                Entry(
                    entry_id=self._entry_id_generator.generate(),
                    term=self._term_number,
                    **entry
                ) for entry in entries
            ]
        )
    
    async def _update_logs(
        self,
        host: str,
        port: int,
        entries: List[Dict[str, Any]]
    ):
        
        _, response = await self.submit_log_update(
            host,
            port,
            entries
        )

        elected_leader = self._term_leaders[-1]

        if response.error and elected_leader != response.elected_leader:
            self._term_leaders.append(response.elected_leader)
            self._term_number = response.term_number

    async def run_election(self):
        # Trigger new election
        self._term_number += 1
        
        self._term_votes[self._term_number][(self.host, self.port)] += 1

        members: List[Tuple[str, int]] = []

        for monitor in self._plugins['monitor'].each():
            members.extend([
                address for address, status in monitor._node_statuses.items() if status  == 'healthy'
            ])

        members = list(set(members))

        election_timeout = random.uniform(
            self._min_election_timeout,
            self._max_election_timeout
        )

        vote_requests = [
            asyncio.create_task(
                self.request_vote(
                    member_host,
                    member_port
                )
            ) for member_host, member_port in members
        ]

        accepted_count = 0

        for vote_result in asyncio.as_completed(
            vote_requests, 
            timeout=election_timeout
        ):

            try:
                response: Tuple[int, RaftMessage] = await vote_result

                (
                    _, 
                    result
                ) = response

                if result.election_status == ElectionState.ACCEPTED:
                    accepted_count += 1

            except asyncio.TimeoutError:
                pass
    
        quorum_count = int(
            len(members) * (1 - FLEXIBLE_PAXOS_QUORUM) + 1
        )

        if accepted_count >= quorum_count:
            self._raft_node_status = NodeState.LEADER

    async def _run_raft_monitor(self):

        while self._running:

            members: List[Tuple[str, int]] = []

            for monitor in self._plugins['monitor'].each():
                members.extend([
                    address for address, status in monitor._node_statuses.items() if status == 'healthy'
                ])

            members = list(set(members))

            if self._raft_node_status == NodeState.LEADER:
                for host, port in members:
            
                    self._tasks_queue.append(
                        asyncio.create_task(
                            self.submit_log_update(
                                host,
                                port
                            )
                        )
                    )

            else:
                failed_members = list(set([
                    node for node in monitor.failed_nodes if node not in monitor.removed_nodes
                ]))

                print(failed_members)

                if len(failed_members) > 0:
                    self._tasks_queue.append(
                        asyncio.create_task(
                            self.run_election()
                        )
                    )

            await asyncio.sleep(
                self._logs_update_poll_interval
            )

    async def _cleanup_pending_raft_tasks(self):

        await self._logger.distributed.aio.debug(f'Running cleanup for source - {self.host}:{self.port}')
        await self._logger.filesystem.aio['hedra.distributed'].debug(f'Running cleanup for source - {self.host}:{self.port}')

        while self._running:

            pending_count = 0

            for pending_task in list(self._tasks_queue):
                if pending_task.done() or pending_task.cancelled():
                    try:
                        await pending_task

                    except (
                        ConnectionRefusedError,
                        ConnectionAbortedError,
                        ConnectionResetError
                    ):
                        pass

                    self._tasks_queue.remove(pending_task)
                    pending_count += 1

            await self._logger.distributed.aio.debug(f'Cleaned up - {pending_count} - for source - {self.host}:{self.port}')
            await self._logger.filesystem.aio['hedra.distributed'].debug(f'Cleaned up - {pending_count} - for source - {self.host}:{self.port}')

            await asyncio.sleep(self._cleanup_interval)

    async def leave(self):
        await self._logger.distributed.aio.debug(f'Shutdown requested for RAFT source - {self.host}:{self.port}')
        await self._logger.filesystem.aio['hedra.distributed'].debug(f'Shutdown requested for RAFT source - {self.host}:{self.port}')

        await asyncio.gather(*[
            monitor.leave() for monitor in self._plugins['monitor'].each() if isinstance(monitor, Monitor)
        ])

        self._running = False

        await cancel(self._raft_monitor_task)

        await self.close()

        await self._logger.distributed.aio.debug(f'Shutdown complete for RAFT source - {self.host}:{self.port}')
        await self._logger.filesystem.aio['hedra.distributed'].debug(f'Shutdown complete for RAFT source - {self.host}:{self.port}')
