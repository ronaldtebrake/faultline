"""Validated Jev answers in one SQLite file; inference inputs remain hash-addressed."""
import json
import re
import sqlite3
from contextlib import closing

from ..core import FaultlineError, digest
from .common import checked, seal


class AnswerCache:
    def __init__(self, store):
        self.path = store.path / 'jev-cache.sqlite'
        self.legacy = store.path / 'batch-cache'

    def get(self, key, qid):
        if self.path.exists():
            try:
                with closing(sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)) as db:
                    row = db.execute('SELECT value FROM answers WHERE request_key=? AND question_id=?', (key, qid)).fetchone()
                if row:
                    value = json.loads(row[0])
                    if value.get('integrity') != digest({k: v for k, v in value.items() if k != 'integrity'}):
                        raise FaultlineError('Jev cache integrity mismatch')
                    if value.get('request_key') != key or value.get('question_id') != qid:
                        raise FaultlineError('Jev cache input identity mismatch')
                    return value
            except (sqlite3.Error, ValueError, TypeError, AttributeError):
                raise FaultlineError('Cannot read Jev cache; preserve it for inspection or restore a trusted copy') from None
        old = self.legacy / key / (qid + '.json')
        return checked(old, 'jev-answer') if old.exists() else None

    def put(self, value):
        value = seal(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('CREATE TABLE IF NOT EXISTS answers(request_key TEXT, question_id TEXT, value TEXT NOT NULL, PRIMARY KEY(request_key,question_id))')
                row = db.execute('SELECT value FROM answers WHERE request_key=? AND question_id=?',
                                 (value['request_key'], value['question_id'])).fetchone()
                if row:
                    existing = json.loads(row[0])
                    if existing.get('integrity') != digest({k:v for k,v in existing.items() if k != 'integrity'}):
                        raise FaultlineError('Jev cache integrity mismatch')
                    if {k:v for k,v in existing.items() if k not in ('integrity', 'created_at')} != {k:v for k,v in value.items() if k not in ('integrity', 'created_at')}:
                        raise FaultlineError('Refusing to replace a cached Jev judgment')
                else:
                    db.execute('INSERT INTO answers VALUES(?,?,?)', (value['request_key'], value['question_id'], json.dumps(value, separators=(',', ':'))))
        except (sqlite3.Error, ValueError):
            raise FaultlineError('Cannot persist Jev cache; completed analysis must remain incomplete') from None

    def compact(self):
        """Explicitly migrate recognized JSON answers; remove only verified copies."""
        from ..jev import validate_answer
        imported = removed = skipped = 0
        if not self.legacy.exists():
            return {'imported_answers': 0, 'removed_files': 0, 'skipped_batches': 0, 'database': str(self.path)}
        for folder in sorted(self.legacy.iterdir()):
            if folder.is_symlink() or not folder.is_dir() or not re.fullmatch(r'[0-9a-f]{64}', folder.name):
                skipped += 1
                continue
            try:
                files = sorted(folder.iterdir())
                if any(p.is_symlink() or not p.is_file() or not (p.name == 'request.json' or re.fullmatch(r'q\d+\.json', p.name)) for p in files):
                    raise FaultlineError('Unrecognized legacy cache contents')
                values = []
                for path in files:
                    value = checked(path, 'jev-request' if path.name == 'request.json' else 'jev-answer')
                    if value.get('request_key') != folder.name:
                        raise FaultlineError('Legacy cache identity mismatch')
                    if path.name != 'request.json':
                        if value.get('question_id') != path.stem:
                            raise FaultlineError('Legacy question identity mismatch')
                        validate_answer({'model': value['model'], 'answers': {'relevance': value['answer']}}, value['model'])
                        values.append(value)
                for value in values:
                    self.put(value)
                    # Verify the durable database row before removing its source.
                    saved = self.get(value['request_key'], value['question_id'])
                    if saved['answer'] != value['answer'] or saved['model'] != value['model']:
                        raise FaultlineError('Migrated cache verification failed')
                imported += len(values)
                for path in files:
                    path.unlink()
                    removed += 1
                folder.rmdir()
            except (FaultlineError, OSError, KeyError, TypeError):
                skipped += 1
        try:
            self.legacy.rmdir()
        except OSError:
            pass
        return {'imported_answers': imported, 'removed_files': removed, 'skipped_batches': skipped,
                'database': str(self.path), 'complete': skipped == 0}
