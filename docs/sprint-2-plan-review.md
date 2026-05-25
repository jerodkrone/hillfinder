# Sprint 2 Plan Review

**Reviewed by:** Claude Code (architect pass)
**Date:** 2026-05-25
**Plan reviewed:** `docs/sprint-2-plan.md`
**Source files read:** `hill-finder/app/main.py`, `app/routers/hills.py`, `app/utils/geo.py`, `app/models/hill.py`, `app/services/elevation.py`, `tests/test_api.py`, `tests/test_geo.py`

---

## Summary

The plan is largely sound. The algorithm is correct, the filter design is idiomatic FastAPI, and the test matrix is thorough. Three findings require attention before implementation; the rest are minor inconsistencies or documentation gaps.

---

## Findings

### F-1 — CRITICAL: `elevation.py` has its own hardcoded timeout that Task 1 does not fix

**File:** `hill-finder/app/services/elevation.py`, line 9
```python
ORS_TIMEOUT = 15.0  # hardcoded
```
This constant is passed directly to each `client.post(..., timeout=ORS_TIMEOUT)` call on line 59. In httpx, a **per-request timeout overrides the client-level timeout**. This means:

- Task 1 fixes `main.py` to read `ORS_TIMEOUT_S` from env and sets the *client-level* timeout.
- But `elevation.py`'s per-request `timeout=ORS_TIMEOUT` silently overrides that client setting on every elevation call.
- After Sprint 2, setting `ORS_TIMEOUT_S=30` in env will appear to work (the client is constructed with 30s) but all elevation calls will still time out at 15s.

**Impact:** The CLAUDE.md "No hardcoded timeouts" rule remains violated after Sprint 2. `ORS_TIMEOUT_S` must also replace `ORS_TIMEOUT` in `elevation.py`, or the env var is effectively a no-op for the only service that actually hits ORS.

---

### F-2 — WILL CAUSE CONFUSION: Task 2 (B-2 fix) is made dead by Task 4

Task 2 says to change the `except ValueError` block in `hills.py` (lines 62–64) from `raise HTTPException(500)` to `logger.warning + continue`. Task 4 then **replaces the entire per-way loop** — including that same `except ValueError` block — with the new segmented loop that already incorporates the same `logger.warning + continue` pattern.

If an implementor applies Task 2 first and then Task 4, they touch the same code block twice. The diff will be confusing and any code review will question why Task 2 exists. More critically, if they apply Task 2 but forget Task 4's changes fully, the B-2 fix is there but the segmentation logic isn't.

**Recommendation:** Remove Task 2 as a standalone step. Add a note in Task 4 that it subsumes the B-2 fix. The two-pass edit creates unnecessary churn.

---

### F-3 — LOGICAL GAP: `way_segment_index` is not useful for unnamed ways

`way_segment_index` lets callers identify "Steep Hill Road, segment 0 vs. segment 1." That works when `name` is not null. But OSM has many unnamed roads (`name: null`). Two different unnamed ways can both emit `{name: null, way_segment_index: 0}` — and callers cannot distinguish them.

The field is useful, but without a stable `way_id` (e.g., the OSM element ID, which Overpass already returns in the `id` field) it only works for named ways. If the Sprint 2 goal is to help callers identify which run within a way they are looking at, the model needs either an OSM `way_id` field or the `way_segment_index` should be `None` when the way produced only one segment (as the original plan comment suggests, but then contradicts with "always populated").

This is a design decision, not an implementation bug — but the current plan leaves it ambiguous.

---

### F-4 — TEST COUNT MISMATCH: 8 vs 9 integration tests

The **Deliverables** section says "9 new integration tests." The **Task 6** section heading says "(8 tests)." The table in Task 6 lists 9 tests (including `test_get_hills_min_grade_boundary`). Whoever implements will count 9 and the heading will be wrong — minor, but will cause "wait, is the plan correct?" friction.

---

### F-5 — IMPLEMENTATION GAP: `test_get_hills_min_grade_boundary` is underspecified

The test is described as: "`min_grade_pct` set to exactly the segment's rounded `avg_grade`." The shared 4-node fixture has two segments with grades of approximately 18% and 13.5%, but the *exact* values depend on the geodesic distance between specific lat/lon pairs, which varies slightly from the `111 m per 0.001°` approximation.

The test author needs to either:
- Hard-code the grade value (requires knowing the exact `compute_grades()` output for the fixture), or
- Call the endpoint without a filter, read `grade_avg_pct` from the response, and use that value as the filter in a second call.

The plan does not specify which approach to use. An implementor who guesses the grade value wrong will write a test that doesn't actually pin the `>=` boundary — it will pass for other reasons.

---

### F-6 — MINOR: O(n) redundant distance computation at run closure

`split_into_climbing_segments()` already computes `compute_distance_m(coordinates[i], coordinates[i+1])` for each pair during the walk. At run closure it calls `compute_total_length_m(run_coords)`, which iterates all pairs in the run *again* to sum the same distances.

At the 500-node ceiling this is not a performance problem. But it is an inconsistency: the function has all the information it needs to maintain a `run_length_m` accumulator as it walks, which would eliminate the re-scan. Worth a note so future work (e.g., hysteresis in Sprint 3) doesn't inherit this pattern.

---

### F-7 — MINOR: Zero-length way debug log is silently dropped

The current router has:
```python
logger.debug("Skipping zero-length way: %r", way.get("name"))
```
The plan replaces the per-way loop entirely (Task 4) but never mentions this log line. With the new logic, zero-length ways produce no segments from `split_into_climbing_segments()` (grade = 0.0 → no uphill pairs), so they are silently excluded without any log message. The `test_get_hills_zero_length_way_excluded` test will still pass, but the observability regression (no debug signal for a skipped way) is unintentional.

---

## What the Plan Gets Right

- The algorithm is gap-free: every node is the start of exactly one potential run. Coincident nodes produce grade 0.0 and correctly break any active run.
- `Query(ge=0.0, le=100.0)` for `min_grade_pct` is the right layer for constraint enforcement. The 422 test validates this correctly.
- Surface filter fires before `split_into_climbing_segments()` — the most efficient placement given that elevation data is already fetched for all ways upstream.
- `avg_grade < min_grade_pct` using a value already rounded to 2 decimal places avoids float comparison surprises (Research doc Section 3.2).
- Elevation noise sensitivity is acknowledged and deferred cleanly to Sprint 3 with a documented tuning lever.
- B-2 (ValueError → 500) is fixed, but see F-2 above about the two-pass redundancy.

---

## Pre-Implementation Checklist

| # | Action required before writing code |
|---|---|
| F-1 | Extend Task 1 scope: also move `ORS_TIMEOUT` in `elevation.py` to the `ORS_TIMEOUT_S` env var |
| F-2 | Remove Task 2 as a standalone step; absorb B-2 fix note into Task 4 description |
| F-3 | Decide: add `way_id` (OSM element ID) to `HillSegment`, or document the unnamed-way limitation explicitly |
| F-4 | Fix "(8 tests)" heading in Task 6 to "(9 tests)" |
| F-5 | Specify how `test_get_hills_min_grade_boundary` derives its filter value |
| F-6 | Optional: accumulate `run_length_m` during the walk to avoid re-scan (low priority) |
| F-7 | Decide whether to preserve a debug log for ways that produce no climbing segments |
