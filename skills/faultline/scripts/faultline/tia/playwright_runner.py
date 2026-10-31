"""Playwright's native inventory and whole-file selection with project setup.

A temporary config beside the original preserves relative paths and reporters.
Playwright performs exclusions before its ordinary execution pipeline. Both the
selected discovery and actual run must report the same native test identities.
"""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import tempfile

from ..core import FaultlineError, digest
from .config import inside
from .runners import command, invoke, source_path, unit
from .common import revision
from .evidence import GitSources
from .playwright_sources import validate as validate_generation

CONFIGS = ['playwright.config.' + extension for extension in ('ts', 'js', 'mts', 'mjs', 'cts', 'cjs')]
SUPPORTED_VERSION = r'1\.(?:63|64)\.\d+'


@contextmanager
def configuration(root, suite, variant, output, files=None):
    argv = command(suite, variant)
    if suite['path_map'] or any(arg.split('=', 1)[0] in ('--reporter', '--ui', '--debug', '--last-failed', '--only-changed', '--list', '--no-deps', '--test-list', '--test-list-invert') for arg in argv):
        raise FaultlineError('Playwright selection needs a local config without CLI reporter overrides, interactive mode or state-dependent filters')
    configured, position, width = None, None, 0
    for index, arg in enumerate(argv):
        if arg in ('-c', '--config'):
            if configured is not None or index + 1 >= len(argv):
                raise FaultlineError('Ambiguous Playwright config')
            configured, position, width = argv[index + 1], index, 2
        elif arg.startswith('--config='):
            if configured is not None:
                raise FaultlineError('Ambiguous Playwright config')
            configured, position, width = arg.split('=', 1)[1], index, 1
        elif arg.startswith('-c') and not arg.startswith('--'):
            raise FaultlineError('Use a separate -c argument for Playwright selection')
    cwd = inside(root, suite['cwd'])
    location = inside(root, str(Path(suite['cwd']) / configured)) if configured else cwd
    if location.is_dir():
        candidates = [location / name for name in CONFIGS if (location / name).is_file()]
        if len(candidates) > 1:
            raise FaultlineError('Multiple Playwright configurations; choose one with --config')
        config = candidates[0] if candidates else None
        directory = location
    else:
        config, directory = location, location.parent
        if not config.is_file():
            raise FaultlineError('Playwright config is unavailable')
    fd, temporary = tempfile.mkstemp(prefix='.faultline-playwright-', suffix='.config.mts', dir=directory)
    try:
        options = {'output': str(output), 'files': None if files is None else [str(root / file) for file in files],
                   'root': str(root.resolve()), 'revision': revision(root)}
        reporter = str(Path(__file__).with_name('playwright_reporter.mjs').resolve())
        with os.fdopen(fd, 'w') as stream:
            stream.write(('import imported from ' + json.dumps(config.as_uri()) + ';\nconst original = imported?.__esModule ? imported.default : imported;\n')
                         if config else 'const original = {};\n')
            stream.write('const reporters = original.reporter ?? [[process.env.CI ? "dot" : "list"]];\n')
            stream.write('export default {...original, reporter: [...(typeof reporters === "string" ? [[reporters]] : reporters), [' +
                         json.dumps(reporter) + ', ' + json.dumps(options) + ']]};\n')
        if position is None:
            argv += ['--config', temporary]
        else:
            argv[position:position + width] = ['--config', temporary]
        yield argv
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_report(path, *, discovery=False):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError()
        value = json.loads(raw)
        if (value.get('version') != 2 or value.get('complete') is not True or
                value.get('selectionApplied') is not True or value.get('errors') != 0 or
                not re.fullmatch(SUPPORTED_VERSION, value.get('runnerVersion', '')) or
                not isinstance(value.get('tests'), list)):
            raise ValueError()
        identities = set()
        for test in value['tests']:
            if (not all(isinstance(test.get(key), str) and test[key] for key in ('id', 'file', 'nativeFile', 'title')) or
                    test['id'] in identities or not isinstance(test.get('project'), str) or
                    not isinstance(test.get('nativeSha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', test['nativeSha256']) or
                    type(test.get('support')) is not bool or
                    (test.get('generation') is not None and not isinstance(test['generation'], dict)) or
                    test.get('outcome') not in ('expected', 'unexpected', 'flaky', 'skipped') or
                    test.get('expectedStatus') not in ('passed', 'failed', 'timedOut', 'skipped', 'interrupted') or
                    not isinstance(test.get('attempts'), list)):
                raise ValueError()
            identities.add(test['id'])
            retries = set()
            for attempt in test['attempts']:
                if (type(attempt.get('retry')) is not int or attempt['retry'] < 0 or attempt['retry'] in retries or
                        attempt.get('status') not in ('passed', 'failed', 'timedOut', 'skipped', 'interrupted') or
                        type(attempt.get('duration')) not in (int, float) or not math.isfinite(attempt['duration']) or attempt['duration'] < 0):
                    raise ValueError()
                retries.add(attempt['retry'])
            if not discovery and not test['attempts']:
                raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise FaultlineError('Missing, incomplete or unsupported native Playwright report') from None


def case_proof(root, suite, test, snapshot):
    source = source_path(root, suite, test['file'])
    native = source_path(root, suite, test['nativeFile'])
    generation = test.get('generation')
    if generation is not None:
        validate_generation(generation, snapshot, source)
    elif source != native:
        raise FaultlineError('Playwright source mapping lacks generation evidence')
    return source, {'file': native, 'sha256': test['nativeSha256'], 'generation': generation, 'support': test['support']}


def inventory(root, suite, variant, output, files=None):
    with configuration(root, suite, variant, output, files) as argv:
        invoke([*argv, '--list'], root / suite['cwd'], suite['timeout_seconds'])
    value = read_report(output, discovery=True)
    grouped = {}
    snapshot = GitSources(root, revision(root))
    for test in value['tests']:
        source, proof = case_proof(root, suite, test, snapshot)
        group = grouped.setdefault(source, {'members': [], 'titles': [], 'cases': {}})
        group['members'].append(test['id'])
        group['titles'].append(test['title'])
        group['cases'][test['id']] = proof
    return [{**unit(root, suite, variant, source, row['members'], {'path': source, 'native_cases': row['cases']}, '\n'.join(row['titles'])),
             'native_support': all(case['support'] for case in row['cases'].values())}
            for source, row in sorted(grouped.items())]


def results(path, expected, root, suite):
    value = read_report(path)
    by_source = {u['source']: u for u in expected}
    observed, unmatched = [], []
    snapshot = GitSources(root, revision(root))
    for test in value['tests']:
        source, proof = case_proof(root, suite, test, snapshot)
        target = by_source.get(source)
        if target is None or test['id'] not in target['members']:
            unmatched.append({'reason': 'Unknown native Playwright case', 'source': source})
            continue
        if target.get('locator', {}).get('native_cases', {}).get(test['id']) != proof:
            unmatched.append({'reason': 'Native Playwright source or generation changed after discovery', 'source': source})
            continue
        observed.append({'id': target['id'], 'member': test['id'],
                         'status': {'expected': 'passed', 'unexpected': 'failed', 'flaky': 'passed', 'skipped': 'skipped'}[test['outcome']],
                         'duration_seconds': sum(a['duration'] for a in test['attempts']) / 1000,
                         'native_outcome': test['outcome'], 'attempts': test['attempts'],
                         'native_source_fingerprint': digest(proof)})
    expected_ids = {(u['id'], member) for u in expected for member in u['members']}
    if expected_ids != {(row['id'], row['member']) for row in observed}:
        unmatched.append({'reason': 'Expected native Playwright cases missing from results'})
    if not observed:
        unmatched.append({'reason': 'No matched native Playwright cases in results'})
    return observed, unmatched
