# Sprint 2 Research — Segment Calculation & API Filters

**Date:** 2026-05-25
**Sprint:** 2 — Hill Detection Logic
**Scope:** Best practices for climbing-segment calculation and query-parameter filtering; common mistakes to avoid.

---

## 1. Segment Calculation Best Practices

### 1.1 Smooth elevation data before segmenting

Raw elevation APIs return noisy values. A 1 m vertical spike over 2 m horizontal distance produces a 50% grade that is an artifact, not a real climb. Applying a light smoothing pass (e.g., a 3-point rolling mean) before the segmentation walk reduces false segment boundaries and spurious short runs.

**Relevance to Sprint 2:** `split_into_climbing_segments()` will receive raw ORS elevation data. If the API returns noisy values, the `_FLAT_GRADE_THRESHOLD_PCT = 1.0` guard may not be enough on its own. Consider a post-elevation-fetch smoothing step in `elevation.py`, or at minimum document the noise sensitivity in `CLAUDE.md`.

### 1.2 Use hysteresis (dual threshold) instead of a single cutoff

A single threshold of `> 1.0%` causes oscillation: a run that alternates between 0.9% and 1.1% pairs will be chopped into many 1-pair fragments rather than recognised as a continuous climb. Hysteresis uses two thresholds — enter a run at `> start_threshold`, stay in it until `< stop_threshold` — to produce stable, noise-tolerant boundaries.

```
start_threshold = 1.5%   # pair must exceed this to open a new run
stop_threshold  = 0.5%   # pair must fall below this to close the run
```

**Relevance:** The current plan uses a single `_FLAT_GRADE_THRESHOLD_PCT`. This is a known simplification. It works well for clean elevation data but may produce fragmented segments on roads with minor undulations. Flagging this as a potential follow-up (Sprint 3) is advisable.

### 1.3 Preserve contiguous node coverage — never leave gaps

Every node in the input must be the start of exactly one potential run. The Sprint 2 algorithm handles this correctly: when a pair falls below threshold the closed run's last node becomes the `run_coords[0]` of the next candidate run. Verify that zero-distance pairs (coincident nodes) also restart the accumulator from the current node rather than skipping it.

### 1.4 Apply the minimum-length check at run closure, not per pair

Checking length pair-by-pair would discard a long climb that happens to start with a short step. Checking at closure (after accumulating all qualifying pairs) is the correct approach — and matches the Sprint 2 algorithm.

### 1.5 Validate inputs strictly at the function boundary

`split_into_climbing_segments()` takes two parallel lists. The `ValueError` on length mismatch should fire before any iteration. A fence-post error — `len(coords) == 1` reaching the loop without error — is easy to introduce; the `< 2` guard must come before the loop.

### 1.6 Round distances and grades consistently

`compute_total_length_m()` rounds to 2 decimal places. The segment function calls this for the min-length check. Confirm that a segment of exactly `50.00 m` passes the `>= _MIN_SEGMENT_LENGTH_M` guard — it does, since `>=` is inclusive. Had the plan used `>`, the boundary test `test_split_exactly_at_min_length` would fail by design.

### 1.7 Document the grade formula clearly

The current formula counts **only uphill gain** in the numerator (`avg = total_gain / total_distance`). After Sprint 2 the denominator is the **total length of the climbing run** (all pairs, uphill and flat-within-run). This means a run with one steep pair and several moderate pairs will show a lower `avg_grade` than that steep pair alone. Make sure `HillSegment.grade_avg_pct` docs reflect this.

---

## 2. API Filter Best Practices

### 2.1 Declare constraints in the `Query()` object, not application logic

FastAPI generates a 422 response automatically when a `Query(ge=0.0, le=100.0)` constraint is violated. This is better than a manual `if min_grade_pct > 100: raise HTTPException(400)` for two reasons: it is captured in the OpenAPI schema (visible in Swagger UI), and the error format is consistent with all other validation errors. The Sprint 2 plan uses `Query(ge=0.0, le=100.0)` correctly.

### 2.2 Use `Literal` for string enums

`Literal["road", "trail", "unknown"] | None` gives both compile-time type safety and runtime 422 validation for free. Avoid accepting a raw `str` and validating inside the handler — it pushes validation past the framework boundary.

### 2.3 Filter before the sort, not after

Filtering after sorting is correct for results but wastes cycles if the filtered set is small. More importantly, the `results.sort()` call should operate on the already-filtered list. The Sprint 2 plan keeps the sort at the end of the loop, which is correct.

### 2.4 Apply the surface filter as early as possible

The surface filter in Sprint 2 is applied at the top of the per-way loop before `split_into_climbing_segments()` is called. This is the right layer — it avoids splitting a way into segments only to discard all of them. Elevation data is fetched for all ways at once (upstream of the loop), so the filter cannot move further up the stack without restructuring the elevation call.

### 2.5 Default values should reflect the typical use case

`min_grade_pct=3.0` matches typical "interesting hill" perception. `surface=None` (return all surfaces) is the safe default. Both are correct choices that avoid surprising users with empty results.

### 2.6 Expose applied filters in logs for debuggability

Add the active filter values to the entry-level log line:

```python
logger.info(
    "GET /hills/ address=%r radius_m=%d min_grade_pct=%.1f surface=%r",
    address, radius_m, min_grade_pct, surface,
)
```

This makes it immediately clear from logs why a response returned 0 results.

