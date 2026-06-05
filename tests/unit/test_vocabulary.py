"""T068 Vocabulary discipline: code/docs use CONTEXT.md terms, not banned synonyms.

CONTEXT.md fixes the shared language (backfill, frontier, poll, enrichment, fully
synced, raw store). This guard scans ``strava_mcp/`` for unambiguous banned
synonyms — multi-word phrases that would only appear as domain-vocabulary drift,
avoiding false positives on legitimate technical words (Python ``import``, OAuth
token ``refresh``, ``lru_cache``, SQL ``UPDATE``).
"""

from __future__ import annotations

import re
from pathlib import Path

import strava_mcp

_PKG_DIR = Path(strava_mcp.__file__).parent

# Phrases banned by CONTEXT.md that have no legitimate technical use here.
_BANNED = [
    r"initial sync",
    r"full sync",
    r"re-?sync",
    r"hydration",
    r"telemetry",
    r"blob store",
    r"up to date",
]
_BANNED_RE = re.compile("|".join(_BANNED), re.IGNORECASE)

# Canonical terms that must appear somewhere in the package.
_REQUIRED_TERMS = ["backfill", "frontier", "poll", "enrichment", "fully_synced", "raw"]


def _all_source() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in _PKG_DIR.rglob("*.py")}


def test_no_banned_synonyms() -> None:
    offenders: dict[str, list[str]] = {}
    for path, text in _all_source().items():
        hits = _BANNED_RE.findall(text)
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"banned vocabulary found: {offenders}"


def test_canonical_terms_present() -> None:
    corpus = "\n".join(_all_source().values()).lower()
    missing = [term for term in _REQUIRED_TERMS if term not in corpus]
    assert not missing, f"canonical terms missing from the codebase: {missing}"
