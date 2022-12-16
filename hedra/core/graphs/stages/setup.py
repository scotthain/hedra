import asyncio
import psutil
from typing_extensions import TypeVarTuple, Unpack
from typing import Dict, Generic, List, Any
from hedra.core.graphs.hooks.types.hook import Hook
from hedra.core.graphs.hooks.types.hook_types import HookType
from hedra.core.graphs.hooks.types.internal import Internal
from hedra.core.engines.client.client import Client
from hedra.core.engines.client.config import Config
from hedra.core.graphs.stages.types.stage_types import StageTypes
from hedra.core.personas.types import PersonaTypesMap
from hedra.plugins.types.engine.engine_plugin import EnginePlugin
from hedra.plugins.types.plugin_types import PluginType
from playwright.async_api import Geolocation
from .execute import Execute
from .stage import Stage
from .exceptions import (
    HookSetupError
)

T = TypeVarTuple('T')


class SetupCall:

    def __init__(self, hook: Hook) -> None:
        self.hook = hook
        self.exception = None
        self.action_store = None

    async def setup(self):
        try:
            await self.hook.call()

        except Exception as setup_exception:
            self.exception = setup_exception
            self.action_store.waiter.set_result(None)



class Setup(Stage, Generic[Unpack[T]]):
    stage_type=StageTypes.SETUP
    log_level='info'
    persona_type='default'
    total_time='1m'
    batch_size=1000
    batch_interval=0
    action_interval=0
    batch_gradient=0.1
    cpus=int(psutil.cpu_count(logical=False))
    no_run_visuals=False
    graceful_stop=1
    connect_timeout=10
    request_timeout=60
    reset_connections=False
    apply_to_stages=[]
    browser_type: str='chromium'
    device_type: str=None
    locale: str=None
    geolocation: Geolocation=None
    permissions: List[str]=[]
    playwright_options: Dict[str, Any]={}

    
    def __init__(self) -> None:
        super().__init__()
        self.generation_setup_candidates = 0
        self.stages: Dict[str, Execute] = {}
        self.accepted_hook_types = [ HookType.SETUP ]
        self.persona_types = PersonaTypesMap()

        self.internal_hooks.extend([
            'get_hook',
            'get_checks',
            'setup'
        ])

    @Internal()
    async def run(self):

        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Starting setup')

        setup_hooks = self.hooks.get(HookType.SETUP)
        setup_hook_names = ', '.join([hook.name for hook in setup_hooks])
        
        if len(setup_hooks) > 0:
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Runnning Setup hooks for stage - {setup_hook_names}')
        
        await asyncio.gather(*[hook.call() for hook in self.hooks.get(HookType.SETUP)])
        execute_stage_id = 1

        stages = dict(self.stages)

        execute_stage_names = ', '.join(list(stages.keys()))

        await self.logger.spinner.append_message(f'Setting up - {execute_stage_names}')
        
        for execute_stage_name, execute_stage in stages.items():

            execute_stage.execution_stage_id = execute_stage_id
            execute_stage.execute_setup_stage = self.name

            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Execute stage - {execute_stage_name} - assigned stage order id - {execute_stage_id}')

            execute_stage_id += 1

            persona_plugins = self.plugins_by_type.get(PluginType.PERSONA)
            for plugin_name in persona_plugins.keys():
                self.persona_types.types[plugin_name] = plugin_name
                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Loaded Persona plugin - {plugin.name} - for Execute stae - {execute_stage_name}')

            config = Config(
                log_level=self.log_level,
                persona_type=self.persona_types[self.persona_type],
                total_time=self.total_time,
                batch_size=self.batch_size,
                batch_interval=self.batch_interval,
                action_interval=self.action_interval,
                batch_gradient=self.batch_gradient,
                cpus=self.cpus,
                no_run_visuals=self.no_run_visuals,
                connect_timeout=self.connect_timeout,
                request_timeout=self.request_timeout,
                graceful_stop=self.graceful_stop,
                reset_connections=self.reset_connections,
                browser_type=self.browser_type,
                device_type=self.device_type,
                locale=self.locale,
                geolocation=self.geolocation,
                permissions=self.permissions,
                playwright_options=self.playwright_options
            )
   
            client = Client(
                self.graph_name,
                self.graph_id,
                execute_stage.name,
                execute_stage.stage_id
            )
            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Created Client, id - {client.client_id} - for Execute stage - {execute_stage_name}')

            engine_plugins: Dict[str, EnginePlugin] = self.plugins_by_type.get(PluginType.ENGINE)

            for plugin_name, plugin in engine_plugins.items():
                client.plugin[plugin_name] = plugin(config)
                plugin.name = plugin_name
                self.plugins_by_type[plugin_name] = plugin

                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Loaded Engine plugin - {plugin.name} - for Execute stage - {execute_stage_name}')


            execute_stage.client = client
            execute_stage.client._config = config

            for hook in execute_stage.hooks.get(HookType.ACTION, []):

                execute_stage.client.next_name = hook.name
                execute_stage.client.intercept = True

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Client intercept set to {execute_stage.client.intercept} - Action calls for client id - {execute_stage.client.client_id} - will be suspended on execution')

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Setting up Action - {hook.name} - for Execute stage - {execute_stage_name}')
                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Preparing Action hook - {hook.name} - for suspension - Execute stage - {execute_stage_name}')

                execute_stage.client.actions.set_waiter(execute_stage.name)

                setup_call = SetupCall(hook)
                setup_call.action_store = execute_stage.client.actions

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Executing Action hook call - {hook.name} - Execute stage - {execute_stage_name}')

                task = asyncio.create_task(setup_call.setup())
                await execute_stage.client.actions.wait_for_ready(setup_call)   

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Exiting suspension for Action - {hook.name} - Execute stage - {execute_stage_name}')

                try:
                    if setup_call.exception:
                        raise HookSetupError(hook, HookType.ACTION, str(setup_call.exception))

                    task.cancel()
                    if task.cancelled() is False:
                        await asyncio.wait_for(task, timeout=0.1)

                except HookSetupError as hook_setup_exception:
                    raise hook_setup_exception

                except asyncio.InvalidStateError:
                    pass

                except asyncio.CancelledError:
                    pass

                except asyncio.TimeoutError:
                    pass
                     
                action, session = execute_stage.client.actions.get(
                    execute_stage.name,
                    hook.name
                )

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Successfully retrieved prepared Action and Session for action - {action.name} - Execute stage - {execute_stage_name}')

                action.hooks.before =  await self.get_hook(execute_stage, hook.shortname, HookType.BEFORE)
                action.hooks.after = await self.get_hook(execute_stage, hook.shortname, HookType.AFTER)
                action.hooks.checks = await self.get_checks(execute_stage, hook.shortname)

                hook.session = session
                hook.action = action    

            for hook in execute_stage.hooks.get(HookType.TASK, []):

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Loading Task hook - {hook.name} - to Execute stage - {execute_stage_name}')

                execute_stage.client.next_name = hook.name
                task, session = execute_stage.client.task.call(
                    hook.call,
                    env=hook.config.env,
                    user=hook.config.user,
                    tags=hook.config.tags
                )

                await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Successfully retrieved task and session for Task - {task.name} - Execute stage - {execute_stage_name}')

                task.hooks.checks = self.get_checks(execute_stage, hook.shortname) 

                hook.session = session
                hook.action = task  

            execute_stage.client.intercept = False
            await self.logger.filesystem.aio['hedra.core'].debug(f'{self.metadata_string} - Client intercept set to {execute_stage.client.intercept} - Action calls for client id - {execute_stage.client.client_id} - will not be suspended on execution')

            for setup_hook in execute_stage.hooks.get(HookType.SETUP):
                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing Setup hook - {setup_hook.name} - for Execute stage - {execute_stage_name}')

                await setup_hook.call()

            self.stages[execute_stage_name] = execute_stage

            actions_generated_count = len(execute_stage.hooks.get(HookType.ACTION, []))
            tasks_generated_count = len(execute_stage.hooks.get(HookType.TASK, []))

            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Generated - {actions_generated_count} - Actions for Execute stage - {execute_stage_name}')
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Generated - {tasks_generated_count} - Tasks for Execute stage - {execute_stage_name}')

        await self.logger.spinner.set_default_message(f'Setup for - {execute_stage_names} - complete')

        await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Completed setup')

        return self.stages

    @Internal()
    async def get_hook(self, execute_stage: Execute, shortname: str, hook_type: str):
        for hook in execute_stage.hooks[hook_type]:
            if shortname in hook.names:
                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Adding Hook - {hook.name} - of type - {hook.hook_type.name.capitalize()} - to Action - {shortname} - for Execute stage - {execute_stage.name}')

                return hook.call

    @Internal()
    async def get_checks(self, execute_stage: Execute, shortname: str):

        checks = []

        for hook in execute_stage.hooks[HookType.CHECK]:
            if shortname in hook.names:
                await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Adding Check - {hook.name} - to Action or Task - {shortname} - for Execute stage - {execute_stage.name}')
                
                checks.append(hook.call)

        return checks

    @Internal()
    async def setup(self):
        for setup_hook in self.hooks.get(HookType.SETUP):
            await self.logger.filesystem.aio['hedra.core'].info(f'{self.metadata_string} - Executing Setup hook - {setup_hook.name}')

            await setup_hook()