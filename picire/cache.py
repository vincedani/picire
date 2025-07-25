# Copyright (c) 2016-2023 Renata Hodovan, Akos Kiss.
# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from hashlib import sha3_256

from .outcome import Outcome

from sys import setrecursionlimit
from pympler.asizeof import asizeof as _asizeof, flatsize as _flatsize

setrecursionlimit(100000) # ConfigCache needs this hack.


class CacheRegistry(object):
    registry = {}

    @classmethod
    def register(cls, cache_name):
        def decorator(cache_class):
            cls.registry[cache_name] = cache_class
            return cache_class
        return decorator


class OutcomeCache(object):
    """
    Abstract base class for configuration outcome caching strategies.
    """

    def set_test_builder(self, test_builder):
        """
        Set the test builder for the cache.

        :param test_builder: Callable object that creates test case from a
            configuration. It must be identical to the test builder used by the
            tester class.
        """
        raise NotImplementedError()

    def add(self, config, result):
        """
        Add a new configuration to the cache.

        :param config: The configuration to save.
        :param result: The outcome of the added configuration.
        """
        raise NotImplementedError()

    def lookup(self, config):
        """
        Cache lookup to find out the outcome of a given configuration.

        :param config: The configuration we are looking for.
        :return: PASS or FAIL if config is in the cache; None, otherwise.
        """
        raise NotImplementedError()

    def clear(self):
        """
        Clear the cache.
        """
        raise NotImplementedError()

    def clean(self, config):
        """
        Delete cache entries that are larger than the current one.

        :param config: The configuration from wich larger entries are deleted.
        """
        raise NotImplementedError()

    def get_size(self):
        """
        Returns the total size of the stored cache data and the cache entry count.
        """
        raise NotImplementedError()


@CacheRegistry.register('none')
class NoCache(OutcomeCache):
    """
    Implementation of a disabled cache. Does not store anything, so no cache hit
    can occur, ever.
    """

    def __init__(self, *, cache_fail=False, evict_after_fail=True, measure_memory=False):
        """
        :param cache_fail: Unused, only added for compatibility with other cache
            implementations.
        :param evict_after_fail: Unused, only added for compatibility with other
            cache implementations.
        """

    def set_test_builder(self, test_builder):
        pass

    def add(self, config, result):
        pass

    def lookup(self, config):
        return None

    def clear(self):
        pass

    def clean(self, config):
        pass

    def __str__(self):
        return '{}'

    def get_size(self):
        """
        Returns the total size of the stored cache data and the cache entry count.
        """
        0, 0


@CacheRegistry.register('config')
class ConfigCache(OutcomeCache):
    """
    Re-implementation of Zeller's original caching approach. The cache
    associates configurations (i.e., lists of elements) with their test
    outcomes, using a tree as the underlying data structure.
    """

    class _Entry(object):
        """
        This class holds test outcomes for configurations. This avoids running
        the same test twice.

        The outcome cache is implemented as a tree.  Each node points to the
        outcome of the remaining list.

        Example: ([1, 2, 3], PASS), ([1, 2], FAIL), ([1, 4, 5], FAIL):

             (2, FAIL)--(3, PASS)
            /
        (1, None)
            \
             (4, None)--(5, FAIL)
        """

        def __init__(self):
            self.result = None  # Result so far
            self.tail = {}  # Points to outcome of tail

    def __init__(self, *, cache_fail=False, evict_after_fail=True, measure_memory=False):
        """
        :param cache_fail: Add configurations with FAIL outcome to the cache.
        :param evict_after_fail: When a configuration with a FAIL outcome is
            added to the cache, evict all larger configurations.
        """
        # NOTE: evict_after_fail=True should be safe as after a fail is found,
        # reduction continues from there, generating only even smaller test
        # cases, and larger tests are never re-tested again.
        self._cache_fail = cache_fail
        self._evict_after_fail = evict_after_fail
        self.measure_memory = measure_memory
        self._root = self._Entry()

    def set_test_builder(self, test_builder):
        pass

    def add(self, config, result):
        if result is Outcome.PASS or self._cache_fail:
            p = self._root
            for cs in config:
                if cs not in p.tail:
                    p.tail[cs] = self._Entry()
                p = p.tail[cs]
            p.result = result

    def lookup(self, config):
        p = self._root
        for cs in config:
            if cs not in p.tail:
                return None
            p = p.tail[cs]
        return p.result

    def clear(self):
        self._root = self._Entry()

    def clean(self, config):
        def _evict(p, length):
            if length == 0:
                p.tail = {}
            else:
                for e in p.tail.values():
                    _evict(e, length - 1)

        if not self._evict_after_fail:
            return

        _evict(self._root, len(config))

    def __str__(self):
        def _str(p):
            if p.result is not None:
                s.append(f'\t[{", ".join(repr(cs) for cs in config)}]: {p.result.name!r},\n')
            for cs, e in sorted(p.tail.items()):
                config.append(cs)
                _str(e)
                config.pop()

        config, s = [], []
        s.append('{\n')
        _str(self._root)
        s.append('}')
        return ''.join(s)

    def get_size(self):
        if not self.measure_memory:
            return 0, 0

        def _traversal(node, tsize=0, tcount=0):
            tsize += _flatsize(node)
            tcount += 1

            for e in node.tail.values():
                tsize, tcount = _traversal(e, tsize, tcount)

            return tsize, tcount

        return _traversal(self._root)


