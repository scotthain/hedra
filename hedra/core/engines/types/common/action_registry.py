from typing import (
    Dict,
    List,
    Iterable,
    Union
)
from hedra.core.engines.types.graphql.action import GraphQLAction
from hedra.core.engines.types.graphql_http2.action import GraphQLHTTP2Action
from hedra.core.engines.types.grpc.action import GRPCAction
from hedra.core.engines.types.http.action import HTTPAction
from hedra.core.engines.types.http2.action import HTTP2Action
from hedra.core.engines.types.http3.action import HTTP3Action
from hedra.core.engines.types.playwright.command import PlaywrightCommand
from hedra.core.engines.types.task.task import Task
from hedra.core.engines.types.udp.action import UDPAction
from hedra.core.engines.types.websocket.action import WebsocketAction


Action = Union[
    GraphQLAction,
    GraphQLHTTP2Action,
    GRPCAction,
    HTTPAction,
    HTTP2Action,
    HTTP3Action,
    PlaywrightCommand,
    Task,
    UDPAction,
    WebsocketAction
]


class ActionRegistry:

    def __init__(self) -> None:
        self._actions: Dict[str, Action] = {}

    def __iter__(self) -> Iterable[Action]:
        for action in self._actions.values():
            yield action

    def names(self):
        for action_name in self._actions.keys():
            yield action_name

    def get_action(self, action_name: str) -> Union[Action, None]:
        return self._actions.get(action_name)

    def get_stage_actions(self, stage_name: str) -> List[Action]:
        return [
            action for action in self._actions.values() if action.stage == stage_name
        ]
            

def makeActionRegistry():
    return ActionRegistry()


actions_regsitry = makeActionRegistry()