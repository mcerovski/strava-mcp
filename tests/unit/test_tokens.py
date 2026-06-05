"""T012 [US1] Token storage, .env-override precedence, near-expiry auto-refresh."""

from __future__ import annotations

import sqlite3

import httpx
import pytest
from strava_mcp.auth.tokens import TokenSet, TokenStore
from strava_mcp.config import Settings


def _settings(**overrides: object) -> Settings:
    base = dict(
        strava_client_id="cid",
        strava_client_secret="csecret",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_save_and_read_roundtrip(conn: sqlite3.Connection) -> None:
    store = TokenStore(conn, _settings())
    tokens = TokenSet("acc", "ref", 2_000_000_000, "read,activity:read_all")
    store.save(tokens)
    got = store.read()
    assert got == tokens


def test_db_overrides_env_seed(conn: sqlite3.Connection) -> None:
    settings = _settings(
        strava_access_token="env-acc",
        strava_refresh_token="env-ref",
        strava_token_expires_at=2_000_000_000,
        strava_token_scope="read",
    )
    store = TokenStore(conn, settings)
    # With no DB row, the env seed is used.
    assert store.current().access_token == "env-acc"
    # Once a DB row exists, it wins over the env seed.
    store.save(TokenSet("db-acc", "db-ref", 2_000_000_000, "read"))
    assert store.current().access_token == "db-acc"


def test_missing_tokens_raises(conn: sqlite3.Connection) -> None:
    store = TokenStore(conn, _settings())
    with pytest.raises(RuntimeError):
        store.current()


def test_near_expiry_triggers_refresh_and_persists_rotated_token(
    conn: sqlite3.Connection,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "access_token": "fresh-acc",
                "refresh_token": "rotated-ref",
                "expires_at": 4_000_000_000,
                "expires_in": 21600,
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    # Clock far past the stored expiry → refresh path.
    store = TokenStore(conn, _settings(), now=lambda: 3_000_000_000.0, client=client)
    store.save(TokenSet("old-acc", "old-ref", 1_000_000_000, "read,activity:read_all"))

    token = store.access_token()
    assert token == "fresh-acc"
    persisted = store.read()
    assert persisted is not None
    assert persisted.refresh_token == "rotated-ref"  # rotation persisted
    assert persisted.scope == "read,activity:read_all"  # scope preserved


def test_valid_token_is_not_refreshed(conn: sqlite3.Connection) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not refresh a still-valid token")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = TokenStore(conn, _settings(), now=lambda: 1_000.0, client=client)
    store.save(TokenSet("acc", "ref", 2_000_000_000, "read"))
    assert store.access_token() == "acc"