@CacheRegistry.register('config-tuple')
class ConfigTupleCache(OutcomeCache):
    """
    This cache associates configurations (i.e., lists of elements) with their
    test outcomes, using a dictionary of tuples as the underlying data
    structure.
    """

    def __init__(self, *, cache_fail=False, evict_after_fail=True, measure_memory=False):
        """
        :param cache_fail: Add configurations with FAIL outcome to the cache.
        :param evict_after_fail: When a configuration with a FAIL outcome is
            added to the cache, evict all larger configurations.
        """
        # NOTE: evict_after_fail=True should be safe as after a fail is found,
        # reduction continues from there, generating only even smaller test
        # cases, and larger tests are never re-tested again.
        self._cache_fail = cache_fail
        self._evict_after_fail = evict_after_fail
        self.measure_memory = measure_memory
        self._container = {}

    def set_test_builder(self, test_builder):
        pass

    def add(self, config, result):
        if result is Outcome.PASS or self._cache_fail:
            self._container[tuple(config)] = result

    def lookup(self, config):
        return self._container.get(tuple(config), None)

    def clear(self):
        self._container = {}

    def clean(self, config):
        if not self._evict_after_fail:
            return

        length = len(config)
        evicted = [c for c in self._container if len(c) > length]
        for c in evicted:
            del self._container[c]

    def __str__(self):
        return '{\n%s}' % ''.join(f'\t{c!r}: {r.name!r},\n' for c, r in sorted(self._container.items()))

    def get_size(self):
        if not self.measure_memory:
            return 0, 0

        return _asizeof(self._container), len(self._container)


@CacheRegistry.register('content')
class ContentCache(OutcomeCache):
    """
    A cache implementation that associates test contents (built from
    configurations) with their test outcomes.
    """

    def __init__(self, *, cache_fail=False, evict_after_fail=True, measure_memory=False):
        """
        :param cache_fail: Add configurations with FAIL outcome to the cache.
        :param evict_after_fail: When a configuration with a FAIL outcome is
            added to the cache, evict all larger configurations.
        """
        # NOTE: evict_after_fail=True should be safe as after a fail is found,
        # reduction continues from there, generating only even smaller test
        # cases, and larger tests are never re-tested again.
        self._cache_fail = cache_fail
        self._evict_after_fail = evict_after_fail
        self.measure_memory = measure_memory
        self._container = {}
        self._test_builder = None

    def set_test_builder(self, test_builder):
        self._test_builder = test_builder

    def add(self, config, result):
        if result is Outcome.FAIL and not self._cache_fail and not self._evict_after_fail:
            return

        # TODO (23114): Temporary tweaks: save the config -> content transformation and do it in an outer
        # level! Needs some adjustments later.
        test_content = config # self._test_builder(config)

        if result is Outcome.PASS or self._cache_fail:
            self._container[test_content] = result

    def lookup(self, config):
        test_content = config
        return self._container.get(test_content, None)

    def clear(self):
        pass

    def clean(self, config):
        if not self._evict_after_fail:
            return

        length = len(self._test_builder(config))
        evicted = [c for c in self._container if len(c) > length]
        for c in evicted:
            del self._container[c]

    def __str__(self):
        return '{\n%s}' % ''.join(f'\t{c!r}: {r.name!r},\n' for c, r in sorted(self._container.items()))

    def get_size(self):
        if not self.measure_memory:
            return 0, 0

        return _asizeof(self._container), len(self._container)


@CacheRegistry.register('content-hash')
class ContentHashCache(OutcomeCache):
    """
    A cache implementation that associates hashed test contents (built from
    configurations and hashed afterwards) with their test outcomes.
    """

    def __init__(self, *, cache_fail=False, evict_after_fail=True, measure_memory=False, hash_ctor=sha3_256):
        """
        :param cache_fail: Unused, only added for compatibility with other cache
            implementations.
        :param evict_after_fail: When a configuration with a FAIL outcome is
            added to the cache, evict all larger configurations.
        :param hash_ctor: A hash object constructor from hashlib.
        """
        # NOTE: Caching by hashed content is only safe if FAIL outcomes are not
        # stored in the cache. Therefore, the value of the cache_fail argument
        # is not taken into account but is forced to False.
        # NOTE: evict_after_fail=True should be safe as after a fail is found,
        # reduction continues from there, generating only even smaller test
        # cases, and larger tests are never re-tested again.
        self._evict_after_fail = evict_after_fail
        self._hash_ctor = hash_ctor
        self.measure_memory = measure_memory
        self._container = {}
        self._test_builder = None

    def _hash_content(self, test_content):
        return self._hash_ctor(test_content.encode('utf-8')).digest()

    def set_test_builder(self, test_builder):
        self._test_builder = test_builder

    def add(self, config, result):
        if result is Outcome.FAIL and not self._evict_after_fail:
            return

        # TODO (23114): Temporary tweaks: save the config -> content transformation and do it in an outer
        # level! Needs some adjustments later.
        test_content = config # self._test_builder(config)
        length = len(test_content)

        if result is Outcome.PASS:
            self._container[self._hash_content(test_content)] = (result, length)

    def lookup(self, config):
        test_content = config # self._test_builder(config)
        result, _ = self._container.get(self._hash_content(test_content), (None, None))
        return result

    def clear(self):
        pass

    def clean(self, config):
        if not self._evict_after_fail:
            return

        length = len(self._test_builder(config))

        evicted = [h for h, (_, l) in self._container.items() if l > length]
        for h in evicted:
            del self._container[h]

    def __str__(self):
        return '{\n%s}' % ''.join(f'\t{h.hex()}/{l}: {r.name!r},\n' for h, (r, l) in sorted(self._container.items()))

    def get_size(self):
        if not self.measure_memory:
            return 0, 0

        return _asizeof(self._container), len(self._container)
