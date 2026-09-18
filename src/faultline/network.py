"""Serial bounded HTTP, explicit backoff, and persistent GET caches."""
from __future__ import annotations

import json
import os
import random
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path

from .core import FaultlineError, digest, read_json, write_json


@dataclass
class Budget:
    limit: int
    used: int = 0

    def take(self):
        if self.used >= self.limit:
            raise FaultlineError(f"Request ceiling reached ({self.limit}); saved work can be resumed.")
        self.used += 1


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https":
            raise FaultlineError("Refused a non-HTTPS API redirect")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and target.netloc != urllib.parse.urlsplit(req.full_url).netloc:
            redirected.remove_header("Authorization")
        return redirected


def github_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                    capture_output=True, text=True)
            token = result.stdout.strip() if result.returncode == 0 else None
        except FileNotFoundError:
            pass
    if not token:
        raise FaultlineError("GitHub authentication required: run gh auth login or set GH_TOKEN.")
    return token


class HTTP:
    def __init__(self, cache: Path, provider: str, config: dict, token: str, budget: Budget):
        self.cache = cache / provider
        self.config, self.token, self.budget, self.provider = config, token, budget, provider
        self.last = 0.0
        self.opener = urllib.request.build_opener(SafeRedirect())
        self.cache_hits = 0
        self.seen = set()

    def request(self, url, *, payload=None, accept="application/vnd.github+json", cached=True,
                refresh=False, binary=False, max_bytes=8_000_000):
        parts = urllib.parse.urlsplit(url)
        expected = "api.github.com" if self.provider == "github" else "api.typesafe.ai"
        if parts.scheme != "https" or parts.netloc != expected:
            raise FaultlineError("Refused an unexpected API origin")
        key = digest([url, accept])
        cache_file = self.cache / (key + ".json")
        previous = read_json(cache_file) if cached and payload is None else None
        if previous and (not refresh or key in self.seen):
            self.cache_hits += 1
            return previous["data"], previous.get("headers", {})
        cooldown = read_json(self.cache / "cooldown.json", {})
        delay = cooldown.get("until", 0) - time.time()
        if delay > self.config["max_wait"]:
            raise FaultlineError(f"{self.provider} rate limit still active; resume after the reported reset time.")
        if delay > 0:
            time.sleep(delay)
        headers = {"Authorization": f"Bearer {self.token}", "Accept": accept,
                   "User-Agent": "faultline-cli/0.1"}
        if self.provider == "github":
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        if previous:
            etag = previous.get("headers", {}).get("etag")
            if etag:
                headers["If-None-Match"] = etag
        for attempt in range(self.config["retries"] + 1):
            self.budget.take()
            time.sleep(max(0, self.last + self.config["request_interval"] - time.monotonic()))
            self.last = time.monotonic()
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with self.opener.open(request, timeout=45) as response:
                    raw = response.read(max_bytes + 1)
                    response_headers = {k.lower(): v for k, v in response.headers.items()}
                if len(raw) > max_bytes:
                    raise FaultlineError("Response exceeded the configured size limit; data was not truncated.")
                if binary:
                    return raw, response_headers
                try:
                    data = json.loads(raw)
                except ValueError as exc:
                    raise FaultlineError("Provider returned malformed JSON") from exc
                if cached and payload is None:
                    # Store only cache/pagination headers, never cookies or auth.
                    safe = {k: v for k, v in response_headers.items() if k in ("etag", "last-modified", "link")}
                    write_json(cache_file, {"data": data, "headers": safe})
                    self.seen.add(key)
                return data, response_headers
            except urllib.error.HTTPError as exc:
                if exc.code == 304 and previous:
                    self.cache_hits += 1
                    self.seen.add(key)
                    return previous["data"], previous.get("headers", {})
                retryable = exc.code in (429, 529) or (payload is None and exc.code in (500, 502, 503, 504))
                remaining = exc.headers.get("x-ratelimit-remaining")
                # Distinguish permission errors from GitHub secondary limits.
                if exc.code == 403:
                    error_body = exc.read(4096).decode(errors="replace").lower()
                    retryable = remaining == "0" or "rate limit" in error_body or bool(exc.headers.get("Retry-After"))
                if not retryable:
                    raise FaultlineError(f"{self.provider} HTTP {exc.code}; verify credentials, permissions, or request configuration.") from None
                delay = (60 if self.provider == "github" else 2) * (2 ** attempt) + random.random()
                retry_after = exc.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        try:
                            delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                        except (ValueError, TypeError):
                            pass
                if remaining == "0":
                    try:
                        delay = max(delay, float(exc.headers.get("x-ratelimit-reset", 0)) - time.time() + 1)
                    except ValueError:
                        pass
                write_json(self.cache / "cooldown.json", {"until": time.time() + delay})
                if delay > self.config["max_wait"] or attempt == self.config["retries"]:
                    raise FaultlineError(f"{self.provider} rate limited/unavailable; resume in at least {int(delay) + 1}s.") from None
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError):
                # Do not retry ambiguous inference failures: they may have been billed.
                raise FaultlineError(f"{self.provider} connection failed; saved work is intact. No automatic ambiguous retry.") from None
        raise FaultlineError("Retry limit reached")
