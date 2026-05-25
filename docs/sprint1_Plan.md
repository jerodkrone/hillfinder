# HillFinder — Sprint 1 Implementation Plan

**Sprint:** Sprint 1 — Data Pipeline  
**Status:** Approved, ready for implementation

---

## Context

Sprint 1 builds the complete data pipeline: geocode a user-supplied address, fetch road/trail geometry from OpenStreetMap via Overpass, enrich each segment with elevation data from OpenRouteService, compute hill grades, and return ranked results via a FastAPI endpoint. No code exists yet — this sprint creates the entire project from scratch.

The `sprint1_review.md` pre-kickoff review identified 8 risk areas. All are addressed in this plan and marked in each task.

---

## Project Root

All source code lives under:
```
hill-finder/
```
within the project directory. All paths below are relative to `hill-finder/`.

---

## Directory Layout

```
hill-finder/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── routers/
│   │   ├── __init__.py
│   │   └── hills.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── geocoding.py
│   │   ├── overpass.py
│   │   └── elevation.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── hill.py
│   └── utils/
│       ├── __init__.py
│       └── geo.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_geo.py
│   ├── test_elevation.py
│   └── test_api.py
├── .env                  (gitignored — real secrets)
├── .env.example          (committed — template)
├── .gitignore
├── requirements.txt
└── README.md
```

All `__init__.py` files are empty.

---

## Task 1 — Project Skeleton & Environment

Create the directory tree and all configuration files before writing any code.

### `requirements.txt`
```
fastapi==0.111.0
uvicorn[standard]==0.29.0
httpx==0.27.0
python-dotenv==1.0.1
pydantic==2.7.1
geopy==2.4.1
pytest==8.2.0
```

### `.env.example`
```
ORS_API_KEY=your_openrouteservice_api_key_here
```

### `.gitignore`
```
.env
__pycache__/
*.pyc
.venv/
```

### `README.md` must cover
- Project purpose (find and rank hills for running training)
- Setup: create venv, `pip install -r requirements.txt`, copy `.env.example` → `.env`, add ORS API key
- Run: `uvicorn app.main:app --reload`
- API: `GET /hills/?address=<location>&radius_m=<meters>`

**Review issue addressed:** #2 — API key security from day one.

---

## Task 2 — Pydantic Response Model

**File:** `app/models/hill.py`

Define the data contract before writing any service. All services build toward this shape.

```python
from pydantic import BaseModel


class HillSegment(BaseModel):
    name: str | None
    grade_avg_pct: float       # total upward gain / total distance × 100
    grade_max_pct: float       # steepest single consecutive node pair
    length_m: float
    surface: str               # "road" | "trail" | "unknown"
    coordinates: list[tuple[float, float]]
```

---

## Task 3 — Geo Utilities

**File:** `app/utils/geo.py`

Three pure functions — no external APIs, no side effects. Build and verify in isolation before touching any service.

### `compute_distance_m(coord_a, coord_b) -> float`
- Inputs: two `(lat, lon)` tuples
- Uses `geopy.distance.geodesic(coord_a, coord_b).meters`
- Returns distance in meters

### `compute_grades(coordinates, elevations) -> tuple[float, float]`
- Inputs: `list[tuple[float, float]]`, `list[float]` (must be same length, ≥ 2 items)
- Raises `ValueError` if lengths differ or fewer than 2 points
- Iterates consecutive pairs:
  - `dist = compute_distance_m(coords[i], coords[i+1])`
  - `elev_diff = elevations[i+1] - elevations[i]`
  - Accumulate `total_distance += dist`
  - If `elev_diff > 0`: `total_gain += elev_diff`
  - If `dist > 0`: `pair_grade = abs(elev_diff) / dist * 100`; update `max_grade`
- `avg_grade_pct = total_gain / total_distance * 100` (upward gain only, not net)
- Guard: if `total_distance == 0`, return `(0.0, 0.0)`
- Returns `(round(avg_grade_pct, 2), round(max_grade_pct, 2))`

