"""Dual-sink logging (stdout + rotating file) with secret redaction.

No secrets are ever written to either sink (PRD §6.5, Constitution). A filter
scrubs token-like values from every record before it is emitted (research R11).
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FILENAME = "strava-mcp.log"

# Patterns that look like secrets in messages/args. Conservative but effective:
# bearer headers, oauth token JSON fields, and long hex/secret-ish blobs.
_REDACTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r'(?i)("?(?:access_token|refresh_token|client_secret|code)"?\s*[:=]\s*"?)'
            r"[A-Za-z0-9._\-]+"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"\b[0-9a-f]{32,}\b"), "[REDACTED]"),
)

REDACTED = "[REDACTED]"


def _scrub(text: str) -> str:
    for pattern, repl in _REDACTION_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactionFilter(logging.Filter):
    """Scrub token-like values from the formatted message and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _scrub(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub_arg(v) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub_arg(a) for a in record.args)
        return True

    @staticmethod
    def _scrub_arg(value: object) -> object:
        return _scrub(value) if isinstance(value, str) else value


def setup_logging(db_path: Path | str, *, level: int = logging.INFO) -> logging.Logger:
    """Configure the ``strava_mcp`` logger with stdout + rotating-file sinks.

    The log file lives next to the database (``./.database/strava-mcp.log``).
    Idempotent: repeated calls do not stack handlers.
    """
    logger = logging.getLogger("strava_mcp")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger

    log_dir = Path(db_path).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / _LOG_FILENAME

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    redaction = RedactionFilter()

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    stream.addFilter(redaction)

    rotating = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    rotating.setFormatter(fmt)
    rotating.addFilter(redaction)

    logger.addHandler(stream)
    logger.addHandler(rotating)
    return logger


def get_logger(name: str = "strava_mcp") -> logging.Logger:
    return logging.getLogger(name)
