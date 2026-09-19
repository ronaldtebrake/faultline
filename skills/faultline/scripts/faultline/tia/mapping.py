"""Import test-attributed evidence produced by existing coverage tooling.

No instrumentation or static dependency inference lives here. Coverage absence
is never an exclusion signal, and native reports are parsed as data, not PHP.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

from ..core import FaultlineError, now
from .common import seal
from .runners import xml

NS = {'c': 'https://schema.phpunit.de/coverage/1.0'}


def safe_relative(value):
    if not isinstance(value, str) or not value or '\0' in value or ':' in value:
        raise FaultlineError('Coverage paths must be nonempty relative paths')
    path = PurePosixPath(value.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts:
        raise FaultlineError('Coverage report contains an unsafe relative path')
    return str(path)


def phpunit_xml(directory, *, source_prefix, revision, suite, variant='default'):
    if not all(isinstance(v, str) and v.strip() for v in (revision, suite, variant)):
        raise FaultlineError('Mapping requires revision, suite, and variant identities')
    directory = Path(directory).resolve()
    prefix = safe_relative(source_prefix)
    index = xml(directory / 'index.xml')
    project = index.find('c:project', NS)
    if project is None:
        raise FaultlineError('Expected PHPUnit XML coverage, not JUnit/Clover summary XML')
    tests = [t.get('name') for t in project.findall('c:tests/c:test', NS)]
    declared = set(tests)
    if any(not t for t in tests) or len(declared) != len(tests):
        raise FaultlineError('Coverage test identity is missing or duplicated')
    evidence = {'index.xml': hashlib.sha256((directory / 'index.xml').read_bytes()).hexdigest()}
    edges = {}
    files = []
    for entry in project.findall('.//c:file', NS):
        href = safe_relative(entry.get('href', ''))
        file_path = (directory / href).resolve()
        if not file_path.is_relative_to(directory) or not file_path.is_file():
            raise FaultlineError('Coverage file reference is missing or escapes the report')
        evidence[href] = hashlib.sha256(file_path.read_bytes()).hexdigest()
        report = xml(file_path)
        node = report.find('c:file', NS)
        if node is None or not node.get('name'):
            raise FaultlineError('Coverage file has no source identity')
        # Native XML uses / for paths relative to the report's source root.
        relative = safe_relative(str(PurePosixPath(node.get('path', '/').lstrip('/')) / node.get('name')))
        source = str(PurePosixPath(prefix) / relative)
        files.append(source)
        for line in node.findall('c:coverage/c:line', NS):
            try:
                number = int(line.get('nr', ''))
                if number < 1:
                    raise ValueError()
            except ValueError:
                raise FaultlineError('Invalid native coverage line number') from None
            for covered in line.findall('c:covered', NS):
                test = covered.get('by')
                if test not in declared:
                    raise FaultlineError('Coverage references an undeclared test identity')
                edges.setdefault((test, source), set()).add(number)
    build = index.find('c:build', NS)
    return seal({'schema_version': 2, 'kind': 'relationships', 'producer': 'phpunit-xml',
                 'producer_version': build.get('coverage') if build is not None else None,
                 'created_at': now(), 'revision': revision, 'suite': suite, 'variant': variant,
                 'source_prefix': prefix, 'report_hashes': evidence, 'files': sorted(set(files)),
                 'tests': sorted(declared),
                 'edges': [{'test': test, 'source': source, 'lines': sorted(lines)}
                           for (test, source), lines in sorted(edges.items())],
                 'limitations': ['Observed execution only; absence is not proof of no impact.',
                                 'Revision and path prefix are supplied by the importing workflow.']})


def covered_units(mapping, units, changed_files):
    """Exact native test identities only; ambiguous/unmapped evidence stays visible."""
    identities = {}
    for unit in units:
        for member in unit['members']:
            identities.setdefault(member, set()).add(unit['id'])
    required, unmatched = set(), set()
    for edge in mapping['edges']:
        if edge['source'] not in changed_files:
            continue
        targets = identities.get(edge['test'], set())
        if not targets:
            unmatched.add(edge['test'])
        required.update(targets)
    return {'required': sorted(required), 'unmatched': sorted(unmatched)}
