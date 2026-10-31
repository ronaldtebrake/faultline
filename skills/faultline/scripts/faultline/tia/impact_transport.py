"""Four persistent HTTPS connections with one durable budget and cooldown."""
import concurrent.futures
import http.client
import json
import math
import threading
import time
from email.utils import parsedate_to_datetime
from datetime import datetime

from ..core import FaultlineError, digest
from ..network import tls_context

MODEL = 'jev-1.13.0'
PRICE = .042
PRICE_DATE = '2026-10-01'
RESERVE = 65536


def usage(progress):
    known = unknown = 0
    for attempt in progress.attempts:
        value = (attempt.get('usage') or {}).get('input_tokens')
        if type(value) is int and 0 < value <= RESERVE:
            known += value
        else:
            unknown += 1
    return {'requests': len(progress.attempts), 'input_tokens': known,
            'unknown_attempts': unknown, 'known_usd': known * PRICE / 1e6,
            'upper_usd': (known + unknown * RESERVE) * PRICE / 1e6,
            'input_usd_per_million': PRICE, 'pricing_as_of': PRICE_DATE}


def valid(answer):
    return (isinstance(answer, dict) and answer.get('type') == 'noul' and
            type(answer.get('noul')) in (int, float) and math.isfinite(answer['noul']) and 0 <= answer['noul'] <= 1)


def retry_delay(headers):
    text = headers.get('retry-after', '')
    try:
        return max(1, float(text))
    except ValueError:
        try:
            return max(1, parsedate_to_datetime(text).timestamp() - time.time())
        except (ValueError, TypeError, OverflowError):
            return 2


class Pool:
    """No implicit retries, redirects, SDK dependency, or shared mutable socket."""
    def __init__(self, token):
        self.token = token
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()
        self.context = tls_context()

    def __call__(self, payload, timeout):
        connection = getattr(self.local, 'connection', None)
        if connection is None:
            connection = http.client.HTTPSConnection('api.typesafe.ai', timeout=timeout, context=self.context)
            self.local.connection = connection
            with self.lock:
                self.connections.append(connection)
        connection.timeout = timeout
        if connection.sock is not None:
            connection.sock.settimeout(timeout)
        deadline = time.monotonic() + timeout
        try:
            connection.request('POST', '/v1/systemone', body=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
                               headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', 'User-Agent': 'faultline/noul-v1'})
            response = connection.getresponse()
            headers = dict((k.lower(), v) for k, v in response.getheaders())
            pieces, length = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, 1000001 - length))
                if not chunk:
                    break
                pieces.append(chunk)
                length += len(chunk)
                if length > 1000000:
                    raise FaultlineError('Jev response exceeds byte limit')
            try:
                body = json.loads(b''.join(pieces))
            except (ValueError, UnicodeError):
                body = None
            return response.status, headers, body
        except Exception:
            connection.close()
            self.local.connection = None
            raise

    def close(self):
        for connection in self.connections:
            connection.close()


def evaluate(requests, progress, *, max_requests, max_cost, seconds, transport):
    lock = threading.Lock()
    starts, errors = [], []
    for recorded in progress.attempt_times:
        if recorded:
            age = time.time() - datetime.fromisoformat(recorded).timestamp()
            if age < 60:
                starts.append(time.monotonic() - max(0, age))
    stopped = False
    deadline = time.monotonic() + seconds
    cooldown = getattr(progress, 'cooldown_until', 0)

    def acquire(key):
        nonlocal stopped
        while True:
            with lock:
                now = time.monotonic()
                if stopped or now >= deadline:
                    raise FaultlineError('Shared dispatcher stopped or elapsed-time limit reached')
                cost = usage(progress)
                if len(progress.attempts) >= max_requests or cost['upper_usd'] + RESERVE * PRICE / 1e6 > max_cost:
                    raise FaultlineError('Run-wide request or dollar limit reached')
                recent = [t for t in starts if now - t < 1]
                minute = [t for t in starts if now - t < 60]
                delay = max(0, cooldown - time.time(), recent[0] + 1 - now if len(recent) >= 3 else 0,
                            minute[0] + 60 - now if len(minute) >= 180 else 0)
                if delay <= 0:
                    index = len(progress.attempts)
                    try:
                        progress.append('attempt', key)
                    except Exception:
                        stopped = True
                        raise
                    starts.append(now)
                    return index
            time.sleep(min(.05, delay))

    def worker(original):
        nonlocal stopped, cooldown
        key = digest(original)
        # Keep the exact original shared state; only unanswered questions are retried.
        with lock:
            missing = {qid: q for qid, q in original['questions'].items() if not progress.get(key, qid)}
        for wave in range(2):
            if not missing:
                return
            payload = {**original, 'questions': missing}
            try:
                index = acquire(digest(payload))
            except FaultlineError as exc:
                with lock:
                    errors.append(str(exc))
                return
            try:
                status, headers, raw = transport(payload, max(.01, min(30, deadline - time.monotonic())))
            except Exception:
                with lock:
                    stopped = True
                    errors.append('Jev connection failed; ambiguous attempt retained without automatic retry')
                return
            with lock:
                try:
                    tokens = raw.get('usage', {}).get('input_tokens') if isinstance(raw, dict) and isinstance(raw.get('usage'), dict) else None
                    if type(tokens) is int and 0 < tokens <= RESERVE:
                        progress.append('usage', {'attempt': index, 'usage': raw['usage']})
                    elif tokens is not None and (type(tokens) is not int or tokens < 0 or tokens > RESERVE):
                        stopped = True
                        errors.append('Invalid provider usage; dispatch stopped')
                        return
                    if status in (429, 529):
                        delay = retry_delay(headers)
                        if not math.isfinite(delay):
                            delay = seconds
                        cooldown = max(cooldown, time.time() + delay)
                        progress.append('cooldown', cooldown)
                        errors.append('Jev HTTP ' + str(status))
                    elif status != 200:
                        stopped = True
                        errors.append('Jev HTTP ' + str(status) + '; dispatch stopped')
                        return
                    elif not isinstance(raw, dict) or raw.get('model') != MODEL or not isinstance(raw.get('answers'), dict):
                        stopped = True
                        errors.append('Malformed response or model mismatch; dispatch stopped')
                        return
                    else:
                        pending = {}
                        for qid, question in missing.items():
                            answer = raw['answers'].get(qid)
                            if valid(answer):
                                progress.put({'request_key': key, 'question_id': qid, 'model': MODEL, 'answer': answer,
                                              'actual_request_key': digest(payload)})
                            else:
                                pending[qid] = question
                        missing = pending
                        if missing:
                            errors.append('Invalid Noul answers; bounded repair needed')
                except Exception:
                    stopped = True
                    raise
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        # Worker threads share durable accounting; paid attempts are written before dispatch.
        futures = [pool.submit(worker, request) for request in requests]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    return sorted(set(errors))
