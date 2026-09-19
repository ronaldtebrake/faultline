"""Read only Faultline's credential; never source files or expand expressions."""
from __future__ import annotations

import os
import re

from .core import FaultlineError

KEY = "TYPESAFE_API_KEY"


def api_key(store):
    token = os.environ.get(KEY)
    if token and token.strip():
        return token
    for path in (store.path / ".env", store.root / ".env"):
        try:
            text = path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError):
            raise FaultlineError("Cannot read credential .env file; check its permissions and UTF-8 encoding.") from None
        token = None
        for line in text.splitlines():
            match = re.match(r"^\s*(?:export\s+)?TYPESAFE_API_KEY\s*=(.*)$", line)
            if not match:
                continue
            value = match.group(1).strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0 or (value[end + 1:].strip() and not value[end + 1:].strip().startswith("#")):
                    raise FaultlineError("Invalid TYPESAFE_API_KEY assignment in .env; use one line with matching quotes.")
                value = value[1:end]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
            if any(char.isspace() for char in value):
                raise FaultlineError("Invalid TYPESAFE_API_KEY in .env; the key must not contain whitespace.")
            token = value
        if token:
            return token
    raise FaultlineError("Set TYPESAFE_API_KEY in the environment or in the analyzed repository's .faultline/.env (or root .env) to enable Jev evaluation.")
