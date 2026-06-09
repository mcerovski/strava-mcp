# Feature Specification: Unify Auth Token Storage

**Feature Branch**: `005-unify-auth-token-storage`

**Created**: 2026-06-09

**Status**: Draft

**Input**: User description: "analyze auth process … the `.env` tokens are only consulted if the DB has no token row … they're dead weight, provably stale, a plaintext-secret liability serving no function … see if it can be optimized and simplified, then propose how to actually do it correctly without multiple auth processes and storage."

## Why This Feature

Today Strava credentials can live in **two places** and be resolved by **two near-identical
code paths**:

- **Storage A — the database `tokens` row** (the source of record once `auth` has run).
- **Storage B — four `.env` seed values** (`STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN`,
  `STRAVA_TOKEN_EXPIRES_AT`, `STRAVA_TOKEN_SCOPE`), consulted only when the DB has no row.

The seed is a one-time bootstrap that, in practice, becomes **dead weight the moment `auth`
runs** — the DB row wins forever after. The seed values then sit in `.env` as **plaintext,
long-lived secrets** (access *and* refresh tokens) that no longer match reality (e.g. a
stale `scope=read` while the DB holds full scope), leak into process environment and
`docker compose config` output, and serve no function.

Worse, the fallback logic is **duplicated**: `auth/tokens.py::_seed_from_env()` and
`mcp/server.py::_seed_tokens()` implement the same env→TokenSet mapping independently, so the
two can silently drift.

This feature collapses the model to **one store, one create path, and one read path**: the
database is the single source of truth, populated solely by the `auth` authorization flow and
read through a single resolver. The environment seed, its four config fields, and both
duplicated readers are removed outright.

**Scope note**: existing installations are explicitly out of scope. There is no migration,
upgrade-compatibility, or deprecation-warning behavior to design — the seed and its config
fields are simply deleted.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Credentials live in exactly one place (Priority: P1)

As the operator running the server, after I authorize once, my Strava tokens are stored in a
single canonical location (the local database). I never need to copy, paste, or maintain token
values anywhere else, and there is no second place that could hold a conflicting copy.

**Why this priority**: This is the core of the request — eliminating dual storage. Everything
else (security, deduplicated code) follows from establishing one source of truth.

**Independent Test**: On a clean install, run the authorization flow, then start the server and
confirm it operates using the stored tokens while no token values exist anywhere in
configuration. Delete/blank any config token fields and confirm behavior is unchanged.

**Acceptance Scenarios**:

1. **Given** a clean install with no stored tokens, **When** the operator completes the
   authorization flow, **Then** the resulting tokens are written to the single database store
   and the server starts and serves using them.
2. **Given** a database that already holds a token record, **When** the server starts, **Then**
   it uses the stored record and consults no environment/config token values.
3. **Given** the access token is near or past expiry, **When** the worker needs to call Strava,
   **Then** it refreshes using the app client credentials + stored refresh token and persists
   the rotated tokens back to the same single store.

---

### User Story 2 - No plaintext token secrets in configuration (Priority: P1)

As a security-conscious operator, my configuration file (`.env`) never needs to contain Strava
access or refresh tokens, so those long-lived secrets are not duplicated into env files, the
process environment, or container configuration dumps.

**Why this priority**: Removing standing plaintext secrets is a direct security improvement and
a primary motivation; it is independently valuable even before the code dedup.

**Independent Test**: Inspect the shipped configuration template and a default install's
resolved environment (including `docker compose config`) and confirm no Strava token value is
present, while the server still authorizes and serves normally.

**Acceptance Scenarios**:

1. **Given** the shipped configuration template, **When** an operator sets up the project,
   **Then** there are no access/refresh/expiry/scope token fields to fill in — only the app
   client credentials.
2. **Given** a running container that mounts the configuration, **When** the operator dumps the
   effective configuration, **Then** no Strava token secret appears in the output.

---

### User Story 3 - One code path resolves the active token (Priority: P2)

As a maintainer, exactly one piece of code resolves "the active token set," used by both the
startup scope check and the worker's token provider, so the two cannot drift and there is a
single place to reason about token state.

**Why this priority**: Correctness/maintainability win that removes the duplicated seed logic;
valuable but secondary to the user-facing single-store and security outcomes.

**Independent Test**: Inspect the codebase for the number of functions that map credentials to
an active token set; confirm there is one, exercised by tests covering both startup and worker
usage.

