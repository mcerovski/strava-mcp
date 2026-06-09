---

description: "Task list for Unify Auth Token Storage"
---

# Tasks: Unify Auth Token Storage

**Input**: Design documents from `/specs/005-unify-auth-token-storage/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED — not because the spec requested them, but because the project constitution
(Principle II, NON-NEGOTIABLE) mandates regression-first coverage for any change to token
resolution. Each behavior change lands its test first.

**Organization**: Tasks are grouped by user story. The three stories touch **distinct files**
(`auth/tokens.py` ⟂ `config.py`/`.env.example`/`README.md` ⟂ `mcp/server.py`), so after the
foundational phase they are independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories)

## Path Conventions

Single project. Source at `strava_mcp/`, tests at `tests/`, repo-root config/docs. Use `uv run`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish a known-green baseline before any deletion.

- [X] T001 Establish green baseline: run `uv run pytest -q` and `uv run ruff check` from repo root and confirm both pass; note any pre-existing failures so they aren't attributed to this change.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Governance update that authorizes removing the `.env` seed. The constitution's
*Secrets* clause currently sanctions the seed, so it must be amended in the same change.

**⚠️ CRITICAL**: This phase must be complete before the change can merge.

- [X] T002 Amend the *Secrets* clause in `.specify/memory/constitution.md` to state tokens live solely in the DB and `.env` carries only client credentials (remove the "`.env` only seeds the initial run" allowance); bump version `2.0.0 → 2.1.0` and add a SYNC IMPACT REPORT entry describing the MINOR amendment.

**Checkpoint**: Governance updated — token-storage simplification is now sanctioned.

---

## Phase 3: User Story 1 - Credentials live in exactly one place (Priority: P1) 🎯 MVP

**Goal**: The database `tokens` row is the single source of truth; with no row, resolution fails
with the actionable "run auth" error instead of falling back to the environment.

**Independent Test**: Unit-test `TokenStore` — a DB row resolves; no DB row raises the actionable
`RuntimeError`. No env values can authorize the worker path.

### Tests for User Story 1 ⚠️ (write first, ensure it fails)

- [X] T003 [US1] Rewrite `tests/unit/test_tokens.py`: replace `test_db_overrides_env_seed` with a test asserting (a) with a DB row, `current()` returns it; (b) with **no** DB row, `current()` raises `RuntimeError` matching `run uv run strava-mcp auth`; remove the `strava_access_token`/`strava_refresh_token` constructor kwargs. Confirm it FAILS against current code.

### Implementation for User Story 1

- [X] T004 [US1] In `strava_mcp/auth/tokens.py`, change `current()` to return `self.read()` and raise `RuntimeError("No tokens available; run \`uv run strava-mcp auth\`.")` when it is `None`; delete the `_seed_from_env()` method.
- [X] T005 [US1] Run `uv run pytest tests/unit/test_tokens.py -q` green and confirm `access_token()` (worker token provider) still refreshes near-expiry and persists rotated tokens.

**Checkpoint**: The worker resolves credentials from the DB only; no env fallback remains.

---

## Phase 4: User Story 2 - No plaintext token secrets in configuration (Priority: P2)

**Goal**: The four `STRAVA_*_TOKEN*` fields are gone from settings and the shipped template; only
client credentials remain in `.env`.

**Independent Test**: `Settings()` exposes no token fields; `.env.example` has no token lines;
`docker compose config` shows no token secret.

### Tests for User Story 2 ⚠️

- [X] T006 [US2] Add/extend a config test (e.g. `tests/unit/test_config.py` or the nearest existing config test) asserting that `Settings(_env_file=None)` has no `strava_access_token`/`strava_refresh_token`/`strava_token_expires_at`/`strava_token_scope` attributes, and that constructing `Settings` from an env mapping containing those keys loads without error (extra=ignore). Confirm it FAILS against current code.

### Implementation for User Story 2

- [X] T007 [P] [US2] Delete the four token seed fields and their "Optional bootstrap token seed" comment from `Settings` in `strava_mcp/config.py` (keep `strava_client_id` / `strava_client_secret`).
- [X] T008 [P] [US2] Remove the four `STRAVA_*_TOKEN*` lines and the "Bootstrap OAuth tokens" comment block from `.env.example` (retain the client-credentials section).
- [X] T009 [P] [US2] Update `README.md` token/Secrets wording to the single-store model: `auth` writes tokens to the DB; `.env` holds only client credentials.
- [X] T010 [US2] Run the config test from T006 green; verify `grep -E 'STRAVA_(ACCESS|REFRESH)_TOKEN|STRAVA_TOKEN_' .env.example` returns nothing (per `contracts/config-surface.md`).

**Checkpoint**: No Strava token secret exists anywhere in configuration.

---

## Phase 5: User Story 3 - One code path resolves the active token (Priority: P2)

**Goal**: Remove the second, duplicated seed reader so `serve`'s scope gate and the worker both
resolve tokens from the single DB source.

**Independent Test**: With no DB row, `check_scopes` reports all required scopes missing and
`serve` exits 1 with the actionable instruction — via a DB-only read, no `_seed_tokens`.

### Tests for User Story 3 ⚠️

- [X] T011 [US3] In `tests/contract/test_serve_athlete.py`, ensure a case asserts that with no DB row (and no env values) `check_scopes` returns all `REQUIRED_SCOPES` and `run_server` returns `1` after printing `run uv run strava-mcp auth`; adjust the "no env seed" comment to reflect that env seeding no longer exists. Confirm expectations hold/fail as appropriate before implementation.

### Implementation for User Story 3

- [X] T012 [US3] In `strava_mcp/mcp/server.py`, change `check_scopes()` to resolve via `TokenStore(conn, settings).read()` only (None → `list(REQUIRED_SCOPES)`); delete the `_seed_tokens()` helper.
- [X] T013 [US3] Run `uv run pytest tests/contract/test_serve_athlete.py -q` green.

**Checkpoint**: Exactly one token source (`TokenStore.read()`); both consumers go through it.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Prove the simplification is complete and leaves no residue.

- [X] T014 [P] Run the full suite green (`uv run pytest -q`) and static checks clean (`uv run ruff check`; type-check per `pyproject.toml`).
- [X] T015 [P] Grep for residual seed references: `grep -rn "strava_access_token\|strava_refresh_token\|_seed_from_env\|_seed_tokens\|STRAVA_ACCESS_TOKEN" strava_mcp/ .env.example` MUST return no source matches (token-handling references may remain only in deleted-history/tests intentionally).
- [X] T016 Run `quickstart.md` scenarios 1, 2, and 4: no-token → actionable error; legacy env values ignored; no token secret in `.env.example` / `docker compose config`.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately.
- **Foundational (Phase 2)**: after Setup. The constitution amendment gates merge of the stories.
- **User Stories (Phase 3–5)**: after Foundational. Touch disjoint files → independently testable;
  can proceed in parallel.
- **Polish (Phase 6)**: after all desired stories complete.

### User Story Dependencies

- **US1 (P1)** — `auth/tokens.py` + `tests/unit/test_tokens.py`. No dependency on US2/US3.
- **US2 (P2)** — `config.py` + `.env.example` + `README.md` (+ a config test). Fully independent.
- **US3 (P2)** — `mcp/server.py` + `tests/contract/test_serve_athlete.py`. Independent of US1/US2
  (different file); shares the same *intent* (DB-only resolution) but no code dependency.

### Within Each User Story

- Test first (must fail) → implementation → run green.

### Parallel Opportunities

- US1, US2, US3 can be implemented in parallel by different developers (disjoint files).
- Within US2, T007/T008/T009 are `[P]` (config / env template / README are separate files).
- Polish T014/T015 are `[P]`.

---

## Parallel Example: after Foundational

```bash
# Three developers pick up one story each (disjoint files):
Dev A → US1: tests/unit/test_tokens.py + strava_mcp/auth/tokens.py
Dev B → US2: strava_mcp/config.py + .env.example + README.md
Dev C → US3: tests/contract/test_serve_athlete.py + strava_mcp/mcp/server.py

# Within US2, the three implementation edits run in parallel:
Task: "Delete token fields in strava_mcp/config.py"
Task: "Remove token lines in .env.example"
Task: "Update Secrets wording in README.md"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational (constitution amendment).
2. Phase 3 US1 → the single-source resolver. **STOP and validate**: worker resolves from DB only;
   no-token raises the actionable error. This alone delivers "credentials in one place."

### Incremental Delivery

1. Setup + Foundational → governance ready.
2. US1 → single source of truth (MVP).
3. US2 → remove the plaintext-secret config surface.
4. US3 → remove the duplicated second reader.
5. Polish → full suite green, no residue, quickstart validated.

### Note on coupling

This is a deletion-driven change; the three stories are small and the realistic path is to land
them together in one commit. The story split exists for traceability and to keep each behavior
change paired with its own failing-first test, not to imply they ship separately.

---

## Notes

- [P] = different files, no dependencies.
- Every behavior change is paired with a regression-first test (Principle II).
- Verify each test fails before implementing.
- The constitution amendment (T002) MUST land in the same change as the code (per plan.md gate).
