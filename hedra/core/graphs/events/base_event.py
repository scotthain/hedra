from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import Any, Dict, TypeVar, Generic, List
from hedra.core.graphs.simple_context import SimpleContext
from hedra.core.graphs.hooks.registry.registry_types import (
    EventHook,
    TransformHook,
    ContextHook,
    ConditionHook
)
from hedra.core.graphs.hooks.registry.registry_types.hook import Hook
from hedra.core.graphs.hooks.hook_types.hook_type import HookType
from .event_types import EventTypes


T = TypeVar('T', EventHook, TransformHook, ContextHook, ConditionHook)


class BaseEvent(Generic[T]):

    __slots__ = (
        'target',
        'event_type',
        'source',
        'as_hook',
        'event_name',
        'event_order',
        'target_is_event',
        'context',
        'events',
        'execution_path',
        'next_args',
        'previous_map',
        'next_map'
    )

    def __init__(self, target: Hook, source: Hook) -> None:
        
        target.is_event = True
        self.target = target
        self.target_is_event = False

        if isinstance(target, BaseEvent):
            self.target_is_event = True

        self.event_type = EventTypes.EVENT
        self.event_name = source.name
        self.event_order = source.order

        self.source = source

        if target:
            self.target_name = self.target.name
            self.target_shortname = self.target.shortname

        self.as_hook = False
        self.context: SimpleContext = None
        self.events: Dict[str, BaseEvent] = {}
        self.execution_path = []
        self.previous_map = []
        self.next_map = []
        self.next_args: Dict[str, Dict[str,Any]] = defaultdict(dict)

    def __getattribute__(self, name: str) -> Any:
        
        target = None
        event_attrs = [
            'call', 
            'event_type',
            'target', 
            'source',
            'as_hook',
            'event_name',
            'event_order',
            'target_is_event',
            'context',
            'events',
            'execution_path',
            'next_args',
            'previous_map',
            'next_map'
        ]
      
        target = object.__getattribute__(self, 'target')
        
        if target and hasattr(target, name) and name not in event_attrs:
            return getattr(target, name)
        
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value: Any) -> None:

        try:

            target = object.__getattribute__(self, 'target')

            event_attrs = [
                'call', 
                'event_type',
                'target', 
                'source',
                'as_hook',
                'event_name',
                'event_order',
                'target_is_event',
                'context',
                'events',
                'execution_path',
                'next_args',
                'previous_map',
                'next_map'
            ]

            if target and hasattr(target, name) and name not in event_attrs:
                return setattr(target, name, value)

        except AttributeError:
            pass

        return super().__setattr__(name, value)

    async def call(self, **kwargs): 
   
        if len(self.next_args[self.event_name]) == 0:
            self.next_args[self.event_name] = kwargs

        if isinstance(self.source, (BaseEvent, ContextHook)):
            self.source.context = self.context

        results = await self.source.call(**{name: value for name, value in self.next_args[self.event_name].items() if name in self.source.params})

        next_events = [
            self.events.get(event_name) for event_name in  self.next_map if self.events.get(event_name) is not None
        ]

        for event in next_events:
            if isinstance(event, (BaseEvent, ContextHook)):
                event.context = self.context

            self.next_args[event.event_name].update(results)

        if self.source.hook_type == HookType.CONDITION and results is False:
            return

        else:
            results = await asyncio.gather(*[
                asyncio.create_task(
                    event.call(**self.next_args[event.event_name])
                ) for event in next_events
            ])

            return results


    async def execute_pre(self, *hook_args: List[Any]):
        results = None
        for source_name in self.previous_map:
            source: BaseEvent = self.events.get(source_name)
            source.context = self.context
            results = await source.call(*hook_args)

        return results

    async def execute_post(self, results):
        results = None
        for source_name in self.previous_map:
            source: BaseEvent = self.events.get(source_name)
            source.context = self.context
            results = await source.call(results)

        return results