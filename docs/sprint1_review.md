# Hill Finder — Sprint 1 Review

**Sprint:** Sprint 1 — Data Pipeline  
**Source Plan:** hill-finder-kickoff.md  
**Status:** Pre-kickoff review

---

## Sprint 1 Scope (from plan)

- FastAPI project skeleton
- Nominatim geocoding
- Overpass query for roads/trails near a point
- OpenRouteService (ORS) elevation enrichment
- Grade and length computation per segment
- Return raw JSON results

---

## Issues & Risks

### 1. OpenRouteService Rate Limits Are Restrictive

**Issue:** The ORS free tier caps at 2,000 requests/day and 40 requests/minute. A single user query can generate dozens of elevation API calls if you batch per-segment. At scale, you'll hit the daily cap fast.

**Recommendation:** Do not call ORS per-segment. Batch all node coordinates from an Overpass query into a single ORS request (ORS accepts a full LineString with many coordinates). Alternatively, evaluate Open-Elevation (listed in reference links) — no API key, no rate cap, though slower. Consider making the elevation backend pluggable from day one so you can swap it without rearchitecting.

---

### 2. ORS API Key in Sprint 1 — Not Accounted For

**Issue:** The plan notes ORS requires a free account and API key but doesn't call out where that key lives in the project. Hardcoding it is a common early mistake that causes problems when the project goes public on GitHub.

**Recommendation:** Add a `.env` file and `python-dotenv` to the project skeleton from day one. Define `ORS_API_KEY` there and load it via `os.getenv()`. Add `.env` to `.gitignore` immediately. Document the required env vars in a `README.md` or `.env.example`.

---

### 3. Overpass API Fair Use — No Bounding Box Guard

**Issue:** The skeleton query uses `around:5000` (5km radius) with no filter on `highway` values. This returns every mapped way in a 5km circle — potentially thousands of features in dense urban areas. Overpass will return it, but the response can be very large (10MB+), slow to parse, and may trigger fair-use throttling.

**Recommendation:** Filter by relevant `highway` values in the Overpass query itself:

```
[out:json][timeout:25];
(
  way["highway"~"^(primary|secondary|tertiary|residential|unclassified|path|footway|track|cycleway)$"](around:5000, {lat}, {lon});
);
out geom;
```

Also add a `[timeout:25]` directive. Consider exposing radius as a config parameter (default 3000m) rather than hardcoding 5000.

---

### 4. Nominatim Usage Policy — User-Agent Required

**Issue:** Nominatim's usage policy requires every request to include a valid `User-Agent` header identifying your app. Requests without it can be blocked.

**Recommendation:** Set a custom User-Agent on your `httpx` client:

```python
headers = {"User-Agent": "HillFinder/0.1 (your@email.com)"}
```

Also respect Nominatim's 1 request/second limit. Add a small delay or use a rate-limiter if you anticipate repeated geocoding calls during testing.

---

### 5. Elevation API Payload Size Limits

**Issue:** ORS elevation endpoint has an undocumented limit on coordinate count per request (approximately 2,000 points). A dense urban Overpass result with many long ways could exceed this in a single call.

**Recommendation:** Chunk coordinate arrays before sending to ORS (e.g., max 500 points per request) and reassemble results. Build this chunking utility in Sprint 1 so you don't refactor later.

---

### 6. Grade Computation on Multi-Node Segments Is Underspecified

**Issue:** The plan mentions computing grade but describes it only as start-to-end elevation change divided by horizontal distance. For a way with many nodes, this flattens out any undulation — a segment that climbs 20m, drops 10m, then climbs 20m reports as if it only climbed 10m net.

**Recommendation:** Compute grade pair-by-pair across consecutive nodes. Store both:
- **Average grade:** total elevation gain / total horizontal distance (for characterizing the segment overall)
- **Max grade:** highest grade between any two consecutive nodes (runners care about the steepest pitch)

Both fields are already in the Nice-to-Have list — worth computing them in Sprint 1 since you have the node data anyway. It's easier than adding them later.

---

### 7. Horizontal Distance Calculation

**Issue:** The plan doesn't specify how horizontal distance is computed. Naively using lat/lon differences introduces error, especially at higher latitudes.

