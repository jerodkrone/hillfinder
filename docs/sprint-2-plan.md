# Sprint 2 Plan — Hill Detection Logic

**Date:** 2026-05-25
**Sprint goal:** Upgrade the `GET /hills/` response from one segment per OSM way to one segment per climbing run per way, with filtering by minimum grade and surface type.

> **Revision note (2026-05-25):** Updated after architect review (`docs/sprint-2-plan-review.md`). Changes: Task 1 extended to cover `elevation.py` hardcoded timeout; Task 2 (B-2 partial fix) removed — it was made dead by Task 3's full loop replacement; `way_id` added to `HillSegment` and `overpass.py`; segment-splitting algorithm upgraded to use a length accumulator instead of a re-scan; integration test count corrected; boundary test specified concretely; debug-log preservation noted.

---

## Context

Sprint 1 returned the full length of each OSM way as a single `HillSegment`. A 3 km road containing two 200 m climbs separated by a flat middle section looks identical to a consistently steep road. Sprint 2 fixes this by splitting each way at grade breakpoints, exposing individual climbing runs. Two new query parameters let callers filter by minimum grade and by surface type.

**Sprint 1 bugs addressed in this sprint:**

| ID | Issue | Status |
|---|---|---|
| B-1 | `max_grade` counted descents | Already fixed in Sprint 1 code — no action needed |
| B-2 | `ValueError` in router raises 500 instead of skipping | Fixed by the new per-segment loop in Task 3 |
| B-4 | `address` missing `min_length=1` | Already fixed in Sprint 1 code — no action needed |
| — | Hardcoded `15.0` timeout in `main.py` and `elevation.py` | Fix in Task 1 |

---

## Deliverables

1. `split_into_climbing_segments()` pure function in `geo.py`
2. `min_grade_pct` and `surface` query parameters on `GET /hills/`
3. `way_segment_index` and `way_id` fields on `HillSegment`
4. `ORS_TIMEOUT_S` env var (replaces hardcoded 15 s timeout in `main.py` and `elevation.py`)
5. 10 new unit tests + 9 new integration tests; 1 existing test updated

---

## Implementation Tasks

### Task 1 — Move hardcoded timeouts to `ORS_TIMEOUT_S` env var

**Files:** `hill-finder/app/main.py` and `hill-finder/app/services/elevation.py`

Both files contain a hardcoded `15.0` second timeout. In httpx, per-request timeouts override client-level timeouts, so `elevation.py`'s constant would silently override the client setting even after fixing `main.py` alone. Both must read from the same env var.

**`app/main.py`** — add a module-level constant and use it in the lifespan client:

```python
_HTTP_TIMEOUT_S = float(os.getenv("ORS_TIMEOUT_S", "15"))

@asynccontextmanager
async def lifespan(app: FastAPI):
    ...
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
```

`os` is already imported in `main.py`.

**`app/services/elevation.py`** — replace the hardcoded module constant with an env-backed one:

```python
import os

# was: ORS_TIMEOUT = 15.0
ORS_TIMEOUT = float(os.getenv("ORS_TIMEOUT_S", "15"))
```

The rest of `elevation.py` already uses `ORS_TIMEOUT` by name, so no other changes are needed in that file.

---

### Task 2 — Implement `split_into_climbing_segments()` in `geo.py`

**File:** `hill-finder/app/utils/geo.py`

#### New constants (module-level, env-configurable)

```python
import os

_FLAT_GRADE_THRESHOLD_PCT = float(os.getenv("HILLFINDER_FLAT_THRESHOLD_PCT", "1.0"))
_MIN_SEGMENT_LENGTH_M = float(os.getenv("HILLFINDER_MIN_SEGMENT_M", "50.0"))
```

#### Function signature

```python
def split_into_climbing_segments(
    coordinates: list[tuple[float, float]],
    elevations: list[float],
) -> list[tuple[list[tuple[float, float]], list[float]]]:
```

Returns a list of `(coord_slice, elevation_slice)` tuples. Each slice has ≥ 2 nodes and covers a continuous uphill run of ≥ `_MIN_SEGMENT_LENGTH_M`. Returns `[]` if no qualifying runs exist. Raises `ValueError` on mismatched lengths or fewer than 2 input points.

#### Algorithm

Walk consecutive node pairs. Accumulate a "current run" while `pair_grade > _FLAT_GRADE_THRESHOLD_PCT`. When a pair falls at or below the threshold, close the current run (emit if long enough), then start a fresh run from that node — no gap between runs.

