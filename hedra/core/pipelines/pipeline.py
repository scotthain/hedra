
import asyncio
from turtle import pen
import networkx
from typing import Dict, List
from hedra.core.pipelines.transitions.exceptions.exceptions import IsolatedStageError
from hedra.core.pipelines.stages.stage import Stage
from hedra.core.pipelines.stages.types.stage_types import StageTypes
from hedra.core.pipelines.transitions.transition import Transition
from .transitions import TransitionAssembler, local_transitions
from .status import PipelineStatus



class Pipeline:
    status = PipelineStatus.IDLE

    def __init__(self, stages: List[Stage], cpus: int=None, worker_id: int=None) -> None:
        
        self.status = PipelineStatus.INITIALIZING
        self.graph = networkx.DiGraph()
        self.transitions_graph = []
        self._transitions: List[List[Transition]] = []
        self._results = None

        self.stage_types = {
            subclass.stage_type: subclass for subclass in Stage.__subclasses__()
        }

        self.instances: Dict[StageTypes, List[Stage]] = {}
        for stage in self.stage_types.values():
            stage_instances = stage.__subclasses__()
            self.instances[stage.stage_type] = stage_instances

        self.stages: Dict[str, Stage] = {stage.__name__: stage for stage in stages}
        
        self.graph.add_nodes_from([
            (
                stage_name, 
                {"stage": stage}
            ) for stage_name, stage in self.stages.items()
        ])

        for stage in stages:
            for dependency in stage.dependencies:
                if self.graph.nodes.get(dependency.__name__):
                    self.graph.add_edge(dependency.__name__, stage.__name__)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.runner = TransitionAssembler(
            local_transitions,
            cpus=cpus,
            worker_id=worker_id
        )

    def validate(self):

        self.status = PipelineStatus.VALIDATING
        # If we havent specified a Validate stage for save aggregated results,
        # append one.
        if len(self.instances.get(StageTypes.VALIDATE)) < 1:
            self._prepend_stage(StageTypes.VALIDATE)

        # A user will never specify an Idle stage. Instead, we prepend one to 
        # serve as the source node for a graphs, ensuring graphs have a 
        # valid starting point and preventing the user from forgetting things
        # like a Setup stage.
        self._prepend_stage(StageTypes.IDLE)

        # If we haven't specified an Analyze stage for results aggregation,
        # append one.
        if len(self.instances.get(StageTypes.ANALYZE)) < 1:
           self._append_stage(StageTypes.ANALYZE)

        # If we havent specified a Submit stage for save aggregated results,
        # append one.
        if len(self.instances.get(StageTypes.SUBMIT)) < 1:
            self._append_stage(StageTypes.SUBMIT)

        # Like Idle, a user will never specify a Complete stage. We append
        # one to serve as the sink node, ensuring all Graphs executed can
        # reach a single exit point.
        self._append_stage(StageTypes.COMPLETE)

        self.runner.generate_stages(self.stages)
        self.transitions_graph = self.runner.build_transitions_graph(self.execution_order)
        self.runner.map_to_setup_stages(self.graph)

        for isolate_stage_name in networkx.isolates(self.graph):
            raise IsolatedStageError(
                self.stages.get(isolate_stage_name)
            )

        self.status = PipelineStatus.ASSEMBLING
        for transition_group in self.transitions_graph:
            
            transtions = []
            
            for transition_sequence in list(transition_group.values()):
                transtions.extend(transition_sequence)

            self._transitions.append(transtions)

    async def run(self):
        
        self.status = PipelineStatus.RUNNING

        for transition_group in self._transitions:
            
            for transtition in transition_group:
                print(f'Executing {transtition.from_stage}')
                
            results = await asyncio.gather(*[
                asyncio.create_task(transition.transition(
                    transition.from_stage, 
                    transition.to_stage
                )) for transition in transition_group
            ])

            for error, next_stage in results:
                
                if next_stage == StageTypes.ERROR:

                    self.status = PipelineStatus.FAILED

                    print(f'Executing error transition -  {error.from_stage}')

                    error_transtiton = self.runner.create_error_transition(error)

                    await error_transtiton.transition(
                        error_transtiton.from_stage,
                        error_transtiton.to_stage
                    ) 
                    
            if self.status == PipelineStatus.FAILED:
                break
        
        if self.status == PipelineStatus.RUNNING:
            self.status = PipelineStatus.COMPLETE

            completion_stages = self.runner.instances_by_type.get(StageTypes.COMPLETE)
            serialized_results = {}

            for completion_stage in completion_stages:
                results = completion_stage.context.summaries

                stages = results.get('stages')
                
                for stage_name, stage in stages.items():
                    serialized_results[stage_name] = {}

                    actions = stage.get('actions')
                    for action_name, action in actions.items():
                        serialized_results[stage_name][action_name] = action.serialize()

            self._results = serialized_results

        stages_for_shutdown = []
        for stage in self.runner.generated_stages.values():
            if stage.requires_shutdown:
                stages_for_shutdown.append(stage._shutdown_task)

        print('Shutting down!')
        await asyncio.gather(*stages_for_shutdown)
        print('Done!')

        return self._results

    async def cleanup(self):
        pass

    def _append_stage(self, stage_type: StageTypes):

        appended_stage = self.stage_types.get(stage_type)
        last_cut = self.execution_order[-1]

        appended_stage.dependencies = list()

        for stage_name in last_cut:
            stage = self.stages.get(stage_name)

            appended_stage.dependencies.append(stage)

        self.graph.add_node(appended_stage.__name__, stage=appended_stage)

        for stage_name in last_cut:
            self.graph.add_edge(stage_name, appended_stage.__name__)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.stages[appended_stage.__name__] = appended_stage
        self.instances[appended_stage.stage_type].append(appended_stage)

    def _prepend_stage(self, stage_type: StageTypes):
        prepended_stage = self.stage_types.get(stage_type)
        first_cut = self.execution_order[0]

        prepended_stage.dependencies = list()

        for stage_name in first_cut:
            stage = self.stages.get(stage_name)

            stage.dependencies.append(prepended_stage)

        self.graph.add_node(prepended_stage.__name__, stage=prepended_stage)

        for stage_name in first_cut:
            self.graph.add_edge(prepended_stage.__name__, stage_name)

        self.execution_order = [
            generation for generation in networkx.topological_generations(self.graph)
        ]

        self.stages[prepended_stage.__name__] = prepended_stage
        self.instances[prepended_stage.stage_type].append(stage_type)