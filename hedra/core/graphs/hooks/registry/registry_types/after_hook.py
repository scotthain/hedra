from typing import Coroutine, List, Dict
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from hedra.core.graphs.hooks.registry.registry_types.hook import Hook, Metadata

class AfterHook(Hook):

    def __init__(
        self, 
        name: str, 
        shortname: str, 
        call: Coroutine, 
        *names: List[str]
    ) -> None:
        super().__init__(
            name, 
            shortname, 
            call, 
            names=names,
            hook_type=HookType.AFTER, 
            metadata=Metadata()
        )


