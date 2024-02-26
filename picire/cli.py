# Copyright (c) 2016-2023 Renata Hodovan, Akos Kiss.
# Copyright (c) 2023 Daniel Vince.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

import argparse
import codecs
import json
import os
import sys
import time

from datetime import timedelta
from math import inf
from multiprocessing import cpu_count
from os.path import basename, exists, join, realpath
from shutil import rmtree

try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata

import chardet
import inators

from inators import log as logging

from .cache import CacheRegistry
from .dd import DD
from .iterator import CombinedIterator, IteratorRegistry
from .limit_reduction import LimitReduction
from .parallel_dd import ParallelDD
from .reduction_exception import ReductionException, ReductionStopped
from .splitter import SplitterRegistry
from .subprocess_test import ConcatTestBuilder, SubprocessTest

from .events.event_listener import EventListener
from .events.stats import Statistics
from .events.logger import Logger

logger = logging.getLogger('picire')
__version__ = metadata.version(__package__)


def create_parser():
    def int_or_inf(value):
        if value == 'inf':
            return inf
        value = int(value)
        if value < 2:
            raise argparse.ArgumentTypeError(f'invalid value: {value!r} (must be at least 2)')
        return value

    parser = argparse.ArgumentParser(description='Command line interface of the "picire" test case reducer')
    parser.add_argument('-i', '--input', metavar='FILE', required=True,
                        help='test case to be reduced')

    # Base reduce settings.
    parser.add_argument('--cache', metavar='NAME',
                        choices=sorted(CacheRegistry.registry.keys()), default='config',
                        help='cache strategy (%(choices)s; default: %(default)s)')
    parser.add_argument('--split', metavar='NAME',
                        choices=sorted(SplitterRegistry.registry.keys()), default='zeller',
                        help='split algorithm (%(choices)s; default: %(default)s)')
    parser.add_argument('--test', metavar='FILE', required=True,
                        help='test command that decides about interestingness of an input')
    parser.add_argument('--granularity', metavar='N', type=int_or_inf, default=2,
                        help='initial granularity and split factor (integer or \'inf\'; default: %(default)d)')
    parser.add_argument('--encoding', metavar='NAME',
                        help='test case encoding (default: autodetect)')
    parser.add_argument('--no-dd-star', dest='dd_star', default=True, action='store_false',
                        help='run the ddmin algorithm only once')

    # Extra settings for parallel reduce.
    parser.add_argument('-p', '--parallel', action='store_true', default=False,
                        help='run DD in parallel')
    parser.add_argument('-j', '--jobs', metavar='N', type=int, default=cpu_count(),
                        help='maximum number of test commands to execute in parallel (has effect in parallel mode only; default: %(default)s)')

    # Tweaks how to walk through the chunk lists.
    parser.add_argument('--complement-first', dest='subset_first', action='store_false', default=True,
                        help='check complements first')
    parser.add_argument('--subset-iterator', metavar='NAME',
                        choices=sorted(IteratorRegistry.registry.keys()), default='forward',
                        help='ordering strategy for looping through subsets (%(choices)s; default: %(default)s)')
    parser.add_argument('--complement-iterator', metavar='NAME',
                        choices=sorted(IteratorRegistry.registry.keys()), default='forward',
                        help='ordering strategy for looping through complements (%(choices)s; default: %(default)s)')

    # Tweaks for caching.
    parser.add_argument('--cache-fail', action='store_true', default=False,
                        help='store failing, i.e., interesting test cases in the cache')
    parser.add_argument('--no-cache-evict-after-fail', dest='evict_after_fail', action='store_false', default=True,
                        help='disable the eviction of larger test cases from the cache when a failing, i.e., interesting test case is found')

    # Limits on the reduction.
    parser.add_argument('--limit-time', metavar='SEC', type=int,
                        help='limit the execution time of reduction (in seconds; may result in non-minimal output)')
    parser.add_argument('--limit-tests', metavar='N', type=int,
                        help='limit the number of test command executions (may result in non-minimal output)')

    # Logging settings.
    inators.arg.add_log_level_argument(parser)
    parser.add_argument('--log-format', metavar='FORMAT', default='%(message)s',
                        help='printf-style format string of diagnostic messages (default: %(default)s)')
    parser.add_argument('--log-datefmt', metavar='FORMAT', default='%Y-%m-%d %H:%M:%S',
                        help='strftime-style format string of timestamps in diagnostic messages (default: %(default)s)')

    # Additional settings.
    parser.add_argument('-o', '--out', metavar='DIR',
                        help='working directory (default: input.timestamp)')
    parser.add_argument('--no-cleanup', dest='cleanup', default=True, action='store_false',
                        help='disable the removal of generated temporary files')
    parser.add_argument('--statistics', metavar='STATFILE', default=None,
                        help='gather statistics during reduction and export in JSON format')
    return parser


