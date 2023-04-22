import asyncio
import time
import signal
from hedra.core.experiments.variant import Variant
from hedra.core.engines.client.config import Config
from hedra.core.personas.batching.param_type import ParamType
from hedra.core.personas.types.default_persona import DefaultPersona
from typing import Dict, Any, List, Union
from .algorithms import get_algorithm
from .algorithms.types.base_algorithm import BaseAlgorithm
from .optimizer import Optimizer


class DistributionFitOptimizer(Optimizer):
    
    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)

        self.algorithm: BaseAlgorithm = None

        self.variant_weight = self.stage_config.experiment.get('weight')
        self.distribution_intervals = self.stage_config.experiment.get('intervals')
        self.distribution_type = self.stage_config.experiment.get('distribution_type')
        self.distribution = self.stage_config.experiment.get('distribution')

        self.variant = Variant(
            self.stage_name,
            weight=self.variant_weight,
            distribution=self.distribution_type,
        )

        self.algorithms: List[BaseAlgorithm] = []
        self.target_interval_completions: int = 0
        self.completion_rates = {}

        for distribution_idx in range(len(self.distribution)):
            self.algorithms.append(get_algorithm(
                self.algorithm_type,
                {
                    **config,
                    'stage_config': self.stage_config
                },
                distribution_idx=distribution_idx
            ))
            

    def _setup_persona(self, stage_config: Config):
        persona = DefaultPersona(stage_config)
        persona.collect_analytics = True
        persona.optimization_active = True
        persona.setup(self.stage_hooks, self.metadata_string)

        return persona
    
    def optimize(self):

        results = None

        self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Starting optimization')
        self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization config: Time Limit - {self._optimization_time_limit}')
        self.start = 0

        distribution_optimized_params = []

        for distribution_value, algorithm in zip(self.distribution, self.algorithms):
            self.completion_rates = {}
            self.algorithm: BaseAlgorithm = algorithm
            self.algorithm.batch_time = self.stage_config.total_time/self.distribution_intervals

            self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization config: Algorithm - {self.algorithm_type}')
            self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization config: Batch Time - {self.algorithm.batch_time}')
            self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization config: Max Iter - {self.algorithm.max_iter}')


            self.target_interval_completions = distribution_value

            self.start = time.time()
            self.elapsed = 0
            self._current_iter = 0

            results = self.algorithm.optimize(self._run_optimize)

            optimized_params = {}

            for idx in range(len(results.x)):
                param_name = self.algorithm.param_names[idx]
                optimiazed_param_name = f'optimized_{param_name}'
                param = self.algorithm.param_values.get(param_name, {})
                param_type = param.get('type')

                if param_type == ParamType.INTEGER:
                    optimized_params[optimiazed_param_name] = int(results.x[idx])

                else:
                    optimized_params[optimiazed_param_name] = float(results.x[idx])

            distribution_optimized_params.append(optimized_params.get('optimized_batch_size'))        
        
        self.total_optimization_time = time.time() - self.start

        self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization took - {round(self.total_optimization_time, 2)} - seconds')
        self.logger.filesystem.sync['hedra.optimize'].info(f'{self.metadata_string} - Optimization - max actions per second - {self._max_aps}')

        self.optimized_results = {
            'optimized_distribution': distribution_optimized_params,
            'optimization_iters': self.algorithm.max_iter,
            'optimization_iter_duation': self.algorithm.batch_time,
            'optimization_total_time': self.total_optimization_time,
            'optimization_max_aps': self._max_aps
        }

        self.total_optimization_time = time.time() - self.start

        return self.optimized_results

    async def _optimize(self, xargs: List[Union[int, float]]):

        if self._current_iter <= self.algorithm.max_iter:

            persona = self._setup_persona(self.stage_config)

            for idx, param in enumerate(xargs):
                param_name = self.algorithm.param_names[idx]
                param = self.algorithm.param_values.get(param_name, {})
                param_type = param.get('type')

                if param_type == ParamType.INTEGER:
                    xargs[idx] = int(xargs[idx])

                else:
                    xargs[idx] = float(xargs[idx])

                param['value'] = xargs[idx]

                self.current_params[param_name] = xargs[idx]
                self.algorithm.current_params[param_name] = xargs[idx]

            persona = self.algorithm.update_params(persona)
            persona.set_concurrency(persona.batch.size)

            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter}')

            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter} - Batch Size - {persona.batch.size}')
            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter} - Batch Interval - {persona.batch.interval}')
            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter} - Batch Gradient - {persona.batch.gradient}')

            completed_count = 0

            try:
                results = await persona.execute()
                completed_count = len([result for result in results if result.error is None])

            except Exception:
                pass

            elapsed = persona.end - persona.start

            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter} - took - {round(elapsed, 2)} - seconds')
       
            if completed_count < 1:
                completed_count = 1

            self.completion_rates[persona.batch.size] = completed_count

            error = (completed_count - self.target_interval_completions)**2

            await self.logger.filesystem.aio['hedra.optimize'].debug(f'{self.metadata_string} - Optimizer iteration - {self._current_iter} - Target error- {error}')

            return error

        return self.base_batch_size**2
    
    def _run_optimize(self, xargs):

        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)

        def handle_loop_stop(signame):
            try:
                self._event_loop.close()

            except BrokenPipeError:
                pass
                
            except RuntimeError:
                pass

        for signame in ('SIGINT', 'SIGTERM'):

            self._event_loop.add_signal_handler(
                getattr(signal, signame),
                lambda signame=signame: handle_loop_stop(signame)
            )

        self._event_loop.set_exception_handler(self._handle_async_exception)

        error = self._event_loop.run_until_complete(
            self._optimize(xargs)
        )

        self._current_iter += 1
        self.elapsed = time.time() - self.start

        self._event_loop.close()
 
        return error
    