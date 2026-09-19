"""Runner inventories, exact selectors, and native result formats."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from ..core import FaultlineError, digest
from .common import glob_files, hashes
from .config import inside


def command(suite, variant):
    return [*suite['command'], *variant.get('args', [])]


def invoke(argv, cwd, timeout, *, capture=True, input=None):
    try:
        p = subprocess.run(argv, cwd=cwd, input=input, text=True,
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.PIPE if capture else None, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise FaultlineError('Runner command unavailable or timed out; execute the full suite') from None
    if capture and p.returncode:
        raise FaultlineError(f'Runner discovery failed with exit {p.returncode}; output was not copied into evidence')
    return p


def xml(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError()
        text = raw.decode('utf-8-sig')
        if '<!DOCTYPE' in text or '<!ENTITY' in text:
            raise ValueError()
        return ET.fromstring(text)
    except (OSError, ValueError, ET.ParseError):
        raise FaultlineError('Missing or invalid runner XML') from None


def source_path(root, suite, value):
    for prefix, replacement in sorted(suite['path_map'].items(), key=lambda item: -len(item[0])):
        if value == prefix.rstrip('/') or value.startswith(prefix.rstrip('/') + '/'):
            value = replacement.rstrip('/') + value[len(prefix.rstrip('/')):]
            return inside(root, value).relative_to(root).as_posix()
    path = Path(value)
    path = path if path.is_absolute() else root / suite['cwd'] / path
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        raise FaultlineError('Runner source outside repository; configure path_map') from None


def unit(root, suite, variant, source, members, locator, title):
    path = inside(root, source)
    if (Path(source).is_absolute() or '..' in Path(source).parts or not path.is_file()
            or not isinstance(members, list) or not members
            or not all(isinstance(m, str) and m for m in members) or len(members) != len(set(members))
            or not isinstance(locator, dict) or not isinstance(title, str)):
        raise FaultlineError('Missing source or ambiguous/empty test identities')
    fingerprint = hashes(root, [source, *glob_files(root, suite['description_inputs'])])
    return {'id': suite['id'] + ':' + variant['id'] + ':' + source,
            'source': source, 'members': sorted(members), 'locator': locator, 'title': title,
            'description_hash': digest({'sources': fingerprint}),
            'source_hashes': fingerprint}


def phpunit_inventory(root, suite, variant, output):
    invoke([*command(suite, variant), '--list-tests-xml', str(output)], root / suite['cwd'], suite['timeout_seconds'])
    tree = xml(output)
    if tree.tag != 'tests' or tree.findall('.//phptFile'):
        raise FaultlineError('Unsupported PHPUnit inventory; PHPT requires full execution')
    files = glob_files(root, suite['sources'])
    mapping = invoke(['php', str(Path(__file__).with_name('php_classes.php')), str(inside(root, str(Path(suite['cwd']) / suite['autoload'])))], root, suite['timeout_seconds'],
                     input=json.dumps([str(root / f) for f in files]))
    try:
        class_map = json.loads(mapping.stdout)
        if not isinstance(class_map, dict):
            raise ValueError()
    except ValueError:
        raise FaultlineError('Invalid PHP declaration map') from None
    grouped = {}
    for case in tree.findall('.//testCaseClass'):
        name = case.get('name')
        if name not in class_map:
            raise FaultlineError('Discovered PHPUnit class has no unique source; expand suite.sources')
        source = inside(root, class_map[name]).relative_to(root).as_posix()
        group = grouped.setdefault(source, {'members': [], 'classes': set()})
        group['classes'].add(name)
        for method in case.findall('testCaseMethod'):
            if not method.get('name'):
                raise FaultlineError('Unsupported PHPUnit method identity')
            member = name + '::' + method.get('name')
            if method.get('dataSet') is not None:
                member += ' with data set ' + method.get('dataSet')
            group['members'].append(member)
    units = []
    for source, data in grouped.items():
        item = unit(root, suite, variant, source, data['members'], {'classes': sorted(data['classes'])}, '\n'.join(data['members']))
        # Cross-test dependencies cannot be inferred safely from a name filter.
        text = (root / source).read_text(errors='replace')
        item['requires_full_suite'] = bool(re.search(r'@depends\b|\bDepends(?:External|OnClass|Using\w+)?\s*\(', text))
        units.append(item)
    return units


def behat_inventory(root, suite, variant, output):
    output.mkdir()
    invoke([*command(suite, variant), '--dry-run', '--no-interaction', '--format=junit', '--out=' + str(output)],
           root / suite['cwd'], suite['timeout_seconds'])
    files = sorted(output.glob('*.xml'))
    if not files:
        raise FaultlineError('Behat produced no discovery artifacts')
    units = []
    for path in files:
        tree = xml(path)
        features = [tree] if tree.tag == 'testsuite' else tree.findall('.//testsuite')
        for feature in features:
            if not feature.findall('testcase'):
                continue
            if not feature.get('file'):
                raise FaultlineError('Behat JUnit lacks feature file identity; use a generic inventory bridge or upgrade Behat')
            source = source_path(root, suite, feature.get('file'))
            # Native enumeration order disambiguates identical outline-row names within this source.
            members = [f'{i}:{t.get("name", "")}' for i, t in enumerate(feature.findall('testcase'))]
            units.append(unit(root, suite, variant, source, members, {'path': source}, feature.get('name', source)))
    return units


def generic_inventory(root, suite, variant, output):
    argv = expand(suite['discovery_command'], variant=variant, output=output)
    p = invoke(argv, root / suite['cwd'], suite['timeout_seconds'])
    try:
        data = json.loads(output.read_text() if output.exists() else p.stdout)
        if not isinstance(data, dict) or data.get('schema_version') != 2 or data.get('complete') is not True:
            raise ValueError()
        return [unit(root, suite, variant, u['source'], u['members'], u['locator'], u.get('title', u['source'])) for u in data['units']]
    except (OSError, KeyError, ValueError, TypeError):
        raise FaultlineError('Invalid/incomplete generic discovery contract') from None


def expand(argv, *, variant, output=None, selectors=None, selection=None):
    result = []
    for arg in argv:
        if arg == '{variant_args}':
            result.extend(variant.get('args', []))
        elif arg == '{selectors}':
            result.extend(selectors or [])
        else:
            result.append(arg.replace('{output}', str(output or '')).replace('{selection}', str(selection or '')).replace('{variant}', variant['id']))
    return result


def discover_suite(root, suite, variant):
    result = {'key': suite['id'] + ':' + variant['id'], 'suite': suite['id'], 'variant': variant['id'],
              'runner': suite['runner'], 'complete': False, 'units': [], 'errors': []}
    try:
        if not suite['command']:
            raise FaultlineError('No native command configured; source analysis remains available')
        cwd = inside(root, suite['cwd'])
        if not cwd.is_dir():
            raise FaultlineError('Suite working directory missing')
        if suite['runner'] == 'generic' and 'discovery_command' not in suite:
            raise FaultlineError('No native discovery configured; execute the full suite')
        if 'discovery_command' in suite:
            version = 'generic-contract-v2'
            discoverer = generic_inventory
        else:
            if suite['runner'] not in ('phpunit', 'behat'):
                raise FaultlineError('Native discovery unavailable; source analysis remains available')
            version = invoke([*suite['command'], '--version'], cwd, suite['timeout_seconds']).stdout.strip()
            supported = {'phpunit': r'PHPUnit 9\.6\.', 'behat': r'behat 3\.29\.'}
            if suite['runner'] not in supported or not re.search(supported[suite['runner']], version, re.I):
                raise FaultlineError('Unsupported runner version; use full execution')
            discoverer = {'phpunit': phpunit_inventory, 'behat': behat_inventory}[suite['runner']]
        with tempfile.TemporaryDirectory(prefix='faultline-discover-', dir=cwd) as temp:
            units = discoverer(root, suite, variant, Path(temp) / 'inventory')
        if not units:
            raise FaultlineError('Empty inventory does not establish discovery completeness; execute the full suite')
        ids = [u['id'] for u in units]
        if len(ids) != len(set(ids)):
            raise FaultlineError('Duplicate execution units in discovery')
        result.update(complete=True, units=sorted(units, key=lambda u: u['id']), runner_version=version)
    except (FaultlineError, OSError) as exc:
        result['errors'] = [str(exc)]
    return result

