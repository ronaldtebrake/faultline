"""Language-neutral source evidence from immutable Git objects; no application code."""
import fnmatch
import hashlib
import subprocess

from ..core import FaultlineError, digest


def match(path, pattern):
    # Match repository-relative globs: only ** crosses directory boundaries.
    def parts(names, patterns):
        if not patterns:
            return not names
        if patterns[0] == '**':
            return parts(names, patterns[1:]) or bool(names) and parts(names[1:], patterns)
        return bool(names) and fnmatch.fnmatchcase(names[0], patterns[0]) and parts(names[1:], patterns[1:])
    return parts(path.split('/'), pattern.removeprefix('./').split('/'))


class GitSources:
    def __init__(self, root, revision, max_bytes=1000000):
        self.root, self.revision, self.max_bytes = root, revision, max_bytes
        p = subprocess.run(['git', '-C', str(root), 'ls-tree', '-rlz', revision], capture_output=True)
        if p.returncode:
            raise FaultlineError('Cannot enumerate source at the requested revision')
        self.files, self.cache = {}, {}
        for entry in p.stdout.split(b'\0'):
            if not entry:
                continue
            meta, name = entry.split(b'\t', 1)
            mode, kind, oid, size = meta.split()
            if kind == b'blob':
                self.files[name.decode()] = {'mode': mode.decode(), 'oid': oid.decode(), 'size': int(size)}

    def glob(self, patterns):
        # A Git snapshot is immutable; shared setup patterns need one tree scan,
        # not another scan for every target in a large suite.
        if not hasattr(self, '_glob_cache'):
            self._glob_cache = {}
        key = tuple(patterns)
        if key not in self._glob_cache:
            self._glob_cache[key] = tuple(sorted(p for p in self.files if any(match(p, pattern) for pattern in patterns)))
        return list(self._glob_cache[key])

    def read(self, path):
        if path in self.cache:
            return self.cache[path]
        entry = self.files.get(path)
        if not entry or not entry['mode'].startswith('100'):
            raise FaultlineError('Source is missing or is not a regular tracked file')
        if entry['size'] > self.max_bytes:
            raise FaultlineError('Test source exceeds the configured max_test_bytes; target remains unscored')
        p = subprocess.run(['git', '-C', str(self.root), 'cat-file', 'blob', entry['oid']], capture_output=True)
        if p.returncode:
            raise FaultlineError('Cannot read source at the requested revision')
        self.cache[path] = p.stdout
        return p.stdout

    def hashes(self, paths):
        # Git object IDs bind exact bytes without reading all files into memory.
        return {p: self.files[p]['oid'] if p in self.files else None for p in sorted(set(paths))}


def text_parts(text, limit):
    """Bound every fragment, retain byte offsets and a digest of the complete text."""
    raw = text.encode('utf-8')
    if not raw:
        return [{'text': '', 'start_byte': 0, 'end_byte': 0, 'total_bytes': 0, 'sha256': hashlib.sha256(raw).hexdigest()}]
    result, offset = [], 0
    checksum = hashlib.sha256(raw).hexdigest()
    while offset < len(raw):
        end = min(offset + limit, len(raw))
        while end < len(raw) and raw[end] & 0xc0 == 0x80:
            end -= 1
        if end == offset:
            raise FaultlineError('Evidence fragment budget is too small for UTF-8 text')
        result.append({'text': raw[offset:end].decode('utf-8'), 'start_byte': offset,
                       'end_byte': end, 'total_bytes': len(raw), 'sha256': checksum})
        offset = end
    return result


def test_profile(source, unit, graph, suite, variant):
    raw = source.read(unit['source'])
    if b'\0' in raw:
        raise FaultlineError('Binary test source cannot be scored as text')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        raise FaultlineError('Test source is not UTF-8 text') from None
    if not text.strip():
        raise FaultlineError('Empty test source cannot establish protected behavior')
    paths = graph['paths'].get(unit['source'], [])
    # Retain useful symbols/edges, but keep large resolver payloads out of inference.
    graph_context = {'change_paths': [{'changed_source': p['changed_source'],
                     'edges': [{k: e.get(k) for k in ('caller', 'callee', 'caller_symbol', 'callee_symbol', 'kind')}
                               for e in p['edges'][:16]]} for p in paths[:3]],
                     'test_dependencies': [{k: e.get(k) for k in ('caller', 'callee', 'caller_symbol', 'callee_symbol', 'kind')}
                                           for e in graph['dependencies'].get(unit['source'], [])[:6]],
                     'limitations': graph['fallbacks'], 'structural_match': bool(paths)}
    context_paths = source.glob(suite['description_inputs'])
    context = source.hashes(context_paths)
    return {'id': unit['id'], 'source': unit['source'], 'description': '',
            'source_text': text, 'source_sha256': hashlib.sha256(raw).hexdigest(),
            'graph_evidence': graph_context,
            'execution_context': {'args': variant.get('args', []), 'command': suite['command'],
                                  'cwd': suite['cwd'], 'context_hash': digest(context)}}
