import asyncio
import time
import traceback
from typing import Awaitable, Dict, Set, Tuple, Union
from hedra.core.engines.types.common.ssl import get_default_ssl_context
from hedra.core.engines.types.common.timeouts import Timeouts
from .connection import HTTPConnection
from .action import HTTPAction
from .result import HTTPResult
from .pool import Pool


HTTPResponseFuture = Awaitable[Union[HTTPResult, Exception]]
HTTPBatchResponseFuture = Awaitable[Tuple[Set[HTTPResponseFuture], Set[HTTPResponseFuture]]]


class MercuryHTTPClient:

    def __init__(self, concurrency: int=10**3, timeouts: Timeouts = Timeouts(), reset_connections: bool=False) -> None:

        self.timeouts = timeouts
        self.registered: Dict[str, HTTPAction] = {}
        self._hosts = {}

        self.sem = asyncio.Semaphore(concurrency)
        self.pool = Pool(concurrency, reset_connections=reset_connections)
        self.pool.create_pool()

        self.ssl_context = get_default_ssl_context()

    async def prepare(self, action: HTTPAction) -> Awaitable[Union[HTTPAction, Exception]]:
        try:
            if action.url.is_ssl:
                action.ssl_context = self.ssl_context

            if self._hosts.get(action.url.hostname) is None:

                    socket_configs = await action.url.lookup()
                    for ip_addr, configs in socket_configs.items():
                        for config in configs:
                            try:
                                connection = HTTPConnection()
                                await connection.make_connection(
                                    action.url.hostname,
                                    ip_addr,
                                    action.url.port,
                                    config,
                                    ssl=action.ssl_context
                                )

                                action.url.socket_config = config
                                action.url.ip_addr = ip_addr
                                action.url.has_ip_addr = True
                                break

                            except Exception as e:
                                pass

                        if action.url.socket_config:
                            break
                
                    self._hosts[action.url.hostname] = {
                        'ip_addr': action.url.ip_addr,
                        'socket_config': action.url.socket_config
                    }

                    if action.url.socket_config is None:
                        raise Exception('Err. - No socket found.')

            else:
                host_config = self._hosts[action.url.hostname]
                action.url.ip_addr = host_config.get('ip_addr')
                action.url.socket_config = host_config.get('socket_config')

            if action.is_setup is False:
                action.setup()

            self.registered[action.name] = action

            return action
        
        except Exception as e:
            raise e

    async def execute_prepared_request(self, action: HTTPAction) -> HTTPResponseFuture:
 
        response = HTTPResult(action)
        response.wait_start = time.monotonic()
 
        async with self.sem:
            connection = self.pool.connections.pop()
            
            try:
                if action.hooks.before:
                    action = await action.hooks.before(action, response)
                    action.setup()

                response.start = time.monotonic()

                await connection.make_connection(
                    action.url.hostname,
                    action.url.ip_addr,
                    action.url.port,
                    action.url.socket_config,
                    timeout=self.timeouts.connect_timeout,
                    ssl=action.ssl_context
                )

                response.connect_end = time.monotonic()

                connection.write(action.encoded_headers)
                
                if action.encoded_data:
                    if action.is_stream:
                        action.write_chunks(connection)

                    else:
                        connection.write(action.encoded_data)

                response.write_end = time.monotonic()

                response.response_code = await connection._connection._reader.readline_fast()
    
                headers = await connection.read_headers()

                content_length = headers.get(b'content-length')
                transfer_encoding = headers.get(b'transfer-encoding')

                # We require Content-Length or Transfer-Encoding headers to read a
                # request body, otherwise it's anyone's guess as to how big the body
                # is, and we ain't playing that game.
                body = bytearray()
                if content_length:
                    body = await connection.readexactly(int(content_length))

                elif transfer_encoding:
                    
                    all_chunks_read = False

                    while True and not all_chunks_read:

                        chunk_size = int((await connection.readuntil()).rstrip(), 16)
    
                        if not chunk_size:
                            # read last CRLF
                            body.extend(
                                await connection.readuntil()
                            )
                            break
                        
                        chunk = await connection.readexactly(chunk_size + 2)
                        body.extend(
                            chunk[:-2]
                        )

                    all_chunks_read = True
         
                response.read_end = time.monotonic()
                response.headers = headers
                response.body = body
                
                self.pool.connections.append(connection)

                if action.hooks.after:
                    action = await action.hooks.after(action, response)
                    action.setup()
                
                return response

            except Exception as e:
                response.read_end = time.monotonic()
                response.error = str(e)
                self.pool.connections.append(HTTPConnection(reset_connection=self.pool.reset_connections))
                return response
