# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then add ORS_API_KEY

# Run dev server
uvicorn app.main:app --reload

# Run all tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_geo.py::test_compute_distance_m_known_pair -v

# Run a single test module
python -m pytest tests/test_geo.py -v
```

## Architecture

HillFinder is a FastAPI service that returns nearby hills ranked by steepness. A single `GET /hills/?address=<location>&radius_m=<radius>` request chains three external APIs:

1. **Nominatim** (OSM) — geocodes the address to (lat, lon)
2. **Overpass API** — fetches road/trail geometry within a bounding box
3. **OpenRouteService** — enriches coordinates with elevation data

Then `app/utils/geo.py` computes grades and the response is sorted steepest-first.

### Module map

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app + lifespan (httpx.AsyncClient shared across requests) |
| `app/routers/hills.py` | `GET /hills/` — orchestrates the full pipeline |
| `app/services/geocoding.py` | Nominatim: address → (lat, lon); asyncio.Lock enforces 1 req/sec |
| `app/services/overpass.py` | Overpass: bounding box → road/trail segments with surface classification |
| `app/services/elevation.py` | ORS elevation API; chunks coordinates at 500 (API limit) with 1-point overlap |
| `app/utils/geo.py` | `compute_grades()`, `compute_distance_m()`, `compute_total_length_m()` |
| `app/models/hill.py` | `HillSegment` Pydantic model (the response schema) |

### Key behaviors to preserve

- **Grade formula:** average grade only counts uphill segments (upward gain / total distance × 100); max grade is the steepest consecutive node pair with nonzero horizontal distance.
- **Chunking:** elevation coordinates chunked at 500 with a 1-point boundary overlap to maintain continuity; overlap points are deduplicated on reassembly.
- **Surface classification:** checks OSM `surface` tag first, then falls back to `highway` tag to decide road / trail / unknown.
- **Way filtering:** zero-length ways are dropped before grade calculation to prevent division by zero.
- **Rate limiting:** Nominatim lock is held for 1 second per call; ORS 429 responses are surfaced as 429 to the client.
- **Error mapping:** timeouts → 504, upstream service errors → 502, unresolvable address → 400.

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `ORS_API_KEY` | Yes | — | OpenRouteService elevation API key |
| `NOMINATIM_CONTACT_EMAIL` | No | contact@example.com | Sent in User-Agent per OSM policy |
| `LOG_LEVEL` | No | INFO | |
| `HILLFINDER_MAX_WAYS` | No | 200 | Caps Overpass results |

## Coding best practices

- **No hardcoded timeouts.** All timeout values must come from environment variables with a sensible default (e.g. `int(os.getenv("ORS_TIMEOUT_S", "15"))`). Add new timeout vars to `.env.example` and the Environment variables table above.

## Testing

Tests use `pytest-asyncio` (all service tests are async) and `respx` for HTTP mocking. There are no real external calls in tests. `conftest.py` wires up shared fixtures.
