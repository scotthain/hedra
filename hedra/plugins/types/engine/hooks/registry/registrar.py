
from types import FunctionType
from typing import Any, Dict
from hedra.plugins.types.engine.hooks.types.plugin_hook import PluginHook


class PluginRegistrar:

    all: Dict[str, PluginHook] = {}

    def __init__(self, hook_type) -> None:

        self.hook_type = hook_type

    def __call__(self, _: FunctionType) -> Any:
        return self.add_hook(self.hook_type)

    def add_hook(self, hook_type: str):
        def wrap_hook():
            def wrapped_method(func):

                hook_name = func.__qualname__
                hook_shortname = func.__name__


                self.all[hook_name] = PluginHook(
                    hook_name,
                    hook_shortname,
                    func,
                    hook_type=hook_type
                )

                return func
            
            return wrapped_method

        return wrap_hook


def makePluginRegistrar():

    return PluginRegistrar


plugin_registrar = makePluginRegistrar()