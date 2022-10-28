import json
from typing import Generic, TypeVar
from hedra.reporting.events.types.base_event import BaseEvent
from .result import Result

T = TypeVar('T')

class Event(BaseEvent, Generic[T]):

    __slots__ = (
        'fields',
        'type'
    )

    def __init__(self, result: Result[T]) -> None:
        super().__init__(result)

        self.timings = result.as_timings()
        self.time = result.times['complete'] - result.times['start']

    def serialize(self):

        return json.dumps({
            'name': self.name,
            'stage': self.stage,
            'shortname': self.shortname,
            'checks': [check.__name__ for check in self.checks],
            'error': str(self.error),
            'time': self.time,
            'type': self.type,
            'source': self.source,
        })