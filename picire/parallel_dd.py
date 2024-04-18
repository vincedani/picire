# Copyright (c) 2016-2023 Renata Hodovan, Akos Kiss.
# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from concurrent.futures import ALL_COMPLETED, FIRST_COMPLETED, ThreadPoolExecutor, wait
from os import cpu_count
from threading import Lock

from .cache import OutcomeCache
from .dd import DD
from .outcome import Outcome


class SharedCache(OutcomeCache):
    """
    Thread-safe cache representation that stores the evaluated configurations
    and their outcome.
    """

    def __init__(self, cache):
        self._cache = cache
        self._lock = Lock()

    def set_test_builder(self, test_builder):
        with self._lock:
            self._cache.set_test_builder(test_builder)

    def add(self, config, result):
        with self._lock:
            self._cache.add(config, result)

    def lookup(self, config):
        with self._lock:
            return self._cache.lookup(config)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def clean(self, config):
        with self._lock:
            self._cache.clean(config)

    def get_size(self):
        with self._lock:
            return self._cache.get_size()

    def __str__(self):
        with self._lock:
            return self._cache.__str__()


class ParallelDD(DD):

    def __init__(self, test, *, split=None, cache=None, id_prefix=None,
                 config_iterator=None, dd_star=False, stop=None,
                 proc_num=None, greeddy=False, observer=None):
        """
        Initialize a ParallelDD object.

        :param test: A callable tester object.
        :param split: Splitter method to break a configuration up to n parts.
        :param cache: Cache object to use.
        :param id_prefix: Tuple to prepend to config IDs during tests.
        :param config_iterator: Reference to a generator function that provides
            config indices in an arbitrary order.
        :param dd_star: Boolean to enable the DD star algorithm.
        :param stop: A callable invoked before the execution of every test.
        :param proc_num: The level of parallelization.
        """
        super().__init__(test=test, split=split, cache=cache, id_prefix=id_prefix, config_iterator=config_iterator, dd_star=dd_star, stop=stop, observer=observer)
        self._cache = SharedCache(self._cache)

        self._proc_num = proc_num or cpu_count()
        self.greeddy = greeddy


    def _reduce_config(self, run, subsets, complement_offset):
        """
        Perform the reduce task using multiple processes. Subset and complement
        set tests are mixed and don't wait for each other.

        :param run: The index of the current iteration.
        :param subsets: List of sets that the current configuration is split to.
        :param complement_offset: A compensation offset needed to calculate the
            index of the first unchecked complement (optimization purpose only).
        :return: Tuple: (list of subsets composing the failing config or None,
            next complement_offset).
        """
        n = len(subsets)
        tests = set()

        progress = []
        get_fails = lambda : [p[0] for p in progress if p[1] == Outcome.FAIL]

        with ThreadPoolExecutor(self._proc_num) as pool:
            for i in self._config_iterator(n):
                results, tests = wait(tests, timeout=0 if len(tests) < self._proc_num else None, return_when=FIRST_COMPLETED)
                self._process_results(results, progress)

                if len(get_fails()) > 0:
                    break

                if i >= 0:
                    config_id = (f'r{run}', f's{i}')
                    config_set = subsets[i]
                else:
                    i = (-i - 1 + complement_offset) % n
                    config_id = (f'r{run}', f'c{i}')
                    config_set = [c for si, s in enumerate(subsets) for c in s if si != i]
                    i = -i - 1

                # If we checked this test before, return its result
                content = self._cache._cache._test_builder(config_set)
                outcome = self._lookup_cache(content, config_id)
                if outcome is Outcome.PASS:
                    continue
                if outcome is Outcome.FAIL:
                    progress.append((i, outcome))
                    break

                self._check_stop()

                progress.append((i, None))
                tests.add(pool.submit(self._test_config_with_index, i, content, config_id))

            results, _ = wait(tests, return_when=ALL_COMPLETED)
            self._process_results(results, progress)

        interesting_indices = get_fails()

        if not len(interesting_indices):
            return None, complement_offset

        return self._greedy_search(subsets, n, interesting_indices)

    def _test_config_with_index(self, index, config, config_id):
        return index, self._test_config(config, config_id)

    def _process_results(self, results, progress):
        for result in results:
            index, outcome = result.result()
            if outcome == Outcome.PASS:
                progress.remove((index, None))
                continue

            index_to_modify = [p[0] for p in progress].index(index)
            progress[index_to_modify] = (index, outcome)

    def _greedy_search(self, orig_subsets, initial_length, interesting_indices, retest=False):
        def _get_subsets_with_fvalue(subsets, value):
            fvalue = value
            # fvalue contains the index of the cycle in the previous loop
            # which was found interesting. Otherwise it's n.
            if fvalue < 0:
                # Interesting complement is found.
                # In next run, start removing the following subset
                fvalue = -fvalue - 1
                return subsets[:fvalue] + subsets[fvalue + 1:], fvalue
            if fvalue < initial_length:
                # Interesting subset is found.
                fvalue = 0
                return [subsets[fvalue]], fvalue

        def _perform_test(subsets, index, _fvalue):
            self._check_stop()

            config_set = [c for s in subsets for c in s]
            content = self._cache._cache._test_builder(config_set)
            config_id = (f'd{index}', f'f{_fvalue}')
            outcome = self._lookup_cache(content, config_id)

            if not outcome:
                outcome = self._test_config(content, config_id)

            return outcome

        subsets = orig_subsets
        for i, value in enumerate(interesting_indices):
            _subsets, _fvalue = _get_subsets_with_fvalue(subsets, value)
            # The not optimal bad, old method
            if not self.greeddy:
                return _subsets, _fvalue

            # DEBUG
            # outcome = _perform_test(_subsets, i, _fvalue)

            # An item has been already removed from the config
            if i > 0 and retest:
                outcome = _perform_test(_subsets, _fvalue, i)

                # Greedily removing the "FAILs" doesn't did the magic.
                if outcome is Outcome.PASS:
                    continue

            subsets, fvalue = _subsets, _fvalue

        # Re-test the final result only if the intermediate merges are not tested immediately.
        if len(interesting_indices) > 1 and not retest:
            outcome = _perform_test(subsets, fvalue, len(interesting_indices) + 1)
            if outcome is Outcome.PASS:
                return self._greedy_search(orig_subsets, initial_length, interesting_indices, True)

        return subsets, fvalue