A `run_length_m` accumulator is maintained during the walk so the minimum-length check at run closure does not require re-scanning all accumulated pairs.

```
validate: same length, >= 2 points

run_coords   = [coordinates[0]]
run_elevs    = [elevations[0]]
run_length_m = 0.0
results      = []

for i in range(len(coordinates) - 1):
    dist       = compute_distance_m(coordinates[i], coordinates[i+1])
    elev_diff  = elevations[i+1] - elevations[i]
    pair_grade = (elev_diff / dist * 100) if dist > 0 else 0.0

    if pair_grade > _FLAT_GRADE_THRESHOLD_PCT:
        run_coords.append(coordinates[i+1])
        run_elevs.append(elevations[i+1])
        run_length_m += dist
    else:
        if len(run_coords) >= 2 and run_length_m >= _MIN_SEGMENT_LENGTH_M:
            results.append((list(run_coords), list(run_elevs)))
        run_coords   = [coordinates[i+1]]
        run_elevs    = [elevations[i+1]]
        run_length_m = 0.0

# close final run
if len(run_coords) >= 2 and run_length_m >= _MIN_SEGMENT_LENGTH_M:
    results.append((list(run_coords), list(run_elevs)))

return results
```

**Key invariants:**
- Zero-distance pairs (coincident nodes) → grade = 0.0 → break any active run.
- Threshold is strictly `>` (a pair at exactly 1.0% is flat).
- `run_length_m` accumulates only pairs whose grade exceeds the threshold; it resets to 0.0 when a run closes.
- The min-length check happens at run closure, not pair-by-pair.

---

### Task 3 — Update `app/routers/hills.py`

This task replaces the entire per-way loop. It also incorporates the B-2 bug fix (ValueError → 500 was in the old loop and is gone). The new loop wraps both `split_into_climbing_segments()` and `compute_grades()` with `logger.warning + continue` so one malformed way never fails the entire request.

#### New imports

```python
from typing import Literal
from app.utils.geo import compute_grades, compute_total_length_m, split_into_climbing_segments
```

#### New query parameters

```python
async def get_hills(
    ...
    min_grade_pct: float = Query(default=3.0, ge=0.0, le=100.0),
    surface: Literal["road", "trail", "unknown"] | None = Query(default=None),
):
```

#### Replace the per-way loop (currently lines 57–80)

```python
results = []
for way, (start, end) in zip(ways, way_slices):
    if surface is not None and way["surface"] != surface:
        continue

    coords = way["coordinates"]
    elevations = all_elevations[start:end]

    try:
        climbing_runs = split_into_climbing_segments(coords, elevations)
    except ValueError as exc:
        logger.warning("Segment split failed for way %r: %s", way.get("name"), exc)
        continue

    if not climbing_runs:
        logger.debug("No climbing segments found for way %r", way.get("name"))
        continue

    for seg_index, (seg_coords, seg_elevs) in enumerate(climbing_runs):
        try:
            avg_grade, max_grade = compute_grades(seg_coords, seg_elevs)
        except ValueError as exc:
            logger.warning(
                "Grade compute failed for segment %d of way %r: %s",
                seg_index, way.get("name"), exc,
            )
            continue

        if avg_grade < min_grade_pct:
            continue

        length_m = compute_total_length_m(seg_coords)
        if length_m == 0.0:
            continue

        results.append(HillSegment(
            name=way["name"],
            way_id=way["way_id"],
            grade_avg_pct=avg_grade,
            grade_max_pct=max_grade,
            length_m=length_m,
            surface=way["surface"],
            coordinates=seg_coords,
            way_segment_index=seg_index,
        ))
```

The `logger.debug("No climbing segments found for way %r", ...)` line preserves the observability of the old zero-length-way debug log — now it covers all ways that produce no output (flat, too short, or zero-length).

Update the entry log line to include active filter values (aids debugging empty results):
```python
logger.info(
    "GET /hills/ address=%r radius_m=%d min_grade_pct=%.1f surface=%r",
    address, radius_m, min_grade_pct, surface,
)
```

Update the final log line:
```python
logger.info("Returning %d segments (from %d ways) for address=%r", len(results), len(ways), address)
```

---

### Task 4 — Update `HillSegment` and `overpass.py`

#### `app/models/hill.py`

