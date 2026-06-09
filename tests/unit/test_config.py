"""[US2] Config surface: no Strava token seed fields; legacy keys load harmlessly."""

from __future__ import annotations

import pytest
from strava_mcp.config import Settings

_REMOVED_TOKEN_FIELDS = (
    "strava_access_token",
    "strava_refresh_token",
    "strava_token_expires_at",
    "strava_token_scope",
)


def test_settings_has_no_token_seed_fields() -> None:
    # The four `.env` token seed fields are gone — only client credentials remain.
    for field in _REMOVED_TOKEN_FIELDS:
        assert field not in Settings.model_fields, f"{field} should be removed"


@pytest.mark.parametrize("field", _REMOVED_TOKEN_FIELDS)
def test_settings_exposes_no_token_attribute(field: str) -> None:
    settings = Settings(strava_client_id="c", strava_client_secret="s", _env_file=None)  # type: ignore[call-arg]
    assert not hasattr(settings, field)


def test_legacy_env_token_keys_load_without_error() -> None:
    # A developer's pre-existing .env that still lists the removed keys must load
    # cleanly (extra=ignore) — the values are simply ignored.
    settings = Settings(
        strava_client_id="c",
        strava_client_secret="s",
        STRAVA_ACCESS_TOKEN="ignored",
        STRAVA_REFRESH_TOKEN="ignored",
        STRAVA_TOKEN_EXPIRES_AT="123",
        STRAVA_TOKEN_SCOPE="read",
        _env_file=None,
    )  # type: ignore[call-arg]
    assert settings.strava_client_id == "c"


def test_client_credentials_are_retained() -> None:
    assert "strava_client_id" in Settings.model_fields
    assert "strava_client_secret" in Settings.model_fields
