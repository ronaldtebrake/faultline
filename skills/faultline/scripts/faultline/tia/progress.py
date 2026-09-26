"""Portable per-run evidence. The optional cache never owns paid progress."""
import json
import os
from contextlib import contextmanager

from ..core import FaultlineError, digest, now
from ..network import Budget
from .common import seal


@contextmanager
def run_lock(folder):
    """OS releases the lock on interruption, including process termination."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a+b') as stream:
        try:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise FaultlineError('This assessment is already running; wait before resuming it') from None
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


class Progress:
    def __init__(self, folder, cache=None):
        self.path = folder / 'progress.jsonl'
        self.cache = cache
        self.answers, self.attempts, self.warnings = {}, [], []
        self.previous = None
        self.reused = set()
        self.resumed = set()
        self.initial = set()
        self.elapsed = []
        self.request_ceiling = None
        if self.path.exists():
            # A partial last write cannot have authorized a request: append must
            # return successfully before transport starts. Keep all complete records.
            with self.path.open('r+b') as stream:
                while True:
                    start = stream.tell()
                    line = stream.readline()
                    if not line:
                        break
                    if not line.endswith(b'\n'):
                        stream.truncate(start)
                        self.warnings.append('Interrupted final journal write removed')
                        break
                    try:
                        event = json.loads(line)
                        if event['previous'] != self.previous or event['integrity'] != digest({k: v for k, v in event.items() if k != 'integrity'}):
                            raise ValueError()
                        self.apply(event)
                    except (ValueError, KeyError, TypeError, IndexError):
                        raise FaultlineError('Run progress integrity mismatch; preserve it for inspection') from None
                    self.previous = event['integrity']
        self.initial = set(self.answers)

    def apply(self, event):
        kind, value = event['event'], event['value']
        if kind == 'attempt':
            self.attempts.append({'request_key': value, 'usage': None})
        elif kind == 'usage':
            self.attempts[value['attempt']]['usage'] = value['usage']
        elif kind in ('answer', 'reused_answer'):
            key = (value['request_key'], value['question_id'])
            self.answers[key] = value
            if kind == 'reused_answer':
                self.reused.add(key)
        elif kind == 'elapsed':
            self.elapsed.append(value)
        elif kind == 'ceiling':
            self.request_ceiling = value
        else:
            raise ValueError('Unknown event')

    def append(self, kind, value):
        event = seal({'event': kind, 'value': value, 'previous': self.previous, 'at': now()})
        raw = (json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()
        try:
            with self.path.open('ab') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise FaultlineError('Cannot persist run progress; no further paid requests are allowed') from None
        self.previous = event['integrity']
        self.apply(event)

    def peek(self, key, qid):
        if (key, qid) in self.answers:
            return self.answers[key, qid]
        if self.cache is not None:
            value = self.cache.get(key, qid)
            if value is not None:
                from ..jev import validate_answer
                if value.get('request_key') != key or value.get('question_id') != qid:
                    self.warnings.append('Optional cache identity mismatch; treating as a miss')
                    return None
                try:
                    validate_answer({'model': value['model'], 'answers': {'relevance': value['answer']}}, value['model'])
                except (FaultlineError, KeyError, TypeError):
                    self.warnings.append('Optional cache answer invalid; treating as a miss')
                    return None
                return value
        return None

    def get(self, key, qid):
        if (key, qid) in self.answers:
            if (key, qid) in self.initial:
                self.resumed.add((key, qid))
            return self.answers[key, qid]
        value = self.peek(key, qid)
        if value is not None:
            self.append('reused_answer', value)
        return value

    def put(self, value):
        key = (value['request_key'], value['question_id'])
        if key in self.answers:
            if self.answers[key]['answer'] != value['answer']:
                raise FaultlineError('Refusing to replace accepted run evidence')
            return
        self.append('answer', seal(value))
        if self.cache is not None:
            self.cache.put(value)


class RunBudget(Budget):
    def __init__(self, limit, progress):
        super().__init__(limit, len(progress.attempts))
        self.progress, self.request_key = progress, None

    def take(self):
        if self.used >= self.limit:
            raise FaultlineError(f'Run request ceiling reached ({self.limit}); resume does not reset spending')
        self.progress.append('attempt', self.request_key)
        self.used += 1

    def record_usage(self, value):
        if self.used:
            self.progress.append('usage', {'attempt': self.used - 1, 'usage': value})


class OptionalCache:
    """Exact-input reuse, best effort, bounded to 64 MiB; no SQLite requirement."""
    def __init__(self, store):
        self.warnings, self.cache = [], None
        try:
            from .cache import AnswerCache
            self.cache = AnswerCache(store, max_bytes=64 * 1024 * 1024)
        except ImportError:
            self.warnings.append('SQLite unavailable; optional answer cache disabled')

    def get(self, key, qid):
        try:
            return self.cache.get(key, qid) if self.cache else None
        except (FaultlineError, OSError):
            self.warnings.append('Optional cache unreadable; treating as a miss')
            return None

    def put(self, value):
        if self.cache:
            try:
                self.cache.put(value)
            except (FaultlineError, OSError):
                self.warnings.append('Optional cache write skipped; run evidence is retained')