Add `way_id` and `way_segment_index`:

```python
class HillSegment(BaseModel):
    name: str | None = None
    way_id: int | None = None          # OSM element ID; None only if Overpass omits it
    grade_avg_pct: float
    grade_max_pct: float
    length_m: float
    surface: Literal["road", "trail", "unknown"]
    coordinates: list[tuple[float, float]]
    way_segment_index: int = 0         # 0-based index within this way; always present
```

`way_id` allows callers to group segments that belong to the same OSM way even when `name` is `None`. `way_segment_index` is always populated — a way that produces a single segment emits `way_segment_index=0`, not `None`.

#### `app/services/overpass.py`

Include the OSM element ID in the returned dict (line ~89 in the current file, in the `for element in data.get("elements", []):` loop):

```python
ways.append({
    "name": tags.get("name"),
    "way_id": element.get("id"),       # OSM element ID (int); present for all ways
    "surface": _classify_surface(tags),
    "coordinates": coords,
})
```

---

### Task 5 — Tests

#### Update existing test

**`test_get_hills_full_pipeline_returns_sorted_results`** (`tests/test_api.py`)

"Flat Road" in `_OVERPASS_TWO_WAYS` has 0 → 1 m gain over ~111 m (≈ 0.9% grade), which is below both the 1.0% flat threshold and the 3.0% default `min_grade_pct`. It will produce no climbing segments. Update:

```python
# Before:
assert len(results) == 2

# After:
assert len(results) == 1
assert results[0]["name"] == "Steep Hill"
```

#### New unit tests — `tests/test_geo.py` (10 tests)

Use `(40.0, -75.0)` as base; 0.001° lat steps ≈ 111 m each.

| Test | Input shape | Expected output |
|---|---|---|
| `test_split_single_uphill_run` | 3 nodes all uphill (~18% grade) | 1 segment, all 3 nodes |
| `test_split_flat_returns_empty` | 3 nodes, same elevation | `[]` |
| `test_split_downhill_returns_empty` | 3 nodes, descending | `[]` |
| `test_split_uphill_then_flat` | 4 nodes: 0→1→2 uphill, 2→3 flat | 1 segment: nodes 0,1,2 |
| `test_split_flat_then_uphill` | 4 nodes: 0→1 flat, 1→2→3 uphill | 1 segment: nodes 1,2,3 |
| `test_split_two_runs_separated_by_flat` | 6 nodes: 0→2 up, 2→3 flat, 3→5 up | 2 segments |
| `test_split_too_short_excluded` | 2 nodes ~10 m apart, steep gain | `[]` (below 50 m minimum) |
| `test_split_exactly_at_min_length` | 2 nodes ~50 m apart, steep gain | 1 segment |
| `test_split_raises_on_length_mismatch` | `len(coords) != len(elevs)` | `ValueError` |
| `test_split_raises_on_fewer_than_two_points` | 1 node | `ValueError` |

For the 10 m / 50 m tests: `delta_lat = target_m / 111_111`. Comment the expected distance in the test.

#### New integration tests — `tests/test_api.py` (9 tests)

**Shared fixture:** 1 way, 4 nodes. ORS elevations: [0, 20, 20, 35].
- Pair 0→1: +20 m over ~111 m ≈ 18% → climbing
- Pair 1→2: +0 m → flat (breaks run)
- Pair 2→3: +15 m over ~111 m ≈ 13.5% → climbing

Both runs are ~111 m > 50 m min.

| Test | Params | Expected |
|---|---|---|
| `test_get_hills_one_way_two_segments` | defaults | 200, 2 segments, same `name` |
| `test_get_hills_min_grade_filters_low` | `min_grade_pct=15` | 200, 1 segment (≥15%) |
| `test_get_hills_min_grade_zero` | `min_grade_pct=0` | 200, 2 segments |
| `test_get_hills_surface_road_filter` | `surface=road` (2-way fixture) | road segment only |
| `test_get_hills_surface_trail_filter` | `surface=trail` (2-way fixture) | trail segment only |
| `test_get_hills_surface_none_returns_all` | no surface param | both surface types |
| `test_get_hills_all_flat_returns_empty` | way with 0% grade | 200, `[]` |
| `test_get_hills_min_grade_invalid_422` | `min_grade_pct=150` | 422 |
| `test_get_hills_min_grade_boundary` | see below | 200, segment included |

