"""Source-only dependency facts. These are positive evidence, never completeness claims.

No imported module, PHP context, browser, or application is executed. Facts are
cached by exact blob identity; resolution is repeated against each Git tree so a
new file or definition can create an edge even when its consumer did not change.
"""
import posixpath
import re
import subprocess
import json
from pathlib import Path

from ..core import FaultlineError

VERSION = 'dependency-source-v2'
JS_EXTENSIONS = ('.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.mts', '.cts')
PHP_BATCH_FILES = 64
PHP_BATCH_BYTES = 4 * 1024 * 1024


def language(path):
    if path.endswith('.feature'):
        return 'gherkin'
    if path.endswith('.php'):
        return 'php'
    if path.endswith(JS_EXTENSIONS):
        return 'javascript'
    return 'data'


def javascript(text):
    # Preserve strings and newlines while removing comments. Unsupported syntax
    # stays an explicit gap; a lexical edge is not a proof of complete imports.
    tokens = re.compile(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`)|//[^\n]*|/\*[\s\S]*?\*/')
    clean = tokens.sub(lambda m: m[1] if m[1] is not None else '\n' * m[0].count('\n'), text)
    imports = set()
    patterns = [r'\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?[\'\"]([^\'\"]+)[\'\"]',
                r'\b(?:require|import)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]\s*\)']
    for pattern in patterns:
        imports.update(re.findall(pattern, clean))
    gaps = ['source_imports_do_not_describe_browser_or_server_dependencies']
    if re.search(r'\b(?:import|require)\s*\(\s*[^\s\'\"]', clean):
        gaps.append('dynamic_module_reference')
    return {'imports': sorted(imports), 'gaps': gaps}


def gherkin(text):
    steps, gaps = [], []
    lang = re.search(r'^\s*#\s*language:\s*(\S+)', text, re.M)
    if lang and lang[1] != 'en':
        gaps.append('unsupported_gherkin_language:' + lang[1])
    in_docstring = None
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith(('"""', '```')):
            delimiter = stripped[:3]
            in_docstring = None if in_docstring == delimiter else delimiter
            continue
        if in_docstring:
            continue
        match = re.match(r'^\s*(?:Given|When|Then|And|But|\*)\s+(.+?)\s*$', line)
        if match:
            steps.append({'text': match[1], 'line': number})
            if re.search(r'<[^>]+>', match[1]):
                gaps.append('scenario_outline_requires_native_expansion')
    if not steps:
        gaps.append('no_recognized_steps')
    return {'steps': steps, 'gaps': sorted(set(gaps))}


def php_batch(texts):
    """PHP's own tokenizer reads text as data, without eval/include/autoload."""
    try:
        result = subprocess.run(['php', '-n', str(Path(__file__).with_name('dependency_php.php')), '--batch'],
                                input=json.dumps(texts), text=True, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return [{'classes': [], 'references': [], 'definitions': [], 'gaps': ['php_tokenizer_unavailable']} for _ in texts]
    if result.returncode == 78:
        return [{'classes': [], 'references': [], 'definitions': [], 'gaps': ['php_tokenizer_unavailable']} for _ in texts]
    if result.returncode:
        return [{'classes': [], 'references': [], 'definitions': [], 'gaps': ['php_tokenization_failed']} for _ in texts]
    try:
        value = json.loads(result.stdout)
        if (not isinstance(value, list) or len(value) != len(texts) or
                any(not isinstance(row, dict) or set(row) != {'classes', 'references', 'definitions', 'declaration_hash', 'gaps'} for row in value)):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise FaultlineError('Invalid bundled PHP dependency tokenizer output') from None


def php(text):
    return php_batch([text])[0]


def parse_many(entries):
    """Amortize interpreter startup while keeping each source's state isolated."""
    pending, size = [], 0

    def flush():
        try:
            rows = php_batch([text for _, text in pending])
        except FaultlineError:
            rows = [{'gaps': ['php_tokenization_failed']} for _ in pending]
        return [(path, {'language': 'php', **row}) for (path, _), row in zip(pending, rows)]

    for path, raw in entries:
        text = None
        if language(path) == 'php' and b'\0' not in raw:
            try:
                text = raw.decode('utf-8')
            except UnicodeError:
                pass
        if text is None:
            yield path, parse(path, raw)
            continue
        # Count serialized bytes, including escaping, rather than code points.
        encoded_size = len(json.dumps(text).encode()) + 1
        if pending and (len(pending) >= PHP_BATCH_FILES or size + encoded_size > PHP_BATCH_BYTES):
            yield from flush()
            pending, size = [], 0
        pending.append((path, text))
        size += encoded_size
    if pending:
        yield from flush()


def parse(path, raw):
    if b'\0' in raw:
        return {'language': language(path), 'gaps': ['binary_source']}
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        return {'language': language(path), 'gaps': ['non_utf8_source']}
    kind = language(path)
    facts = {'javascript': javascript, 'gherkin': gherkin, 'php': php}.get(kind, lambda _: {'gaps': []})(text)
    return {'language': kind, **facts}


def resolve_import(path, specifier, files):
    if not specifier.startswith('.'):
        return [], 'package_or_alias_import:' + specifier
    target = posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier))
    if target == '..' or target.startswith('../'):
        return [], 'import_outside_repository:' + specifier
    candidates = [target, *(target + ext for ext in JS_EXTENSIONS),
                  *(target + '/index' + ext for ext in JS_EXTENSIONS)]
    # TypeScript commonly imports a .js path that resolves to .ts source.
    if target.endswith(('.js', '.mjs', '.cjs')):
        candidates.extend(target.rsplit('.', 1)[0] + ext for ext in ('.ts', '.tsx', '.mts', '.cts'))
    found = sorted(set(candidates) & files)
    return found, ('ambiguous_import:' if len(found) > 1 else 'unresolved_import:') + specifier if len(found) != 1 else None


def match_steps(steps, definitions):
    """Use PCRE for PCRE patterns; do not reinterpret them as Python regexes."""
    if not steps or not definitions:
        return [[] for _ in steps]
    payload = {'steps': steps, 'patterns': [d['pattern'] for d in definitions]}
    try:
        result = subprocess.run(['php', '-n', str(Path(__file__).with_name('dependency_php.php')), '--match'],
                                input=json.dumps(payload), text=True, capture_output=True, timeout=15)
        if result.returncode:
            raise ValueError()
        matches = json.loads(result.stdout)
        if not isinstance(matches, list) or len(matches) != len(steps):
            raise ValueError()
        return matches
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return [None for _ in steps]
