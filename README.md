# HillFinder

Find and rank hills near any location for running training. Returns road and trail segments sorted by steepness, enriched with grade percentage, length, and surface type.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

Edit `.env` and add your [OpenRouteService](https://openrouteservice.org) API key:

```
ORS_API_KEY=your_key_here
```

## Run

```bash
uvicorn app.main:app --reload
```

Swagger docs: http://127.0.0.1:8000/docs

## API

### `GET /hills/`

Find and rank hills near a given address.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `address` | string | required | Any address or place name |
| `radius_m` | int | 3000 | Search radius in meters (100–10000) |
| `min_grade_pct` | float | 3.0 | Minimum average grade to include a segment (0.0–100.0) |
| `surface` | string | — | Filter by surface type: `road`, `trail`, or `unknown` |

**Example:**

```bash
curl "http://127.0.0.1:8000/hills/?address=Manayunk%2C+Philadelphia%2C+PA&radius_m=2000&min_grade_pct=5&surface=road"
```

**Response:** JSON array of hill segments sorted by average grade (steepest first).

```json
[
  {
    "name": "Levering Street",
    "way_id": 12345678,
    "grade_avg_pct": 8.43,
    "grade_max_pct": 12.1,
    "length_m": 312.5,
    "surface": "road",
    "coordinates": [[40.028, -75.224], ...],
    "way_segment_index": 0
  }
]
```

`way_id` is the OSM way ID (null if not present in Overpass data). `way_segment_index` is the zero-based index of this climbing run within its source way (a single way can yield multiple segments when split by flat sections).

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ORS_API_KEY` | Yes | — | OpenRouteService elevation API key |
| `NOMINATIM_CONTACT_EMAIL` | No | contact@example.com | Sent in User-Agent per OSM policy |
| `LOG_LEVEL` | No | INFO | |
| `HILLFINDER_MAX_WAYS` | No | 200 | Caps Overpass results |
| `ORS_TIMEOUT_S` | No | 15 | ORS elevation API timeout in seconds |
| `OVERPASS_TIMEOUT_S` | No | 180 | Overpass API timeout in seconds |
| `HILLFINDER_FLAT_THRESHOLD_PCT` | No | 1.0 | Grade % below which a node pair is treated as flat |
| `HILLFINDER_MIN_SEGMENT_M` | No | 50.0 | Minimum climbing run length in metres |