### `compute_total_length_m(coordinates) -> float`
- Sums `compute_distance_m` across all consecutive pairs
- Returns `round(total, 2)`

**Review issues addressed:** #6 (avg + max grade computed pair-by-pair), #7 (accurate geodesic distance)

---

## Task 4 — FastAPI Entry Point

**File:** `app/main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import httpx
from dotenv import load_dotenv

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(timeout=15.0) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="HillFinder", version="0.1.0", lifespan=lifespan)

from app.routers import hills  # noqa: E402
app.include_router(hills.router)
```

- `load_dotenv()` at module level so `os.getenv()` works everywhere on startup
- Single shared `httpx.AsyncClient` — connection reuse across all requests
- `timeout=15.0` is the default; individual services override per request with explicit `timeout=` arguments
- Client accessed in routers via `request.app.state.http_client`

---

## Task 5 — Geocoding Service

**File:** `app/services/geocoding.py`

### Constants
```python
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT = 10.0
NOMINATIM_USER_AGENT = "HillFinder/0.1 (contact@email.com)"
```

### `async geocode_address(address: str, client: httpx.AsyncClient) -> tuple[float, float]`

```python
response = await client.get(
    NOMINATIM_URL,
    params={"q": address, "format": "json", "limit": 1},
    headers={"User-Agent": NOMINATIM_USER_AGENT},
    timeout=NOMINATIM_TIMEOUT,
)
```

- Parse `float(data[0]["lat"])`, `float(data[0]["lon"])`
- Empty result list → `HTTPException(400, detail=f"No location found for: {address}")`
- `httpx.TimeoutException` → `HTTPException(504, "Geocoding service timed out")`
- `httpx.HTTPStatusError` → `HTTPException(502, "Geocoding service returned an error")`
- `httpx.RequestError` → `HTTPException(502, "Geocoding service unreachable")`

Note: Nominatim policy requires User-Agent on every request — requests without it may be blocked. The 1 req/sec rate limit is naturally satisfied at one geocode per user request.

**Review issues addressed:** #4 (User-Agent), #8 (error handling, explicit timeout)

---

## Task 6 — Overpass Service

**File:** `app/services/overpass.py`

### Query Template

