"""Committed suite configuration. Commands are argv arrays, never shell strings."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from ..core import DEFAULTS, FaultlineError, digest, number, read_json

SCHEMA = 2
DEFAULT_EVALUATOR = {**DEFAULTS, 'max_batch_units': 50, 'max_batch_bytes': 24000,
                     'selection_seconds': 60, 'pricing': None}


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, p) or (p.endswith('/**') and path == p[:-3]) for p in patterns)


def strings(value, label):
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise FaultlineError(f'{label} must be an array of nonempty strings')
    return value


def inside(root, path):
    if not isinstance(path, str) or not path or '\0' in path:
        raise FaultlineError('Configured paths must be nonempty strings')
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise FaultlineError('Configured path escapes the repository')
    return candidate


def load_config(root):
    raw = read_json(root / 'faultline.json')
    if not isinstance(raw, dict) or raw.get('schema_version') != SCHEMA:
        raise FaultlineError('Create faultline.json with schema_version: 2; see docs/tia.md')
    if set(raw) - {'schema_version', 'repository', 'suites', 'evaluator', 'scope', 'state_max_age_seconds', 'graph'}:
        raise FaultlineError('Unknown faultline.json configuration field')
    if not isinstance(raw.get('suites'), list) or not raw['suites']:
        raise FaultlineError('Configure at least one suite')
    if not isinstance(raw.get('evaluator', {}), dict):
        raise FaultlineError('evaluator must be an object')
    if not isinstance(raw.get('repository', root.name), str) or not raw.get('repository', root.name):
        raise FaultlineError('repository must be nonempty text')
    from .graph import DEFAULTS as GRAPH_DEFAULTS, VERSION as GRAPH_VERSION
    graph = {**GRAPH_DEFAULTS, **raw.get('graph', {})} if isinstance(raw.get('graph', {}), dict) else {}
    if not graph or set(graph) - set(GRAPH_DEFAULTS) or graph['version'] != GRAPH_VERSION:
        raise FaultlineError('Use the supported pinned CodeGraph version and documented graph settings')
    if not strings(graph['command'], 'graph.command'):
        raise FaultlineError('graph.command cannot be empty')
    for key in set(GRAPH_DEFAULTS) - {'command', 'version', 'extensions'}:
        if not isinstance(graph[key], int) or isinstance(graph[key], bool) or graph[key] <= 0:
            raise FaultlineError('Graph budgets must be positive integers')
    if not isinstance(graph['extensions'], dict) or not all(isinstance(k, str) and k.startswith('.') and isinstance(v, str) and v for k, v in graph['extensions'].items()):
        raise FaultlineError('graph.extensions must map file extensions to CodeGraph language IDs')
    config = {'graph': graph, 'schema_version': SCHEMA, 'repository': raw.get('repository', root.name),
              'scope': strings(raw.get('scope', []), 'scope'), 'suites': [],
              'state_max_age_seconds': raw.get('state_max_age_seconds', 86400),
              'evaluator': {**DEFAULT_EVALUATOR, **raw.get('evaluator', {})}}
    number(config['state_max_age_seconds'], 'state_max_age_seconds')
    ev = config['evaluator']
    if set(ev) - set(DEFAULT_EVALUATOR):
        raise FaultlineError('Unknown evaluator configuration field')
    if not isinstance(ev['model'], str) or not re.fullmatch(r'jev-\d+\.\d+\.\d+', ev['model']):
        raise FaultlineError('Use a pinned Jev model version')
    for key in set(DEFAULT_EVALUATOR) - {'model', 'pricing'}:
        number(ev[key], key, allow_zero=key in ('jev_requests', 'retries', 'max_wait', 'request_interval'))
        if key not in ('request_interval', 'selection_seconds') and not isinstance(ev[key], int):
            raise FaultlineError(f'{key} must be an integer')
    if ev['pricing'] is not None:
        price = ev['pricing']
        if not isinstance(price, dict) or not isinstance(price.get('as_of'), str):
            raise FaultlineError('pricing requires as_of and input_usd_per_million')
        number(price.get('input_usd_per_million'), 'input_usd_per_million', allow_zero=True)
    seen = set()
    allowed = {'id', 'runner', 'command', 'cwd', 'sources', 'scope', 'shared_inputs',
               'description_inputs', 'must_run', 'prerequisites', 'variants', 'mode',
               'irrelevant_threshold', 'discovery_command', 'selection_command', 'timeout_seconds',
               'relationships', 'path_map', 'result_format', 'autoload'}
    for value in raw['suites']:
        if not isinstance(value, dict) or set(value) - allowed:
            raise FaultlineError('Unknown or malformed suite configuration')
        suite = {'cwd': '.', 'sources': [], 'scope': [], 'shared_inputs': [], 'description_inputs': [],
                 'must_run': [], 'prerequisites': [], 'mode': 'shadow', 'irrelevant_threshold': .95,
                 'timeout_seconds': 600, 'variants': [{'id': 'default', 'args': []}],
                 'relationships': [], 'path_map': {}, 'autoload': 'vendor/autoload.php', **value}
        if not isinstance(suite.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', suite['id']) or suite['id'] in seen:
            raise FaultlineError('Suite IDs must be unique letters/digits/underscore/hyphen')
        seen.add(suite['id'])
        if suite.get('runner') not in ('phpunit', 'behat', 'playwright', 'generic'):
            raise FaultlineError('runner must be phpunit, behat, playwright, or generic')
        if not strings(suite.get('command'), 'command'):
            raise FaultlineError('command cannot be empty')
        inside(root, suite['cwd'])
        inside(root, str(Path(suite['cwd']) / suite['autoload']) if isinstance(suite['autoload'], str) else None)
        for key in ('sources', 'scope', 'shared_inputs', 'description_inputs', 'must_run', 'prerequisites', 'relationships'):
            strings(suite[key], key)
            if key in ('sources', 'scope', 'shared_inputs', 'description_inputs'):
                for pattern in suite[key]:
                    if Path(pattern).is_absolute() or '..' in Path(pattern).parts:
                        raise FaultlineError('Source and scope patterns must be repository-relative')
        for key in ('discovery_command', 'selection_command'):
            if key in suite:
                if not strings(suite[key], key):
                    raise FaultlineError(key + ' cannot be empty')
        if suite['runner'] == 'generic' and 'discovery_command' not in suite:
            raise FaultlineError('Generic runners require discovery_command')
        if suite['mode'] not in ('shadow', 'experimental'):
            raise FaultlineError('mode must be shadow or experimental')
        number(suite['timeout_seconds'], 'timeout_seconds')
        if not .95 <= number(suite['irrelevant_threshold'], 'irrelevant_threshold') <= 1:
            raise FaultlineError('irrelevant_threshold must be between 0.95 and 1')
        if not isinstance(suite['variants'], list) or not suite['variants']:
            raise FaultlineError('variants must be nonempty')
        variants = set()
        for variant in suite['variants']:
            if not isinstance(variant, dict) or set(variant) - {'id', 'args'} or not isinstance(variant.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', variant['id']) or variant['id'] in variants:
                raise FaultlineError('Variant IDs must be unique and valid')
            strings(variant.get('args', []), 'variant.args')
            variants.add(variant['id'])
        if not isinstance(suite['path_map'], dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in suite['path_map'].items()):
            raise FaultlineError('path_map must map runner prefixes to repository paths')
        config['suites'].append(suite)
    for suite in config['suites']:
        if set(suite['prerequisites']) - seen:
            raise FaultlineError('Unknown prerequisite suite')
    def visit(name, parents):
        if name in parents:
            raise FaultlineError('Suite prerequisites contain a cycle')
        for item in next(s for s in config['suites'] if s['id'] == name)['prerequisites']:
            visit(item, parents | {name})
    for name in seen:
        visit(name, set())
    config['config_hash'] = digest(config)
    return config


def variants(config):
    for suite in config['suites']:
        for variant in suite['variants']:
            yield suite, variant, suite['id'] + ':' + variant['id']
