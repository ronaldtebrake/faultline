"""Serial Jev HTTP with finite budgets and persisted rate-limit cooldowns."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from .core import FaultlineError, read_json, write_json


@dataclass
class Budget:
    limit: int
    used: int = 0

    def take(self):
        if self.used >= self.limit:
            raise FaultlineError(f"Request ceiling reached ({self.limit}); saved work can be resumed.")
        self.used += 1


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward inference data or credentials to a redirected origin.
        return None


class HTTP:
    def __init__(self, cache: Path, provider: str, config: dict, token: str, budget: Budget, *, deadline=None):
        self.cache = cache / provider
        self.config, self.token, self.budget = config, token, budget
        self.deadline = deadline
        self.last = 0.0
        self.opener = urllib.request.build_opener(NoRedirect())

    def remaining(self):
        if self.deadline is None:
            return 45.0
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise FaultlineError("Selection time budget exhausted; execute the affected suite fully")
        return min(45.0, value)

    def pause(self, delay):
        if self.deadline is not None and delay >= self.deadline - time.monotonic():
            raise FaultlineError("Rate limiting/pacing exceeds the remaining selection time budget")
        time.sleep(max(0, delay))
        self.remaining()

    def request(self, url, *, payload, cached=False, accept="application/json", max_bytes=1_000_000):
        if url != "https://api.typesafe.ai/v1/systemone":
            raise FaultlineError("Refused an unexpected inference endpoint")
        cooldown = read_json(self.cache / "cooldown.json", {})
        delay = cooldown.get("until", 0) - time.time()
        if delay > self.config["max_wait"]:
            raise FaultlineError(f"Jev rate limit still active; resume in at least {int(delay) + 1}s.")
        if delay > 0:
            self.pause(delay)
        headers = {"Authorization": f"Bearer {self.token}", "Accept": accept,
                   "User-Agent": "faultline-cli/0.1", "Content-Type": "application/json"}
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        for attempt in range(self.config["retries"] + 1):
            self.pause(max(0, self.last + self.config["request_interval"] - time.monotonic()))
            self.budget.take()
            self.last = time.monotonic()
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with self.opener.open(request, timeout=self.remaining()) as response:
                    if self.deadline is not None and hasattr(response, 'read1'):
                        chunks, total = [], 0
                        while total <= max_bytes:
                            remaining = self.remaining()
                            # CPython's HTTPResponse exposes the underlying socket here.
                            sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                            if sock is not None:
                                sock.settimeout(remaining)
                            chunk = response.read1(min(65536, max_bytes + 1 - total))
                            if not chunk:
                                break
                            chunks.append(chunk)
                            total += len(chunk)
                        raw = b''.join(chunks)
                    else:
                        raw = response.read(max_bytes + 1)
                    self.remaining()
                if len(raw) > max_bytes:
                    raise FaultlineError("Jev response exceeded the size limit; data was not truncated.")
                try:
                    data = json.loads(raw)
                except ValueError:
                    raise FaultlineError("Jev returned malformed JSON") from None
                return data, {}
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 529):
                    raise FaultlineError(f"Jev HTTP {exc.code}; verify credentials, permissions, and request configuration. No response body was logged.") from None
                delay = 2 * (2 ** attempt) + random.random()
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                        except (ValueError, TypeError):
                            pass
                write_json(self.cache / "cooldown.json", {"until": time.time() + delay})
                if delay > self.config["max_wait"] or attempt == self.config["retries"]:
                    raise FaultlineError(f"Jev rate limited/overloaded; resume in at least {int(delay) + 1}s.") from None
                self.pause(delay)
            except (urllib.error.URLError, TimeoutError, OSError):
                raise FaultlineError("Jev connection failed; saved work is intact. No automatic retry of an ambiguous inference request.") from None
        raise FaultlineError("Retry limit reached")
