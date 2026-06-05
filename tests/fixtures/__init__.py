"""Loader for recorded Strava API fixtures.

The JSON files in this directory are hand-built records shaped to the models in
`strava-api-spec/swagger/*.json`. They stand in for live Strava responses so the
whole suite runs offline and deterministically (Constitution II, research R13).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURE_DIR = Path(__file__).parent


def load(name: str) -> Any:
    """Load a recorded fixture by stem (e.g. ``"activity_detail"``)."""
    path = _FIXTURE_DIR / f"{name}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
