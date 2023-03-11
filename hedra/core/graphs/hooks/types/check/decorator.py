import functools
from hedra.core.graphs.hooks.types.base.hook_type import HookType
from hedra.core.graphs.hooks.types.base.registrar import registrar
from .validator import CheckHookValidator


@registrar(HookType.CHECK)
def check(*names, order: int=1):
    
    CheckHookValidator(
        names=names,
        order=order
    )
    
    def wrapper(func):

        @functools.wraps(func)
        def decorator(*args, **kwargs):
            return func(*args, **kwargs)

        return decorator

    return wrapper