def config_logging(args):
    logging.basicConfig(format=args.log_format, datefmt=args.log_datefmt)
    inators.arg.process_log_level_argument(args, logger)


def process_args(args):
    args.input = realpath(args.input)
    if not exists(args.input):
        raise ValueError(f'Test case does not exist: {args.input}')

    with open(args.input, 'rb') as f:
        args.src = f.read()

    if args.encoding:
        try:
            codecs.lookup(args.encoding)
        except LookupError as e:
            raise ValueError(f'The given encoding ({args.encoding}) is not known.') from e
    else:
        args.encoding = chardet.detect(args.src)['encoding'] or 'latin-1'

    args.src = args.src.decode(args.encoding)

    args.out = realpath(args.out if args.out else f'{args.input}.{time.strftime("%Y%m%d_%H%M%S")}')

    args.test = realpath(args.test)
    if not exists(args.test) or not os.access(args.test, os.X_OK):
        raise ValueError(f'Tester program does not exist or isn\'t executable: {args.test}')

    args.tester_class = SubprocessTest
    args.tester_config = {'command_pattern': [args.test, '%s'],
                          'work_dir': join(args.out, 'tests'),
                          'filename': basename(args.input),
                          'encoding': args.encoding,
                          'cleanup': args.cleanup}

    args.cache_class = CacheRegistry.registry[args.cache]
    args.cache_config = {'cache_fail': args.cache_fail,
                         'evict_after_fail': args.evict_after_fail}

    if args.limit_time or args.limit_tests:
        stop = LimitReduction(deadline=timedelta(seconds=args.limit_time) if args.limit_time else None,
                              max_tests=args.limit_tests or None)
    else:
        stop = None

    # Choose the reducer class that will be used and its configuration.
    args.reduce_config = {'config_iterator': CombinedIterator(args.subset_first,
                                                              IteratorRegistry.registry[args.subset_iterator],
                                                              IteratorRegistry.registry[args.complement_iterator]),
                          'split': SplitterRegistry.registry[args.split](n=args.granularity),
                          'dd_star': args.dd_star,
                          'stop': stop}
    if not args.parallel:
        args.reduce_class = DD
    else:
        args.reduce_class = ParallelDD
        args.reduce_config.update(proc_num=args.jobs)

    logger.info('Input loaded from %s', args.input)


def log_args(title, args):
    def _log_args(args):
        if not args:
            return repr(args)
        if isinstance(args, dict):
            log = []
            for k, v in sorted(args.items()):
                k_log = _log_args(k)
                v_log = _log_args(v)
                if isinstance(v_log, list):
                    log += [f'{k_log}:']
                    for line in v_log:
                        log += [f'\t{line}']
                else:
                    log += [f'{k_log}: {v_log}']
            return log if len(log) > 1 else log[0]
        if isinstance(args, list):
            v_logs = [_log_args(v) for v in args]
            if any(isinstance(v_log, list) for v_log in v_logs):
                log = []
                for v_log in v_logs:
                    if not isinstance(v_log, list):
                        v_log = [v_log]
                    for i, line in enumerate(v_log):
                        log += [f'{"-" if i == 0 else " "} {line}']
            else:
                log = ', '.join(v_log for v_log in v_logs)
            return log
        if hasattr(args, '__name__'):
            return '.'.join(([args.__module__] if hasattr(args, '__module__') else []) + [args.__name__])
        return str(args)
    logger.info('%s\n\t%s\n', title, '\n\t'.join(_log_args(args)))


