# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

import logging

from picire.outcome import Outcome
from .events import EventHandler


class Logger(EventHandler):

    def __init__(self, logger = None) -> None:
        super().__init__()
        self.logger = logger or logging.getLogger(__name__)

    def iteration_started(self, iteration: int, **kwargs) -> None:
        self.logger.info(f'Iteration {iteration}')

    def cycle_started(self, cycle: int, configuration: list, **kwargs) -> None:
        self.logger.info(f'Run {cycle}')
        self.logger.info(f'\t Config size: {len(configuration)}')

    def finished(self, reason: str, result: str) -> None:
        self.logger.info(f'\t Stopped: {reason}')
        self.logger.info(f'\t Size of the result: {len(result)}')

    def successful_reduction(self, configuration: list) -> None:
        self.logger.info(f'\t Reduced to: {len(configuration)}')

    def configuration_split(self, **kwargs) -> None:
        self.logger.info('\t Increased granularity')

    def test_started(self, configuration_id: str, **kwargs) -> None:
        self.logger.debug(f'\t [{configuration_id}]: test...')

    def test_finished(self, configuration_id: str, outcome: Outcome, **kwargs) -> None:
        self.logger.debug(f'\t [{configuration_id}]: test = {outcome.name}')

    def cache_lookup(self, configuration_id: str, outcome: Outcome, **kwargs) -> None:
        self.logger.debug(f'\t [{configuration_id}]: cache = {outcome.name}')

    def cache_insert(self,
                     configuration_id: str,
                     outcome: Outcome,
                     length: int,
                     **kwargs) -> None:
        self.logger.debug(f'\t [{configuration_id}]: cache => {outcome.name} (cache: {length} items)')
