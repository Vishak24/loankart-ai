"""Keeps credentials out of logs, stored events and error text.

`register()` is given every secret value the process holds; `redact()` then removes those exact values, plus anything shaped
like a key, bearer token, auth header or session cookie. `install_log_scrubbing()` applies it to every log record.
"""

import logging
import re
import threading
import traceback

_PLACEHOLDER = "[redacted]"
_MIN_LEN = 6                                   # shorter values would mangle ordinary text
_values: set[str] = set()
_lock = threading.Lock()
_PATTERNS = [                                                                        # (pattern, replacement)
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), _PLACEHOLDER),                           # provider key shapes (sk-ant-..., sk-...)
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), rf"\1 {_PLACEHOLDER}"),   # Authorization values
    (re.compile(r"(?i)\b(authorization|x-api-key|api-subscription-key|api[_-]?key|cookie|set-cookie)\b(['\"]?\s*[:=]\s*['\"]?)[^\s,;'\"}%]+"),               # '%' stops a match so a log template's %s survives
     rf"\1\2{_PLACEHOLDER}"),
    (re.compile(r"\b(lk_adv|lk_bor)=[^\s;,]+"), rf"\1={_PLACEHOLDER}"),            # this app's session cookies
]


def register(*secrets: str) -> None:
    with _lock:
        _values.update(s for s in secrets if s and len(s) >= _MIN_LEN)


def redact(text: object) -> str:
    out = str(text)
    for value in sorted(_values, key=len, reverse=True):
        out = out.replace(value, _PLACEHOLDER)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def _clean(arg: object) -> object:
    if isinstance(arg, (int, float)):
        return arg                                                         # numbers stay numbers so "%d" still works
    text = redact(arg)
    return arg if text == str(arg) else text                               # untouched args keep their type


_installed = False


def install_log_scrubbing() -> None:
    """Wrap the record factory once, so every logger in the process (ours, uvicorn, httpx, SDKs) is scrubbed."""
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        record = previous(*args, **kwargs)
        record.msg = redact(record.msg)                               # also covers log.error(exc), whose msg is not a string
        if isinstance(record.args, tuple):                           # keep the shape: uvicorn's formatter unpacks args
            record.args = tuple(_clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _clean(v) for k, v in record.args.items()}
        if record.exc_info:                                          # tracebacks carry exception text: render it scrubbed now
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        return record

    logging.setLogRecordFactory(factory)
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic", "sarvamai", "fern"):     # their DEBUG output includes request headers
        logging.getLogger(noisy).setLevel(logging.WARNING)