### 2.7 Document AND vs. OR semantics explicitly

Multiple filters are always AND in the Sprint 2 design (surface AND min_grade). This should be stated in the endpoint docstring or OpenAPI description so callers don't assume OR.

---

## 3. Common Mistakes When Building API Filters

### 3.1 Silent filter mismatch (wrong field name)

**Mistake:** Filtering on `way["surface_type"]` when the dict key is `"surface"`. The filter silently passes all or no items instead of raising an error.

**Prevention:** Access dict keys via a typed dataclass or a helper that raises `KeyError` loudly. At minimum, add a test that exercises the surface filter with each valid value.

### 3.2 Float comparison on threshold values

**Mistake:** Using `avg_grade < min_grade_pct` where both are floats derived from rounded intermediate computations. A segment with a computed grade of `2.9999999...` will be excluded when `min_grade_pct=3.0`, even though the true grade is 3%.

**Prevention:** Round `avg_grade` before comparison (already done — `compute_grades()` returns `round(..., 2)`). The Sprint 2 code is safe as long as the rounding step is not removed.

### 3.3 Filtering at the wrong layer

**Mistake:** Pushing filter logic into the service or data-fetch layer (e.g., adding `surface=road` to the Overpass query). This optimises one filter but breaks composability when the caller wants `surface=None`.

**Prevention:** Keep filters in the router. Let services fetch the full raw dataset and let the router apply business-level filtering. The Sprint 2 design does this correctly.

### 3.4 Not testing the boundary value of a range filter

**Mistake:** Testing `min_grade_pct=5` returns segments with grade > 5 and `min_grade_pct=20` returns none, but never testing that a segment with exactly `min_grade_pct=X` is included. The `>=` vs `>` distinction matters.

**Prevention:** The Sprint 2 test matrix includes `min_grade_pct=15` against a segment with grade ≈ 18%. Add a test where the segment grade equals the filter exactly to pin the boundary.

### 3.5 Returning 400 instead of 422 for validation errors

**Mistake:** Raising `HTTPException(400, "min_grade_pct must be between 0 and 100")` inside the handler. FastAPI's `Query` constraints produce 422 with a structured body; a manual 400 inside the handler is inconsistent and not reflected in the OpenAPI schema.

**Prevention:** Always put range and type constraints in `Query()`, not in handler logic. The Sprint 2 plan already does this; the `test_get_hills_min_grade_invalid_422` test validates it.

### 3.6 Missing or ambiguous None handling for optional filters

**Mistake:** `if surface != None` (using `!=` instead of `is not`). For `Literal` types this is not a problem, but `surface` could be the string `"None"` if the caller passes `?surface=None`. FastAPI will reject that as a 422 (not a valid Literal value), which is correct — but document it so callers know to omit the param entirely rather than passing `null`.

**Prevention:** The `| None = Query(default=None)` pattern is idiomatic. The `is not None` check in the loop body is correct.

### 3.7 Forgetting to update the OpenAPI description when filters change defaults

**Mistake:** Changing `min_grade_pct` default from `3.0` to `5.0` in code but not updating the docstring, README, or CLAUDE.md. Callers relying on the documented default get surprising results.

**Prevention:** Whenever a filter default changes, update the Environment variables table in `CLAUDE.md` and the endpoint docstring in the same commit.

### 3.8 O(n²) complexity from naive filter ordering

**Mistake:** Running the surface filter inside the inner segment loop rather than at the outer way loop:

```python
# Bad: calls split_into_climbing_segments for every way, then discards filtered ones
for way, ... in ...:
    for seg in split_into_climbing_segments(...):
        if surface is not None and way["surface"] != surface:
            continue
```

**Prevention:** Check the surface filter at the top of the outer way loop, before `split_into_climbing_segments()` is called. The Sprint 2 plan does this correctly.

---

## 4. Sprint 2 Plan — Assessment

### Strengths

- The `split_into_climbing_segments()` algorithm is gap-free (no lost nodes), handles coincident points (grade = 0.0 → breaks run), and applies the min-length check at closure.
- `Query(ge=0.0, le=100.0)` for `min_grade_pct` is the correct place to enforce range constraints.
- Surface filter fires before segment splitting — best possible layer for efficiency.
- `test_get_hills_min_grade_invalid_422` explicitly tests the 422 path.
- B-2 fix (skip bad way instead of 500) is addressed in Task 2.
- `ORS_TIMEOUT_S` env var satisfies the no-hardcoded-timeouts rule from `CLAUDE.md`.

### Risks & Recommendations

| # | Risk | Recommendation |
|---|---|---|
| R-1 | Elevation noise may fragment runs at the 1% threshold | Consider a 3-point rolling average after `get_elevations()` returns, or note the noise sensitivity in CLAUDE.md and plan for Sprint 3 |
| R-2 | No test pins the `avg_grade == min_grade_pct` boundary | Add a test where segment grade exactly equals the filter to confirm `>=` semantics |
| R-3 | Log line at entry does not include active filter values | Add `min_grade_pct` and `surface` to the INFO log in Task 4 |
| R-4 | `way_segment_index` default is `0`, not `None` | A way with one segment will show `way_segment_index=0`, which is correct but may confuse callers who expect it only when there are multiple segments — document this in the model |
| R-5 | Surface tests use a 2-way fixture with both road and trail; if grade computation fails for one way, the test may pass for the wrong reason | Guard the fixture so both ways have valid elevation data and grades above 3% |
