# Quickstart / Validation: Hide Empty (All-Zero) Stream Charts

Validates that all-zero stream charts are suppressed while genuinely-populated
charts (including partial-zero and constant-non-zero) still render. Display-only;
no DB or sync changes.

## Prerequisites

- Repo checked out on branch `004-hide-empty-stream-charts`.
- `uv` installed; dependencies synced (`uv sync`).
- The existing local mirror at `./.database/strava.db` (used only by the manual
  end-to-end check; the unit tests are self-contained).

## 1. Automated unit tests (primary gate)

Run the chart-builder unit tests:

```bash
uv run pytest tests/dashboard/test_charts.py -q
```

**Expected**: all pass, including the new cases —
- an all-zero `altitude` stream produces **no** chart;
- an all-zero `grade_smooth` stream produces **no** chart;
- a `cadence` stream mixing zeros and non-zero values **is** plotted;
- a constant non-zero stream (e.g. existing `heartrate = [130]*n`) **is** plotted;
- when every plottable stream is all-zero, `build_activity_charts` returns `[]`.

Full suite + static gates (constitution Definition of Done):

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy strava_mcp
```

**Expected**: green; no new lint/type findings.

## 2. Manual end-to-end check (optional, against the real mirror)

Serve the dashboard and compare an indoor vs. outdoor activity:

```bash
uv run strava-mcp serve   # or the dashboard entrypoint used in this project
```

- Open an **indoor / no-GPS** activity whose stored `altitude` and `grade_smooth`
  are entirely zero (e.g. a WeightTraining or pool Swim — see spec for act
  `11704713320`). **Expected**: no Elevation and no Grade chart; Heart rate (and
  any present speed/cadence/temp) still shown.
- Open an **outdoor** activity (e.g. a Run or outdoor Ride with real elevation).
  **Expected**: Elevation and Grade charts still render unchanged.
- Open an activity whose only plottable streams happen to be all-zero. **Expected**:
  the Streams section shows "No stream data for this activity."

## 3. Success criteria mapping

| Check | Spec criterion |
|-------|----------------|
| All-zero `altitude`/`grade_smooth` charts gone | SC-001 |
| Non-zero charts unchanged (count preserved)    | SC-002 |
| No flat-at-zero chart remains anywhere         | SC-003 |
| All-zero-only activity shows fallback message  | SC-004 |

## Notes

- No migration, no `streams_json` change, no MCP tool contract change — rolling
  back is reverting the `charts.py` diff.
- See [contracts/chart-builder.md](./contracts/chart-builder.md) for the full
  behavioral contract and [data-model.md](./data-model.md) for the visibility rule.
