from typing import Coroutine, Optional, Any, Dict
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from hedra.core.graphs.hooks.registry.registry_types.hook import Hook, Metadata

class SetupHook(Hook):

    def __init__(
        self, 
        name: str, 
        shortname: str, 
        call: Coroutine, 
        metadata: Dict[str, Any]={}
    ) -> None:
        super().__init__(
            name, 
            shortname, 
            call, 
            hook_type=HookType.SETUP, 
            metadata=Metadata(**metadata)
        )