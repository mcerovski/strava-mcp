# Implementation Plan: Unify Auth Token Storage

**Branch**: `005-unify-auth-token-storage` | **Date**: 2026-06-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-unify-auth-token-storage/spec.md`

## Summary

Collapse Strava credential handling to a **single source of truth (the database `tokens` row)**
populated by a **single create path (the `auth` OAuth flow)** and read through a **single
resolver**. Delete the `.env` token seed entirely: the four `STRAVA_*_TOKEN*` settings fields
and both duplicated env→token readers (`auth/tokens.py::_seed_from_env` and
`mcp/server.py::_seed_tokens`). After this change, the only way tokens enter the system is
`auth`, and the only place runtime code reads them is `TokenStore.read()`. Existing
installations are out of scope (no migration/deprecation behavior).

This is a **deletion-and-simplification** change plus a constitution amendment to the "Secrets"
clause that currently sanctions the seed.

## Technical Context

**Language/Version**: Python 3.11+ (managed by `uv`)

**Primary Dependencies**: FastMCP (`streamable-http`), httpx, pydantic-settings

**Storage**: SQLite mirror (`.database/strava.db`); the single-row `tokens` table holds
credentials. No schema change required.

**Testing**: pytest (offline; real temp SQLite in WAL mode for DB-layer tests; no live Strava)

**Target Platform**: Local single-user loopback service (Linux)

**Project Type**: Single project — CLI + loopback MCP server + background worker

**Performance Goals**: N/A — auth/config path, not a hot path

**Constraints**: Loopback-only transport; read-only OAuth scopes; no secret written outside
`.database/`; no live-API calls in tools or tests

**Scale/Scope**: Small, surgical change across 3 source files + 1 test file + docs + constitution

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Code Quality & Architectural Integrity** — ✅ **Strengthened.** Removes duplicated logic
  (two seed readers → one `read()` source), preserves `config`/`auth`/`mcp` separation, keeps
  MCP tools as pure readers (untouched). Vocabulary discipline respected.
- **II. Testing Standards (NON-NEGOTIABLE)** — ✅ Honored. The behavior change (no env fallback;
  missing tokens → actionable error) is covered by updating `tests/unit/test_tokens.py` and
  asserting the resolver raises/returns-missing without a DB row. DB-layer tests continue to use
  a real temp SQLite. Regression-first: rewrite the precedence test before deleting the code.
- **III. User Experience Consistency** — ✅ Preserved. `serve` with no usable token still exits
  with the actionable `run uv run strava-mcp auth` instruction (FR-007).
- **IV. Performance & Rate-Limit Discipline** — ✅ Unaffected. Refresh/rate-limit logic
  unchanged; single writer / WAL unchanged.
- **Technology & Security Constraints** — ⚠️ **Amendment required.** The *Secrets* clause states
  "Tokens persist in the DB after first auth; `.env` only seeds the initial run." Removing the
  seed contradicts this sentence, so the constitution MUST be amended in the same change
  (proposed MINOR bump 2.0.0 → 2.1.0: tightens guidance — the `.env` seed allowance is removed;
  `.env` now carries only client credentials). This is tracked, not a blocking violation.

**Gate result**: PASS (with the constitution amendment folded into the change as a required
deliverable; logged below, not in Complexity Tracking, since it is a governance update rather
than an architectural exception).

## Project Structure

### Documentation (this feature)

```text
specs/005-unify-auth-token-storage/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── token-resolution.md
│   └── config-surface.md
└── checklists/
    └── requirements.md  # from /speckit-specify
```

### Source Code (repository root)

```text
strava_mcp/
├── config.py                  # EDIT: delete 4 token seed fields (strava_access_token,
│                              #       strava_refresh_token, strava_token_expires_at,
│                              #       strava_token_scope)
├── auth/
│   └── tokens.py              # EDIT: delete _seed_from_env(); current() = read()-or-raise
├── mcp/
│   └── server.py              # EDIT: delete _seed_tokens(); check_scopes() reads DB only
└── (all other modules unchanged — tools remain pure readers)

tests/
└── unit/
    └── test_tokens.py         # EDIT: replace test_db_overrides_env_seed with
                               #       "no DB row → current() raises; read() is sole source"

.env.example                   # EDIT: remove the 4 token seed lines + their comment block
README.md                      # EDIT: token/Secrets wording → single-store model
.specify/memory/constitution.md# EDIT: amend Secrets clause; bump version 2.0.0 → 2.1.0
```

**Structure Decision**: Single-project layout (existing). No new modules, no schema change.
The change is concentrated in `config.py`, `auth/tokens.py`, and `mcp/server.py`, with
corresponding doc/test/constitution updates.

## Complexity Tracking

> No constitution violations requiring justification. The Secrets-clause amendment is a planned
> governance update (folded into this change), not an architectural exception, so this table is
> intentionally empty.
