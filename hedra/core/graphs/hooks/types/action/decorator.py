import functools
from typing import Dict, Union, Tuple
from hedra.core.graphs.hooks.types.base.hook_type import HookType
from hedra.core.graphs.hooks.types.base.hook import Hook
from hedra.core.graphs.hooks.types.base.registrar import registrar
from .validator import ActionHookValidator


@registrar(HookType.ACTION)
def action(
    *names: Tuple[str, ...],
    weight: int=1, 
    order: int=1, 
    metadata: Dict[str, Union[str, int]]={}
):
    ActionHookValidator(
        names=names,
        weight=weight,
        order=order,
        metadata=metadata
    )
    
    def wrapper(func) -> Hook:

        @functools.wraps(func)
        def decorator(*args, **kwargs):

            return func(*args, **kwargs)
                
        return decorator

    return wrapper