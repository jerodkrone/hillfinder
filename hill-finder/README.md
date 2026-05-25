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

**Example:**

```bash
curl "http://127.0.0.1:8000/hills/?address=Manayunk%2C+Philadelphia%2C+PA&radius_m=2000"
```

**Response:** JSON array of hill segments sorted by average grade (steepest first).

```json
[
  {
    "name": "Levering Street",
    "grade_avg_pct": 8.43,
    "grade_max_pct": 12.1,
    "length_m": 312.5,
    "surface": "road",
    "coordinates": [[40.028, -75.224], ...]
  }
]
```
