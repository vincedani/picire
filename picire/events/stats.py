# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from multiprocessing import Value
from time import time

from .events import EventHandler
from picire.outcome import Outcome

class SharedCounter(object):
    def __init__(self, value):
        self._value = Value('i', value)

    def __iadd__(self, other):
        with self._value.get_lock():
            self._value.value += other
            return self

    def __int__(self):
        return self._value.value

    def __str__(self):
        return str(self._value.value)


class Statistics(EventHandler):
    """
    Event handler implementation that collects statistics during reduction.
    The gathered information can be accessed via `flush` function.
    """
    def __init__(self, counterclass=SharedCounter):
        # Number of executed tests: equals to passing_tests + failing_tests in
        # single process mode, but not necessarily in parallel mode because not all
        # tests finish to give a pass/fail result
        self.tests_started = counterclass(0)
        self.tests_passed = counterclass(0)
        self.tests_failed = counterclass(0)

        self.cache_hits = counterclass(0)

        self.runtime = None
        self._start_time = time()

        self.iterations = counterclass(0)
        self.cycles = counterclass(0)

    def iteration_started(self, iteration : int, configuration : list) -> None:
        self.iterations += 1

    def cycle_started(self, iteration : int, cycle : int, configuration : list) -> None:
        self.cycles += 1

    def finished(self, reason : str, result : str) -> None:
        self.runtime = round(time() - self._start_time, 2)

    def succesful_reduction(self, configuration : list) -> None:
        pass

    def configuration_split(self, configuration : list) -> None:
        pass

    def test_started(self, configuration : list, configuration_id : str) -> None:
        self.tests_started += 1

    def test_finished(self, configuration : list, configuration_id : str, outcome : Outcome) -> None:
        if outcome is Outcome.FAIL:
            self.tests_failed += 1
        else:
            self.tests_passed += 1

    def cache_lookup(self, configuration : list, configuration_id : str, outcome : Outcome) -> None:
        self.cache_hits += 1

    def flush(self):
        stats = dict([(x, y) for x, y in vars(self).items() if not x.startswith('_')])

        for key in stats:
            value = stats[key]
            if type(value) == SharedCounter:
                value = int(value)

            stats[key] = value

        return stats
