# Sprint 2 Code Review Report

**Date:** 2026-05-25
**Branch:** `feat/sprint-2-hill-detection`
**Reviewer:** Claude Sonnet 4.6
**Plan reference:** `docs/sprint-2-plan.md`

---

## Verdict Summary

The implementation is largely faithful to the plan and mechanically correct. No crashes, no data-loss paths, no new external dependencies introduced. Four issues warrant attention before merging: one outright rule violation, two functional gaps in test coverage, and one piece of dead code that could mislead future readers.

---

## Findings

### F-1 — Hardcoded timeout in `overpass.py` — HIGH

**File:** `app/services/overpass.py:63`

```python
response = await client.get(
    OVERPASS_URL,
    params={"data": query},
    timeout=180.0,       # ← hardcoded
)
```

The Sprint 2 plan fixed the hardcoded `15.0` in `main.py` and `elevation.py`. CLAUDE.md states explicitly: *"No hardcoded timeouts. All timeout values must come from environment variables."* `overpass.py` was left with `180.0`. Sprint 2 didn't create this, but it also didn't fix it, and it should have been caught given that the plan's stated purpose was to sweep for hardcoded timeouts.

**Fix:** Add a separate `OVERPASS_TIMEOUT_S` env var (defaulting to `180`) to `overpass.py`, `.env.example`, and the CLAUDE.md env vars table — same pattern as `ORS_TIMEOUT_S`.

---

### F-2 — `way_id` and `way_segment_index` are never asserted in any test — MEDIUM

Both new fields are added to `HillSegment` and populated correctly, but no test verifies their values.

- `_OVERPASS_ONE_WAY_4NODES` sets `"id": 1001`, and `test_get_hills_one_way_two_segments` is the natural place to assert `results[0]["way_id"] == 1001` and that `{results[0]["way_segment_index"], results[1]["way_segment_index"]} == {0, 1}`.
- The pre-existing `_OVERPASS_TWO_WAYS` fixture has no `"id"` field, so `way_id` is always `None` in those responses. The serialisation path for a non-null `way_id` is exercised only in Sprint 2 fixtures but never asserted.

**Fix:** Add value assertions for both fields in `test_get_hills_one_way_two_segments`.

---

### F-3 — `length_m == 0.0` guard in router is dead code — LOW

**File:** `app/routers/hills.py:94–96`

```python
length_m = compute_total_length_m(seg_coords)
if length_m == 0.0:
    continue
```

`split_into_climbing_segments` only emits a segment when `run_length_m >= _MIN_SEGMENT_LENGTH_M` (default 50 m). A segment emitted by that function cannot have `compute_total_length_m` return `0.0` unless every retained node pair has zero distance — but zero-distance pairs produce `pair_grade = 0.0`, which breaks any active run before emission. The guard can never be true for segments produced by `split_into_climbing_segments`. Leaving it causes future readers to wonder what edge case it is protecting against.

**Fix:** Remove the guard, or replace it with an explicit `assert` or comment explaining it is an unreachable safety net.

---

### F-4 — Stale comment in `test_get_hills_zero_length_way_excluded` — LOW

**File:** `tests/test_api.py:312`

```python
# Two coincident coordinates → length_m = 0 → filtered out by router
```

This describes the Sprint 1 filtering path. Under the Sprint 2 implementation, coincident nodes produce `pair_grade = 0.0`, so `split_into_climbing_segments` returns `[]` and the `logger.debug("No climbing segments found...")` branch fires. The router's `length_m == 0.0` guard (dead code per F-3) is never reached. The test outcome is correct; the explanation is wrong.

**Fix:** Update the comment to reflect the actual code path.

---

### F-5 — README not updated — MEDIUM

**File:** `README.md`

Sprint 2 added two new query parameters, two new response fields, and three new environment variables. None of them appear in the README. Specifically:

- API table is missing `min_grade_pct` and `surface` parameters.
- Example response JSON is missing `way_id` and `way_segment_index` fields.
- Setup section has no mention of `ORS_TIMEOUT_S`, `HILLFINDER_FLAT_THRESHOLD_PCT`, or `HILLFINDER_MIN_SEGMENT_M`.

The root cause is structural: the plan's "Files modified" table never listed `README.md`, so it was not treated as a deliverable.

**Fix:** Update the API table, example response, and add an environment variables section to the README.

---

### F-6 — Pre-existing chunking edge case in `elevation.py` — MEDIUM (not Sprint 2, backlog)

**File:** `app/services/elevation.py:20–28`

```python
if end >= len(coordinates) or len(coordinates) - end <= 1:
    chunks.append(coordinates[start:])
    break
```

For exactly 501 coordinates: `end = 500`, `len - end = 1 ≤ 1`, so the condition fires and all 501 points are placed in a single chunk — exceeding ORS's 500-point hard limit. This is a pre-existing Sprint 1 bug. Sprint 2 added no regression, but it also did not catch it. All Sprint 2 test fixtures use ≤ 4 nodes, so the branch remains unexercised.

**Fix (backlog):** Add a regression test in `tests/test_elevation.py` for a 501-coordinate input that asserts two chunks are produced.

---

## What Is Correct

| Area | Status |
|---|---|
| `ORS_TIMEOUT_S` in `main.py` | ✓ |
| `ORS_TIMEOUT_S` in `elevation.py` | ✓ |
| `split_into_climbing_segments` algorithm matches spec | ✓ |
| Zero-distance pair → grade 0.0 → run break | ✓ |
| Threshold strictly `>` (not `>=`) | ✓ |
| `run_length_m` accumulator resets on run close | ✓ |
| `way_id` added to `overpass.py` returned dict | ✓ |
| `HillSegment.way_id` and `way_segment_index` fields | ✓ |
| `min_grade_pct` / `surface` query params with validation constraints | ✓ |
| Per-segment error isolation (`logger.warning + continue`) | ✓ |
| Filter values included in entry log line | ✓ |
| Final log line updated to include way count | ✓ |
| All 10 unit tests in `test_geo.py` match plan spec | ✓ |
| Updated `test_get_hills_full_pipeline_returns_sorted_results` | ✓ |
| All 9 integration tests from plan present | ✓ |
| Boundary test (`>=` semantics) implemented per plan | ✓ |
| `.env.example` — all 3 new vars present | ✓ |
| CLAUDE.md env var table updated | ✓ |
| CLAUDE.md noise-sensitivity note present | ✓ |
| No secrets logged; API key absent from responses | ✓ |
| Input validation: `min_length=1`, `ge=0.0`, `le=100.0` | ✓ |

---

## Action Items

| Priority | Item |
|---|---|
| HIGH | Add `OVERPASS_TIMEOUT_S` env var to `overpass.py`, `.env.example`, and CLAUDE.md (F-1) |
| MEDIUM | Assert `way_id` and `way_segment_index` values in `test_get_hills_one_way_two_segments` (F-2) |
| LOW | Remove or annotate the dead `length_m == 0.0` guard in `hills.py` (F-3) |
| LOW | Fix stale comment in `test_get_hills_zero_length_way_excluded` (F-4) |
| MEDIUM | Update README: add `min_grade_pct`/`surface` params, `way_id`/`way_segment_index` response fields, and env vars section (F-5) |
| BACKLOG | Add regression test for 501-coordinate chunking edge case in `test_elevation.py` (F-6) |