**`test_get_hills_min_grade_boundary` — implementation approach:**

This test pins the `>=` semantics: a segment whose `avg_grade` exactly equals `min_grade_pct` must be included. Because the exact `avg_grade` depends on the geodesic distance between the fixture's lat/lon pairs (which varies slightly from the 111 m approximation), the grade must be read from the API rather than guessed:

```python
def test_get_hills_min_grade_boundary(client_with_key):
    with respx.mock:
        # ... mock setup using shared 4-node fixture ...
        r1 = client_with_key.get("/hills/", params={"address": "...", "min_grade_pct": 0})
    assert r1.status_code == 200
    segments = r1.json()
    # take the grade of the lower segment (index 1 after sort)
    lower_grade = segments[1]["grade_avg_pct"]

    with respx.mock:
        # ... same mocks ...
        r2 = client_with_key.get("/hills/", params={"address": "...", "min_grade_pct": lower_grade})
    assert r2.status_code == 200
    assert any(s["grade_avg_pct"] == lower_grade for s in r2.json()), \
        "segment with avg_grade == min_grade_pct must be included (>= semantics)"
```

For the surface tests: use `highway: residential` (→ road) and `highway: footway` (→ trail), both with grade > 3% so only the surface param drives filtering. Ensure both ways' ORS elevation fixtures produce grades well above 3% — a grade-computation failure on one way must not silently make the surface filter appear to work.

---

## Elevation noise sensitivity

`split_into_climbing_segments()` is sensitive to elevation noise: a 1 m spike over 2 m horizontal distance produces a 50% grade pair that immediately re-opens a run. Raw ORS data can exhibit this on dense node sets. The `_FLAT_GRADE_THRESHOLD_PCT = 1.0` guard reduces but does not eliminate false splits.

**This sprint:** no smoothing is added — the threshold env var is the tuning lever. Note the sensitivity in `CLAUDE.md` under Key behaviors.

**Sprint 3 candidate:** add a 3-point rolling average over elevations after `get_elevations()` returns, behind a `HILLFINDER_SMOOTH_ELEVATIONS=false` env var.

---

## New environment variables

Add to `CLAUDE.md` env vars table and `hill-finder/.env.example`:

| Variable | Default | Notes |
|---|---|---|
| `ORS_TIMEOUT_S` | `15` | HTTP client timeout in seconds; used in `main.py` (client-level) and `elevation.py` (per-request) |
| `HILLFINDER_FLAT_THRESHOLD_PCT` | `1.0` | Grade % below which a node pair is treated as flat |
| `HILLFINDER_MIN_SEGMENT_M` | `50.0` | Minimum climbing run length in metres |

---

## Files modified

| File | Change |
|---|---|
| `hill-finder/app/main.py` | `_HTTP_TIMEOUT_S` constant from `ORS_TIMEOUT_S` env var |
| `hill-finder/app/services/elevation.py` | `import os`; `ORS_TIMEOUT` read from `ORS_TIMEOUT_S` env var |
| `hill-finder/app/services/overpass.py` | `way_id` added to returned dict |
| `hill-finder/app/utils/geo.py` | `import os`; 2 module constants; `split_into_climbing_segments()` |
| `hill-finder/app/models/hill.py` | `way_id: int \| None = None`; `way_segment_index: int = 0` |
| `hill-finder/app/routers/hills.py` | `Literal` import; new geo import; 2 new query params; new per-segment loop |
| `hill-finder/tests/test_geo.py` | 10 new unit tests |
| `hill-finder/tests/test_api.py` | Update 1 existing test; 9 new tests |
| `CLAUDE.md` | 3 new rows in env vars table; noise-sensitivity note under Key behaviors |
| `hill-finder/.env.example` | 3 new env vars |

---

## Verification

```bash
cd hill-finder

# All tests (45 existing + ~19 new)
python -m pytest tests/ -v

# Segment splitting unit tests in isolation
python -m pytest tests/test_geo.py -v -k "split"

# New API integration tests
python -m pytest tests/test_api.py -v -k "segment or surface or min_grade"

# Confirm updated existing test
python -m pytest tests/test_api.py::test_get_hills_full_pipeline_returns_sorted_results -v

# Manual smoke test (real keys required in .env)
uvicorn app.main:app --reload
# GET /hills/?address=Manayunk+Philadelphia+PA&radius_m=2000&min_grade_pct=5&surface=road
```
