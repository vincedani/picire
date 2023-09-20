# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

import logging

from picire.outcome import Outcome
from .events import EventHandler

logger = logging.getLogger(__name__)


class Logger(EventHandler):

    def iteration_started(self, iteration: int, **kwargs) -> None:
        logger.info(f'Iteration {iteration}')

    def cycle_started(self, cycle: int, configuration: list, **kwargs) -> None:
        logger.info(f'Run {cycle}')
        logger.info(f'\t Config size: {len(configuration)}')

    def finished(self, reason: str, result: str) -> None:
        logger.info(f'\t Stopped: {reason}')
        logger.info(f'\t Size of the result: {len(result)}')

    def succesful_reduction(self, configuration: list) -> None:
        logger.info(f'\t Reduced to: {len(configuration)}')

    def configuration_split(self, **kwargs) -> None:
        logger.info('\t Increased granularity')

    def test_started(self, configuration_id: str, **kwargs) -> None:
        logger.debug(f'\t [{configuration_id}]: test...')

    def test_finished(self, configuration_id: str, outcome: Outcome, **kwargs) -> None:
        logger.debug(f'\t [{configuration_id}]: test = {outcome.name}')

    def cache_lookup(self, configuration_id: str, outcome: Outcome, **kwargs) -> None:
        logger.debug(f'\t [{configuration_id}]: cache = {outcome.name}')

    def cache_insert(self,
                     configuration_id: str,
                     outcome: Outcome,
                     size: int,
                     length: int,
                     **kwargs) -> None:
        logger.debug(f'\t [{configuration_id}]: cache => {outcome.name} (cache: {length} items, {size} bytes)')
