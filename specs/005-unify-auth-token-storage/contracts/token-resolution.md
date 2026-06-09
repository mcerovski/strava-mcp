# Contract: Token Resolution

The internal contract for how credentials are resolved at runtime after this feature. Verified by
`tests/unit/test_tokens.py` and the `serve` scope-gate tests.

## `TokenStore.read() -> TokenSet | None`

- Returns the persisted `tokens` row as a `TokenSet`, or `None` if no row exists.
- **The only token source.** No environment fallback.
- Unchanged signature/behavior from today (it already only reads the DB).

## `TokenStore.current() -> TokenSet`

- Returns `read()`.
- If `read()` is `None`, raises `RuntimeError("No tokens available; run \`uv run strava-mcp auth\`.")`.
- **Removed**: the `or self._seed_from_env()` fallback. `_seed_from_env` is deleted.

**Contract tests**:
- Given a DB row → `current()` returns it.
- Given **no** DB row → `current()` **raises** `RuntimeError` (previously: returned the env seed).
- Given env vars that *used to* seed (now removed fields) → no effect; with no DB row `current()`
  still raises.

## `TokenStore.access_token() -> str` (worker token provider)

- Unchanged: calls `current()`, refreshes if within the expiry margin, persists rotated tokens,
  returns a valid access token.
- Now surfaces the "no tokens" `RuntimeError` from `current()` when the store is empty.

## `mcp/server.py::check_scopes(settings) -> list[str]`

- Reads the DB row via `TokenStore(conn, settings).read()`.
- If `None` → returns `list(REQUIRED_SCOPES)` (all missing).
- Else → returns `missing_scopes(tokens.scope)`.
- **Removed**: the `or _seed_tokens(settings)` fallback. `_seed_tokens` is deleted.

**Contract test** (`serve` gate): with no DB row and no env values, `check_scopes` reports all
required scopes missing, and `run_server` prints `run uv run strava-mcp auth` and returns `1`
(behavior preserved from today).

## Invariants

- Exactly **one** function reads token bytes from storage: `TokenStore.read()`.
- Exactly **one** function writes the initial token: the `auth` flow via `TokenStore.save()`.
- Refresh persists rotated tokens to the same row; no env copy exists to diverge.
