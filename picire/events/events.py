# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from abc import ABC, abstractmethod
from picire.outcome import Outcome

class EventHandler(ABC):

    @abstractmethod
    def iteration_started(self, iteration : int, configuration : list) -> None:
        """
        A new iteration started.
        :param iteration: Number of the started iteration.
        :param configuration: Input configuration of the iteration.
        """
        pass

    @abstractmethod
    def cycle_started(self, iteration : int, cycle : int, configuration : list) -> None:
        """
        A new cycle started inside an iteration.
        :param iteration: Number of the current iteration.
        :param cycle: Number of the started reduction cycle inside the
            `iteration`.
        :param configuration: Input configuration of the cycle.

        """
        pass

    @abstractmethod
    def finished(self, reason : str, result : str) -> None:
        """
        The reduction has been finished (or stopped for some reason).
        :param reason: Reason for stopping the reduction.
        :param result: Result of the reduction process. It might not be the
            smallest possible form of the input, however, it is till failing
            test case.
        """
        pass

    @abstractmethod
    def succesful_reduction(self, configuration : list) -> None:
        """
        A successful reduction step has been performed.
        :param configuration: Newly found, failing configuration.
        """
        pass

    @abstractmethod
    def configuration_split(self, configuration : list) -> None:
        """
        The configuration has a new splitting, e.g., because of the increased
        granularity.
        :param configuration: Split configuration.
        """
        pass

    @abstractmethod
    def test_started(self, configuration : list, configuration_id : str) -> None:
        """
        The configuration testing has been started.
        :param configuration: Configuration to be tested.
        :param configuration_id: Unique identifier of the configuration.
        """
        pass

    @abstractmethod
    def test_finished(self, configuration : list, configuration_id : str, outcome : Outcome) -> None:
        """
        The configuration testing has been finished.
        :param configuration: Configuration to be tested.
        :param configuration_id: Unique identifier of the configuration.
        :param outcome: Outcome of the testing function (FAIL or PASS).
        """
        pass

    @abstractmethod
    def cache_lookup(self, configuration : list, configuration_id : str, outcome : Outcome) -> None:
        """
        A cache lookup has been performed and its result.
        :param configuration: Configuration to be searched.
        :param configuration_id: Unique identifier of the configuration.
        :param outcome: Outcome of the cache (FAIL or PASS, or None if cache miss).
        """
        pass
