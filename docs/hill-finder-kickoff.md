# Hill Finder — Project Kickoff

A local-first tool to help runners find nearby hills for training, ranked by steepness and length, with road vs. trail classification.

---

## Problem Statement

Finding good hills for running training is surprisingly hard. Most mapping tools don't surface hills as a concept — you have to manually explore terrain, rely on word of mouth, or use apps like Strava that require you to already know where to run. This tool flips that: given a location, find and rank the best hills nearby.

---

## MVP Features

1. **Steepness** — grade percentage (elevation change ÷ horizontal distance × 100)
2. **Length** — total length of the hill segment in meters/miles
3. **Surface type** — road vs. trail (with sub-classification where available)

### Nice-to-Have (Post-MVP)
- Max grade vs. average grade (runners care about the hardest pitch)
- Elevation profile visualization
- "Hill score" combining grade + length into a single ranking metric
- Filtering by surface type
- Saved/favorited hills

---

## Data Sources

### Road & Trail Geometry — OpenStreetMap via Overpass API
- **URL:** `https://overpass-api.de/api/interpreter`
- **Free:** Yes, no API key required (fair use limits apply)
- **What you get:** Geometry (lat/lon nodes) for every road and trail, plus tags like `highway`, `surface`, and `name`
- **Key OSM tags for classification:**

| Tag | Values | Meaning |
|---|---|---|
| `highway` | `road`, `residential`, `primary`, etc. | Paved road |
| `highway` | `path`, `footway`, `track` | Trail or path |
| `surface` | `asphalt`, `concrete` | Paved |
| `surface` | `gravel`, `dirt`, `grass` | Unpaved |

### Elevation Data — SRTM GL1 (30m resolution)
- **Recommended API:** OpenRouteService Elevation API (`https://api.openrouteservice.org/elevation/line`)
- **Free tier:** Yes, requires free account for API key
- **Resolution:** 30m — good enough for training hills of meaningful length
- **Why not GL3 (90m)?** At 90m you miss short punchy climbs; 30m gives 9x more data points with no added complexity
- **US-only alternative:** USGS 3DEP (~10m resolution) via the National Map API — excellent detail if you stay US-focused

### Geocoding — Nominatim (OSM)
- **URL:** `https://nominatim.openstreetmap.org/search`
- **Free:** Yes, no API key required
- **Use:** Convert a user-entered address or city into a lat/lon center point

---

## Data Flow

```
User enters location
        │
        ▼
Nominatim geocoding → (lat, lon) center point
        │
        ▼
Overpass API query → all roads/trails within radius
        │
        ▼
For each segment: call elevation API with node coordinates
        │
        ▼
Compute grade, length, classify surface from OSM tags
        │
        ▼
Rank results, return to user
```

---

## Proposed Stack

This fits naturally with your existing toolset from DataPrivy:

| Layer | Technology | Rationale |
|---|---|---|
| Backend | Python + FastAPI | Already in use; easy to expose endpoints |
| Data cache | DuckDB | Cache elevation lookups locally (SRTM data never changes) |
| HTTP client | `httpx` or `requests` | Call Overpass and elevation APIs |
| Frontend (MVP) | Simple HTML + Leaflet.js | Map display, no framework needed for MVP |
| Frontend (v2) | Electron (if desktop) | Matches DataPrivy architecture |

### Why Cache Elevation Data?
SRTM elevation data is static — a given lat/lon always returns the same elevation. Once you've queried a bounding box, store results in DuckDB. This makes repeat queries instant and reduces API calls significantly.

---

## Key Technical Challenges

### 1. Grade Calculation
You don't get grade directly from any API. You compute it:

```
grade (%) = (elevation_end - elevation_start) / horizontal_distance × 100
```

For a multi-node segment, compute grade between each consecutive pair of nodes, then report max grade and average grade separately.

### 2. Segment Detection
OSM returns *ways* (roads/trails), not hills. A single road way might be flat for 2km then climb steeply. You'll need to:
- Break ways into segments by elevation change direction
- Identify contiguous climbing segments
- Filter out segments below a minimum grade threshold (e.g. >3% to count as a "hill")

### 3. Surface Classification Fallback
Not all OSM ways have a `surface` tag. Classification priority:
1. Use `surface` tag if present
2. Fall back to `highway` tag (e.g. `footway` → trail, `residential` → road)
3. Flag as "unknown" if neither is informative

---

## Overpass API Query Skeleton

```
[out:json];
(
  way["highway"](around:5000, {lat}, {lon});
);
out geom;
```

This returns all roads and trails within 5km of a point, with full geometry. Adjust the radius and filter by `highway` values to narrow results.

---

## OpenRouteService Elevation Request Skeleton

```json
POST https://api.openrouteservice.org/elevation/line

{
  "format_in": "geojson",
  "format_out": "geojson",
  "geometry": {
    "coordinates": [[lon1, lat1], [lon2, lat2], ...],
    "type": "LineString"
  }
}
```

Returns the same coordinates with elevation (z) added to each point.

---

## OSM Coverage Notes
- **Roads:** Excellent globally, very reliable
- **Trails:** Strong in parks, popular areas, and Western Europe; thinner for informal/unmarked paths
- **Surface tags:** Present on most roads; variable on trails — your fallback logic matters here
- **Global:** OSM works worldwide out of the box; no US-only limitation

---

## Sprint Ideas

### Sprint 1 — Data Pipeline
- Set up FastAPI project skeleton
- Implement Nominatim geocoding
- Implement Overpass query for roads/trails near a point
- Implement OpenRouteService elevation enrichment
- Compute grade and length per segment
- Return raw JSON results

### Sprint 2 — Hill Detection Logic
- Segment splitting (detect climbing vs. flat vs. descending portions)
- Min grade threshold filtering
- Max grade vs. average grade
- Surface classification with fallback logic

### Sprint 3 — UI
- Leaflet map showing results as overlays
- Color-coded by steepness
- Click a segment to see details (grade, length, surface)

### Sprint 4 — Caching & Polish
- DuckDB caching of elevation results by bounding box
- Hill scoring/ranking
- Input validation, error handling, rate limit handling

---

## Reference Links

- [Overpass API](https://overpass-api.de) — OSM data query engine
- [Overpass Turbo](https://overpass-turbo.eu) — interactive query tester (great for exploring)
- [OpenRouteService](https://openrouteservice.org) — elevation API (free tier)
- [Open-Elevation](https://open-elevation.com) — alternative elevation API, no key required
- [Nominatim](https://nominatim.openstreetmap.org) — OSM geocoding
- [USGS National Map](https://apps.nationalmap.gov) — 3DEP high-res elevation for US
- [OSM highway tag values](https://wiki.openstreetmap.org/wiki/Key:highway) — full reference for road/trail classification
- [OSM surface tag values](https://wiki.openstreetmap.org/wiki/Key:surface) — full reference for surface types
- [Leaflet.js](https://leafletjs.com) — lightweight map library for the UI
