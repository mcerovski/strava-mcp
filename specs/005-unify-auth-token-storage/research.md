# Phase 0 Research: Unify Auth Token Storage

No open `NEEDS CLARIFICATION` items remain (both were resolved during `/speckit-specify`:
auth-only, DB-only, existing installs out of scope). The "research" here records the design
decisions that shape the deletion so implementation is unambiguous.

## Decision 1 — Single source of truth: the DB `tokens` row

**Decision**: The single-row `tokens` table is the only credential store at runtime. No schema
change.

**Rationale**: It is already the source of record once `auth` has run; the seed only ever
mattered before the first auth. Making it the *sole* source removes the dual-storage ambiguity
and the stale-secret risk with zero data-model change.

**Alternatives considered**:
- *Keep an env fallback but de-duplicate it* — rejected: still leaves long-lived plaintext
  secrets in `.env` and a second populate path (fails the spec's primary intent).
- *Move tokens to a dedicated keyring/OS secret store* — rejected: out of scope, adds a
  dependency and a second store; the loopback single-user model already keeps the DB private
  under `.database/`.

## Decision 2 — Single create path: the `auth` OAuth flow

**Decision**: `auth` is the only way tokens enter the store. No `import-tokens` command.

**Rationale**: Simplest possible model and faithful to "without multiple auth processes." The
existing flow already prints the authorization URL when no browser can be opened, so it works on
headless-but-interactive hosts. Host-to-host moves are done by copying the DB file (which carries
the tokens), not by re-seeding.

**Alternatives considered**:
- *Add a one-time `import-tokens` CLI* (Q1 option B) — rejected by operator decision in favor of
  the simplest model; can be revisited later if a true non-interactive bootstrap need appears.

## Decision 3 — Single read path: `TokenStore.read()` as the only resolver

**Decision**: Collapse the two fallback readers into the persistence read.
- `TokenStore.current()` becomes `read()`-or-raise (raises the existing actionable
  `RuntimeError("No tokens available; run \`uv run strava-mcp auth\`.")`).
- `mcp/server.py::check_scopes()` reads the DB row directly and maps "no row" →
  "all required scopes missing" (so `serve` prints `run uv run strava-mcp auth` and exits 1).
- Delete `auth/tokens.py::_seed_from_env()` and `mcp/server.py::_seed_tokens()`.

**Rationale**: Both call sites already funnel through `TokenStore`; removing the seed leaves a
single source (`read()`). The worker's `access_token()` keeps using `current()`; `serve`'s
gate keeps its non-raising "missing scopes" semantics. No behavior change except the removed
fallback.

**Alternatives considered**:
- *Route `check_scopes` through `current()` in a try/except* — rejected: `check_scopes` wants a
  non-raising "missing list," and the absent-token case maps cleanly to "all required missing"
  without exception control-flow. Reading the row directly is clearer.

## Decision 4 — Config surface: delete the four token fields

**Decision**: Remove `strava_access_token`, `strava_refresh_token`, `strava_token_expires_at`,
`strava_token_scope` from `Settings` and from `.env.example`. Keep `strava_client_id` /
`strava_client_secret`.

**Rationale**: The fields exist only to feed the seed. With the seed gone they are dead. The
client credentials remain because `auth` and refresh still need them. pydantic-settings'
`extra="ignore"` means a developer's pre-existing `.env` that still lists the removed keys will
not error on load (not a goal, but a harmless side effect).

**Alternatives considered**:
- *Keep the fields but stop reading them* — rejected: leaves a confusing dead config surface and
  invites re-introduction of the bug.

## Decision 5 — Constitution amendment (governance)

**Decision**: Amend the *Secrets* clause from "Tokens persist in the DB after first auth; `.env`
only seeds the initial run." to state that tokens live solely in the DB and `.env` carries only
client credentials. Bump **2.0.0 → 2.1.0** (MINOR — materially tightened guidance; an allowance
removed).

**Rationale**: The current wording explicitly sanctions the seed; the constitution requires
amendments to land in the same change as the behavior they govern.

**Alternatives considered**:
- *PATCH bump* — defensible (no principle removed), but removing a sanctioned mechanism is more
  than a clarification; MINOR is the honest classification. Final call deferred to the
  constitution update step.