def reduce(src, *,
           reduce_class, reduce_config,
           tester_class, tester_config,
           atom='line',
           cache_class=None, cache_config=None,
           observer=None):
    """
    Execute picire as if invoked from command line, however, control its
    behaviour not via command line arguments but function parameters.

    :param src: Contents of the test case to reduce.
    :param reduce_class: Reference to the reducer class.
    :param reduce_config: Dictionary containing information to initialize the
        reduce_class.
    :param tester_class: Reference to a runnable class that can decide about the
        interestingness of a test case.
    :param tester_config: Dictionary containing information to initialize the
        tester_class.
    :param atom: Input granularity to work with during reduce ('char', 'line',
        or 'both'; default: 'line').
    :param cache_class: Reference to the cache class to use.
    :param cache_config: Dictionary containing information to initialize the
        cache_class.
    :param observer: Observer for events that will broadcast them for subscribed
        event handlers.
    :return: The contents of the minimal test case.
    :raises ReductionException: If reduction could not run until completion. The
        ``result`` attribute of the exception contains the contents of the
        smallest, potentially non-minimal, but failing test case found during
        reduction.
    """

    # Get the parameters in a dictionary so that they can be pretty-printed
    # (minus src, as that parameter can be arbitrarily large)
    args = locals().copy()
    del args['src']
    log_args('Reduce session starts', args)

    cache = cache_class(**cache_config) if cache_class else None

    for atom_cnt, atom_name in enumerate(['line', 'char'] if atom == 'both' else [atom]):
        # Split source to the chosen atoms.
        if atom_name == 'line':
            src = src.splitlines(True)
        logger.info('Initial test contains %d %ss', len(src), atom_name)

        test_builder = ConcatTestBuilder(src)
        if cache:
            cache.clear()
            cache.set_test_builder(test_builder)

        dd = reduce_class(tester_class(test_builder=test_builder, **tester_config),
                          cache=cache,
                          id_prefix=(f'a{atom_cnt}',),
                          observer=observer,
                          **reduce_config)
        try:
            min_set = dd(list(range(len(src))))
            src = test_builder(min_set)

            logger.trace('The cached results are: %s', cache)
            logger.debug('A minimal config is: %r', min_set)
        except ReductionException as e:
            logger.trace('The cached results are: %s', cache)
            logger.debug('The reduced config is: %r', e.result)
            logger.warning('Reduction stopped prematurely, the output may not be minimal: %s', e, exc_info=None if isinstance(e, ReductionStopped) else e)

            e.result = test_builder(e.result)
            raise

    return src


def postprocess(args, out_src, statistics):
    if args.cleanup:
        rmtree(join(args.out, 'tests'))

    output = join(args.out, basename(args.input))
    with codecs.open(output, 'w', encoding=args.encoding, errors='ignore') as f:
        f.write(out_src)

    if args.statistics:
        statistics['path_input'] = args.input
        statistics['path_output'] = output

        statistics['bytes_input'] = len(args.src)
        statistics['bytes_output'] = len(out_src)

        statistics['nws_input'] = sum(len(word) for line in args.src.splitlines() for word in line.split())
        statistics['nws_output'] = sum(len(word) for line in out_src.splitlines() for word in line.split())

        statistics['reducer'] = f'{__name__}-{__version__}'
        statistics['args'] = args.reduce_config

        for key in statistics['args']:
            item = statistics['args'][key]
            statistics['args'][key] = item.__name__ if hasattr(item, '__name__') else str(item)

        content = json.dumps(statistics, indent=4, sort_keys=True)
        with open(args.statistics, 'w') as f:
            f.write(content)

        logger.info(f'Statistics is saved to: {args.statistics}')

    logger.info('Output saved to %s', output)


def execute():
    """
    The main entry point of picire.
    """
    parser = create_parser()
    # Implementation specific CLI options that are not needed to be part of the core parser.
    parser.add_argument('-a', '--atom', metavar='NAME', choices=['char', 'line', 'both'], default='line',
                        help='atom (i.e., granularity) of input (%(choices)s; default: %(default)s)')
    inators.arg.add_version_argument(parser, version=__version__)
    args = parser.parse_args()

    config_logging(args)
    try:
        process_args(args)
    except ValueError as e:
        parser.error(e)

    observer = EventListener()
    observer.subscribe(Logger())

    stat_handler = Statistics()
    if args.statistics:
        observer.subscribe(stat_handler)

    try:
        out_src = reduce(args.src,
                         reduce_class=args.reduce_class,
                         reduce_config=args.reduce_config,
                         tester_class=args.tester_class,
                         tester_config=args.tester_config,
                         atom=args.atom,
                         cache_class=args.cache_class,
                         cache_config=args.cache_config,
                         observer=observer)
        postprocess(args, out_src, stat_handler.flush())
    except ReductionException as e:
        postprocess(args, e.result, stat_handler.flush())
        if not isinstance(e, ReductionStopped):
            sys.exit(1)