Validate this in [Overpass Turbo](https://overpass-turbo.eu) before writing code. Add the validated result as a comment in the file.

```
[out:json][timeout:25];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|path|footway|track|cycleway)$"](around:{radius},{lat},{lon});
);
out geom;
```

### `async fetch_ways(lat, lon, client, radius_m=3000) -> list[dict]`

Each returned dict: `{"name": str|None, "surface": str, "coordinates": [(lat, lon), ...], "tags": dict}`

- POST `https://overpass-api.de/api/interpreter`
- Body: formatted query string
- Content-Type: `application/x-www-form-urlencoded`
- `timeout=25.0` (matches `[timeout:25]` in query body)
- `out geom` returns `element["geometry"]` as `[{"lat": float, "lon": float}, ...]`
- Extract: `coords = [(node["lat"], node["lon"]) for node in geometry]`
- Skip ways where `len(geometry) < 2`
- Error handling: timeout → 504; HTTP error → 502; request error → 502; JSON parse error → 502

### `_classify_surface(tags: dict) -> str` — private helper

Priority order (first match wins):
1. `tags.get("surface")` in `{"asphalt", "concrete", "paved", "cobblestone", "sett"}` → `"road"`
2. `tags.get("surface")` in `{"gravel", "dirt", "grass", "unpaved", "compacted", "fine_gravel", "ground", "mud", "sand"}` → `"trail"`
3. `tags.get("highway")` in `{"path", "footway", "track", "bridleway"}` → `"trail"`
4. `tags.get("highway")` in `{"primary", "secondary", "tertiary", "residential", "unclassified", "cycleway", "service", "living_street"}` → `"road"`
5. Fallback → `"unknown"`

**Review issues addressed:** #3 (highway filter + `[timeout:25]` + configurable radius), #8 (error handling)

---

## Task 7 — Elevation Service

**File:** `app/services/elevation.py`

### Constants
```python
ORS_ELEVATION_URL = "https://api.openrouteservice.org/elevation/line"
ORS_TIMEOUT = 15.0
ORS_CHUNK_SIZE = 500
```

### Public: `async get_elevations(coordinates, client) -> list[float]`

This is the **only** elevation call site across the entire codebase. Sprint 4 inserts a DuckDB cache check inside this function without changing any callers.

```python
async def get_elevations(coordinates, client):
    return await _get_elevations_ors(coordinates, client)
```

### Private: `_chunk_coordinates(coordinates, chunk_size=500) -> list[list]`

Overlap-by-one at chunk boundaries so elevation continuity is preserved:
- Chunk 0: indices `0..499`
- Chunk 1: indices `499..998` (starts at 499, not 500)
- Chunk 2: indices `998..end`

Reassembly: chunk 0 added in full; chunks 1+ skip their first element (removes the duplicate boundary point). Final list length equals input length.

### Private: `async _get_elevations_ors(coordinates, client) -> list[float]`

1. `api_key = os.getenv("ORS_API_KEY")` → `HTTPException(500, "ORS_API_KEY not configured")` if `None`
2. `chunks = _chunk_coordinates(coordinates, ORS_CHUNK_SIZE)`
3. For each chunk:
   - Convert `(lat, lon)` → `[lon, lat]` — ORS uses GeoJSON coordinate order (lon first); comment this explicitly
   - POST ORS with:
     ```json
     {
       "format_in": "geojson",
       "format_out": "geojson",
       "geometry": {"coordinates": [[lon, lat], ...], "type": "LineString"}
     }
     ```
   - Headers: `{"Authorization": api_key, "Content-Type": "application/json"}`
   - Extract elevations: `[pt[2] for pt in result["geometry"]["coordinates"]]`
4. Reassemble across chunks (skip index 0 on chunks 1+)
5. Error handling per chunk: 429 → 429; timeout → 504; other HTTP error → 502; request error → 502

**Review issues addressed:** #1 (all coords batched, single call, pluggable interface), #2 (key from env), #5 (chunking at 500 pts), #8 (error handling, timeout)

---

## Task 8 — Hills Router

**File:** `app/routers/hills.py`

### Endpoint

```python
@router.get("/hills/", response_model=list[HillSegment])
async def get_hills(
    request: Request,
    address: str,
    radius_m: int = Query(default=3000, ge=100, le=10000),
):
```

### Pipeline (execute in order)

1. `client = request.app.state.http_client`
2. `lat, lon = await geocode_address(address, client)`
3. `ways = await fetch_ways(lat, lon, client, radius_m)`
4. If `not ways`, return `[]`
5. Flatten all coordinates and track per-way index slices:
   ```python
   all_coords = []
   way_slices = []
   for way in ways:
       start = len(all_coords)
       all_coords.extend(way["coordinates"])
       way_slices.append((start, len(all_coords)))
   ```
6. `all_elevations = await get_elevations(all_coords, client)` — **single call for all ways**
7. For each `(way, (start, end))`:
   - `coords = way["coordinates"]`
   - `elevations = all_elevations[start:end]`
   - `avg_grade, max_grade = compute_grades(coords, elevations)`
   - `length_m = compute_total_length_m(coords)`
   - Append `HillSegment(name=way["name"], grade_avg_pct=avg_grade, grade_max_pct=max_grade, length_m=length_m, surface=way["surface"], coordinates=coords)`
8. Sort results by `grade_avg_pct` descending
9. Return results

**Review issue addressed:** #1 (single ORS call for entire query)

---

## Task 9 — Pytest Suite

Convert the verification snippets from Tasks 3 and 7 into a proper pytest suite. External API calls (Nominatim, Overpass, ORS) are not mocked here — they remain as manual verification steps. This gives a real test runner for all pure logic with zero new test logic to write.

### `tests/conftest.py`

Empty file. Placeholder for Sprint 2 fixtures (e.g., shared `httpx` mock client).

```python
```

### `tests/test_geo.py`

Promotes the Task 3 REPL verification checks directly into pytest functions.

```python
from app.utils.geo import compute_distance_m, compute_grades, compute_total_length_m


def test_compute_distance_m_known_pair():
    d = compute_distance_m((40.0, -75.0), (40.001, -75.0))
    assert 100 < d < 120, f"Expected ~111m, got {d}"


def test_compute_grades_uphill():
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [0.0, 10.0])
    assert 8 < avg < 10, f"Expected ~9%, got {avg}"


def test_compute_grades_flat():
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [100.0, 100.0])
    assert avg == 0.0 and max_ == 0.0


def test_compute_grades_downhill_excluded_from_avg():
    # Downhill segment: avg grade counts only upward gain, so should be 0
    avg, max_ = compute_grades([(40.0, -75.0), (40.001, -75.0)], [10.0, 0.0])
    assert avg == 0.0


def test_compute_grades_raises_on_length_mismatch():
    import pytest
    with pytest.raises(ValueError):
        compute_grades([(40.0, -75.0), (40.001, -75.0)], [0.0])


def test_compute_total_length_m():
    length = compute_total_length_m([(40.0, -75.0), (40.001, -75.0)])
    assert 100 < length < 120
```

### `tests/test_elevation.py`

Promotes the Task 7 chunking verification check into pytest.

```python
from app.services.elevation import _chunk_coordinates


def test_chunk_coordinates_count():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 3


def test_chunk_coordinates_boundary_overlap():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert chunks[0][-1] == chunks[1][0], "Boundary overlap missing between chunks 0 and 1"
    assert chunks[1][-1] == chunks[2][0], "Boundary overlap missing between chunks 1 and 2"


def test_chunk_coordinates_reassembly_count():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    total = len(chunks[0]) + sum(len(c) - 1 for c in chunks[1:])
    assert total == 1100, f"Reassembly count mismatch: {total}"


def test_chunk_coordinates_under_chunk_size():
    coords = [(float(i), float(i)) for i in range(100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == coords
```

### `tests/test_api.py`

Uses FastAPI's built-in `TestClient` (no extra dependency — included with `fastapi`). Tests startup and the missing-key guard without hitting any external API.

```python
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_openapi_docs_available(client):
    response = client.get("/docs")
    assert response.status_code == 200


def test_missing_ors_key_returns_500(client):
    response = client.get("/hills/", params={"address": "Philadelphia, PA"})
    assert response.status_code == 500
    assert "ORS_API_KEY" in response.json()["detail"]
```

### Running the suite

```
pytest tests/ -v
```

All tests must pass before the first `git commit`.

---

## Data Flow

```
GET /hills?address=Manayunk,+PA&radius_m=2000
        |
        v geocode_address()
Nominatim --> (lat, lon)
        |
        v fetch_ways()
Overpass --> [way1, way2, ... wayN]   each with (lat,lon) coord list
        |
        v flatten + track index slices
all_coords  = [coord, coord, ...]     all nodes concatenated
way_slices  = [(0,12), (12,31), ...]  per-way index ranges
        |
        v get_elevations(all_coords)  SINGLE CALL
elevation.py chunks at 500, calls ORS, reassembles
all_elevations = [elev_m, ...]        same length as all_coords
        |
        v per way: slice + compute
compute_grades(coords, all_elevations[start:end]) -> (avg, max)
compute_total_length_m(coords) -> length_m
        |
        v sort + return
list[HillSegment] sorted by grade_avg_pct descending
```

**Coordinate convention:** all internal data is `(lat, lon)`. Only `elevation.py` converts to `[lon, lat]` for ORS — this is commented at the call site.

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.111.0 | Framework, routing, Pydantic v2, auto OpenAPI docs at `/docs`; `TestClient` used in tests |
| `uvicorn[standard]` | 0.29.0 | ASGI server; `[standard]` adds uvloop |
| `httpx` | 0.27.0 | Async HTTP client for Nominatim, Overpass, ORS; also required by `TestClient` |
| `python-dotenv` | 1.0.1 | Loads `.env` into `os.environ` at startup |
| `pydantic` | 2.7.1 | `HillSegment` model; FastAPI 0.111 uses Pydantic v2 |
| `geopy` | 2.4.1 | `geodesic()` — Vincenty/WGS-84 ellipsoid distance |
| `pytest` | 8.2.0 | Test runner for geo utility and chunking logic tests |

### Windows Setup Commands
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env: add your ORS_API_KEY
uvicorn app.main:app --reload
```

---

## Verification

### 1. Import check
```
python -c "import fastapi, httpx, pydantic, geopy, dotenv; print('OK')"
```

### 2. Pytest suite (from `hill-finder/`)
```
pytest tests/ -v
```
Expected: all tests in `test_geo.py`, `test_elevation.py`, and `test_api.py` pass. Fix any failures before proceeding to manual steps.

### 3. Server startup
```
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs` — must show `GET /hills/` with query params.

### 4. Missing API key guard (before populating `.env`)
```
curl "http://127.0.0.1:8000/hills/?address=Philadelphia%2C+PA"
```
Expected: HTTP 500, `{"detail": "ORS_API_KEY not configured"}`

### 5. End-to-end test (after adding `ORS_API_KEY` to `.env`)
```
curl "http://127.0.0.1:8000/hills/?address=Manayunk%2C+Philadelphia%2C+PA&radius_m=2000"
```
Expected: HTTP 200, JSON array of `HillSegment` objects with non-zero grades, sorted steepest first.

### 6. Security check (before first `git commit`)
```
git check-ignore -v .env
```
Expected: `.gitignore:1:.env  .env`

If `.env` is not ignored — stop and fix `.gitignore` before committing anything.

---

## Sprint Review Issue Traceability

| Issue | Resolution | File(s) |
|---|---|---|
| #1 ORS Rate Limits | All coords flattened before elevation call; `get_elevations()` called once per request; pluggable via public function | `hills.py`, `elevation.py` |
| #2 API Key Security | `python-dotenv`; `load_dotenv()` at startup; key via `os.getenv()`; `.env` gitignored; `.env.example` committed | `main.py`, `elevation.py`, `.gitignore` |
| #3 Overpass Overfetch | Highway regex filter + `[timeout:25]` + configurable `radius_m` (default 3000m) | `overpass.py` |
| #4 Nominatim User-Agent | `NOMINATIM_USER_AGENT` constant applied to every request | `geocoding.py` |
| #5 ORS Payload Size | `_chunk_coordinates()` at 500 pts with overlap-by-1; reassembly removes duplicate boundary | `elevation.py` |
| #6 Grade Computation | `compute_grades()` iterates consecutive pairs; returns both `avg_grade_pct` and `max_grade_pct` | `geo.py` |
| #7 Distance | `geopy.distance.geodesic()` for all distance calculations | `geo.py` |
| #8 Error Handling | All three external calls wrapped in try/except; structured `HTTPException`; explicit timeouts: 10s / 25s / 15s | `geocoding.py`, `overpass.py`, `elevation.py` |
| Gap: No test structure | `pytest` suite added (Task 9); covers geo utilities, chunking logic, API startup, missing-key guard | `tests/` |

---

## Out of Scope for Sprint 1

| Feature | Target Sprint |
|---|---|
| Segment splitting (climb vs. flat detection within a way) | Sprint 2 |
| Minimum grade threshold filtering | Sprint 2 |
| Max vs. average grade UI distinction | Sprint 2 |
| Mocking external APIs in tests (`respx`) | Sprint 2 |
| Leaflet.js map frontend | Sprint 3 |
| DuckDB elevation caching | Sprint 4 (drops into `get_elevations()` body without changing callers) |
| Hill scoring / composite ranking metric | Sprint 4 |
| USGS 3DEP alternate backend | Post-MVP |