**Recommendation:** Use the **Haversine formula** for distance between coordinate pairs. Python's `geopy` library has `geopy.distance.geodesic()` which is accurate and fast enough. Add this to your dependencies from the start.

---

### 8. Sprint 1 Has No Error Handling Story

**Issue:** Three external APIs are in play (Nominatim, Overpass, ORS). Any of them can timeout, return 429, or return malformed data. With no error handling defined, the first integration test will surface this and stall progress.

**Recommendation:** Define a minimal error handling contract for Sprint 1:
- Wrap all external API calls in try/except with logged errors
- Return structured error responses from FastAPI (not raw exceptions)
- Use `httpx` with explicit `timeout=` settings on every request (suggested: 10s for Nominatim, 25s for Overpass, 15s for ORS)

---

## Best Practices

### Project Structure
Establish this layout in the Sprint 1 skeleton to avoid reorganizing later:

```
hill-finder/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── routers/
│   │   └── hills.py         # /hills endpoint
│   ├── services/
│   │   ├── geocoding.py     # Nominatim wrapper
│   │   ├── overpass.py      # Overpass query logic
│   │   └── elevation.py     # ORS / elevation backend
│   └── models/
│       └── hill.py          # Pydantic response models
├── .env                     # API keys (gitignored)
├── .env.example             # Committed template
├── requirements.txt
└── README.md
```

### Use Pydantic Models for API Responses from Day One
Define response shapes as Pydantic models even in Sprint 1. This prevents silent data drift between sprints and makes the API self-documenting via FastAPI's auto-generated `/docs`.

```python
class HillSegment(BaseModel):
    name: str | None
    grade_avg_pct: float
    grade_max_pct: float
    length_m: float
    surface: str          # "road" | "trail" | "unknown"
    coordinates: list[tuple[float, float]]
```

### DuckDB Caching — Defer but Design Now
The plan defers caching to Sprint 4. That's fine, but design the elevation service interface so caching can be dropped in without changing call sites. Suggestion: wrap ORS calls in a `get_elevations(coordinates)` function that Sprint 4 can swap for a cached version transparently.

### Test with Overpass Turbo First
Before writing any Overpass query code, prototype and validate it in [Overpass Turbo](https://overpass-turbo.eu). It shows response size, timing, and renders ways on a map — much faster than debugging through code. Add your tested query string as a comment in `overpass.py`.

### Pin Dependencies
Use `pip freeze > requirements.txt` after setting up your environment, or better, use a `pyproject.toml` with pinned versions. Unpinned deps are a common source of hard-to-debug failures when picked up on a new machine.

### Suggested `httpx` Client Setup
Use a shared `httpx.AsyncClient` (not per-request instantiation) for connection reuse:

```python
# In a lifespan context manager on the FastAPI app
async with httpx.AsyncClient(timeout=15.0) as client:
    app.state.http_client = client
```

---

## Recommended Sprint 1 Task Additions

These are small additions that address the issues above without scope-creeping the sprint:

| Addition | Effort | Why Now |
|---|---|---|
| Add `.env` + `python-dotenv` to skeleton | ~15 min | Prevents API key leaks on GitHub |
| Add User-Agent to Nominatim client | ~5 min | Required by usage policy |
| Add `[timeout]` + `highway` filter to Overpass query | ~15 min | Prevents large response issues |
| Add Haversine/geodesic distance utility | ~30 min | Required for accurate grade; easier now than refactoring |
| Add chunked coordinate batching for ORS | ~45 min | Prevents payload limit failures |
| Define Pydantic response model for `HillSegment` | ~20 min | Saves rework in Sprint 2-3 |

---

## External API Reference Summary

| API | Auth | Rate Limit | Timeout Suggestion |
|---|---|---|---|
| Nominatim | None (User-Agent required) | 1 req/sec | 10s |
| Overpass | None | Fair use, no hard cap | 25s |
| OpenRouteService | API key (free tier) | 40 req/min, 2,000/day | 15s |
| Open-Elevation | None | No stated limit | 20s |

---

*Review complete. Recommend addressing Issues 1, 2, 3, and 4 before writing any integration code.*