**Acceptance Scenarios**:

1. **Given** the server starting up, **When** it checks scope sufficiency, **Then** it resolves
   the active token through the same single function the worker uses.
2. **Given** no stored token record, **When** either startup or the worker resolves the token,
   **Then** both reach the identical "no tokens — run authorization" outcome via that one path.

---

### Edge Cases

- **No tokens anywhere** (fresh install, authorization never run): startup MUST fail with an
  actionable instruction to run the authorization command — not a stack trace or silent hang.
- **Refresh token rotation**: when Strava rotates the refresh token, the new value is persisted
  back to the single store; there is no environment copy to update or consult.
- **Headless environment**: the operator runs the authorization flow once; when no browser can
  be opened it prints the authorization URL to complete in any browser. Moving an install to a
  new host is done by copying the database file (which carries the tokens), not by configuring
  token values. The interactive authorization flow is the **sole** supported way to populate
  the store.
- **Corrupt/partial token record**: a record missing required fields is treated as "no usable
  token," yielding the same actionable "run authorization" outcome rather than a crash.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST treat the local database token record as the single source of
  truth for Strava credentials.
- **FR-002**: The system MUST populate that record through exactly one authorization path (the
  existing one-time OAuth authorization flow), which writes the resulting tokens to the single
  store.
- **FR-003**: At runtime, the system MUST NOT read Strava access or refresh tokens from the
  environment or configuration as a credential source or fallback.
- **FR-004**: The system MUST resolve "the active token set" through a single shared code path
  used by both server-startup scope checking and the worker's token provider; the previously
  duplicated environment-seed logic MUST be removed.
- **FR-005**: The system MUST refresh an expired/near-expiry access token using the app client
  credentials and the stored refresh token, persisting the rotated tokens back to the single
  store.
- **FR-006**: The configuration surface (settings model and shipped `.env` template) MUST NOT
  include Strava access-token, refresh-token, token-expiry, or token-scope fields; these four
  fields and both environment-seed readers MUST be deleted, not merely deprecated.
- **FR-007**: When no usable token record exists, `serve` MUST exit with a concrete instruction
  to run the authorization command (preserving today's actionable-failure UX).
- **FR-008**: The app client credentials (client id and secret) MUST remain configurable via the
  environment/configuration, as they are still required to run authorization and to refresh
  tokens.
- **FR-009**: Operator-facing documentation (README, configuration template, and the
  constitution's "Secrets" clause, which currently sanctions the `.env` seed) MUST be updated to
  describe the single-store model.

### Key Entities *(include if feature involves data)*

- **Token Record**: the single persisted Strava credential set — access token, refresh token,
  expiry time, and granted scope — stored in the local database. The one and only source of
  truth for credentials at runtime.
- **App Client Credentials**: the Strava application id and secret, supplied via configuration.
  Used solely to perform the authorization flow and to refresh tokens; never themselves a token.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: There is exactly **one** storage location for tokens and exactly **one** function
  that resolves the active token set (verifiable by code inspection and tests covering both
  startup and worker usage).
- **SC-002**: In a default install, **zero** Strava token secrets appear in any configuration
  file, resolved environment, or container configuration dump.
- **SC-003**: A fresh install reaches a serving state through a single command sequence
  (authorize, then serve) with **no** manual editing of token values.
- **SC-004**: The configuration surface is reduced by the **four** token seed fields with no loss
  of functionality (authorization and refresh still work end to end).
- **SC-005**: The number of independent code paths that map external input to an active token set
  drops from **two to one**.

## Assumptions

- **Existing installations are out of scope.** No migration, upgrade-compatibility, or
  deprecation behavior is designed; the seed and its config fields are deleted outright.
- The one-time authorization flow is the sole bootstrap path. It already falls back to printing
  an authorization URL when no browser can be opened, covering headless-but-interactive cases;
  moving an install to a new host is done by copying the database file, not by configuring
  tokens.
- The configuration loader ignores unknown keys, so a developer's pre-existing `.env` that still
  lists the removed token fields will not error on load — but supporting that is not a goal.
- Removing the environment seed is a governance-relevant change because the project constitution
  currently states "`.env` only seeds the initial run"; this feature therefore **depends on** a
  constitution amendment to the Secrets clause, made in the same change.
- Read-only scope requirements and the loopback-only transport are unchanged by this feature.
