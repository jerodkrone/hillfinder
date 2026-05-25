# HillFinder — Sprint 1 Security & Logging Remediation Plan

**Date:** 2026-05-25  
**Scope:** S-1 through S-5 from `docs/sprint1_codereview.md`  
**Status:** Ready for implementation

---

## Overview

Five findings from the Sprint 1 code review require remediation before Sprint 2:

| ID | Finding | Severity | Primary File |
|----|---------|----------|--------------|
| S-1 | Nominatim User-Agent uses a placeholder email | Medium | `geocoding.py` |
| S-2 | No rate limiting on Nominatim (policy: 1 req/sec) | Medium | `geocoding.py` |
| S-3 | No logging in any service module | High | all services + router |
| S-4 | No cap on ways processed per request | Low | `hills.py` |
| S-5 | ORS API key must not appear in logs | Low | `elevation.py` |

S-3 and S-5 are coupled: S-5 is a guard-rail to apply while implementing S-3. Address S-3 and S-5 together. S-1 and S-2 are independent and can be done first since they are simpler.

Recommended order: **S-1 → S-2 → S-3+S-5 → S-4**

---

## S-1 — Nominatim Contact Email via Env Var

**File:** `hill-finder/app/services/geocoding.py`  
**Also:** `hill-finder/.env.example`

### Problem

`NOMINATIM_USER_AGENT = "HillFinder/0.1 (contact@email.com)"` is hardcoded with a placeholder. Nominatim's usage policy requires a real contact address; a placeholder risks request blocks.

### Implementation

Replace the hardcoded constant with a startup-time read from the environment:

```python
import os
import httpx
from fastapi import HTTPException

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT = 10.0
_contact = os.getenv("NOMINATIM_CONTACT_EMAIL", "contact@example.com")
NOMINATIM_USER_AGENT = f"HillFinder/0.1 ({_contact})"
```

Add to `.env.example`:

```
ORS_API_KEY=your_openrouteservice_api_key_here
NOMINATIM_CONTACT_EMAIL=your_email@example.com
```

### Test impact

No existing tests cover the User-Agent header. The S-1 fix is verified manually by inspecting the header value at startup (or via a unit test in the T-1 batch added in the test coverage sprint).

---

## S-2 — Nominatim Rate Limiter (1 req/sec)

**File:** `hill-finder/app/services/geocoding.py`

### Problem

Nominatim enforces 1 request/second globally. Concurrent FastAPI requests will violate this, risking a block.

### Implementation

Add a module-level async rate limiter. The lock serialises callers; the sleep inside the lock enforces the minimum inter-request interval.

```python
import asyncio
import time

_nominatim_lock = asyncio.Lock()
_last_nominatim_call: float = 0.0
NOMINATIM_MIN_INTERVAL = 1.0  # seconds — Nominatim usage policy


async def _rate_limit_nominatim() -> None:
    global _last_nominatim_call
    async with _nominatim_lock:
        elapsed = time.monotonic() - _last_nominatim_call
        if elapsed < NOMINATIM_MIN_INTERVAL:
            await asyncio.sleep(NOMINATIM_MIN_INTERVAL - elapsed)
        _last_nominatim_call = time.monotonic()
```

Call `await _rate_limit_nominatim()` as the first line inside `geocode_address`, before the `client.get()` call.

### Why this design

- `asyncio.Lock` ensures only one coroutine at a time reads/writes `_last_nominatim_call`.
- The sleep is inside the lock, so concurrent callers queue and each waits its turn — total throughput is capped at 1 req/sec regardless of concurrency.
- `time.monotonic()` avoids wall-clock drift issues.

### Test impact

The rate limiter is opaque to existing tests (they don't mock time). A new unit test for S-2 should monkeypatch `time.monotonic` and `asyncio.sleep` to assert the sleep is called with the correct remaining interval.

---

## S-3 + S-5 — Structured Logging (with API Key Masking)

**Files:** `hill-finder/app/main.py`, `geocoding.py`, `overpass.py`, `elevation.py`, `app/routers/hills.py`

### Problem (S-3)

No `logging` calls exist anywhere. Errors caught by the service layer produce HTTP status codes with no server-side record of what failed, which address was searched, or how many ways were returned. Debugging against live external APIs without logs is painful.

### Problem (S-5)

When logging is added to `elevation.py`, the `Authorization: <api_key>` request header must not appear in any log statement. The ORS API key is a secret; logging it would expose it in any log aggregation system.

### Implementation

#### `main.py` — Configure logging at startup

Add before `app = FastAPI(...)`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
```

This configures the root logger. Each module uses `logging.getLogger(__name__)` so log records carry their module name (`app.services.geocoding`, etc.).

---

#### `geocoding.py` — Log geocode lifecycle

```python
import logging
logger = logging.getLogger(__name__)
```

Inside `geocode_address`:

- Before request: `logger.info("Geocoding address: %r", address)`
- On timeout: `logger.warning("Nominatim timed out for address: %r", address)` (before re-raise)
- On HTTP error: `logger.warning("Nominatim HTTP error for address: %r", address)` (before re-raise)
- On request error: `logger.warning("Nominatim unreachable for address: %r", address)` (before re-raise)
- On empty result: `logger.warning("No geocoding result for address: %r", address)` (before raise)
- On success: `logger.info("Geocoded %r → (%.6f, %.6f)", address, lat, lon)`

---

#### `overpass.py` — Log way fetch lifecycle

```python
import logging
logger = logging.getLogger(__name__)
```

Inside `fetch_ways`:

- Before request: `logger.info("Fetching ways at (%.6f, %.6f) radius=%dm", lat, lon, radius_m)`
- On timeout: `logger.warning("Overpass timed out at (%.6f, %.6f)", lat, lon)` (before re-raise)
- On HTTP error: `logger.warning("Overpass HTTP error at (%.6f, %.6f)", lat, lon)` (before re-raise)
- On request error: `logger.warning("Overpass unreachable", exc_info=True)` (before re-raise)
- On ValueError (JSON parse): `logger.error("Failed to parse Overpass response")` (before re-raise)
- After filtering: `logger.info("Overpass returned %d ways after geometry filter", len(ways))`

---

#### `elevation.py` — Log ORS calls WITHOUT logging headers (S-5)

```python
import logging
logger = logging.getLogger(__name__)
```

Inside `_get_elevations_ors`:

- Before chunking: `logger.info("Fetching elevations: %d coordinates in %d chunk(s)", len(coordinates), len(chunks))`
- Per chunk (inside loop):
  ```python
  logger.info("ORS elevation chunk %d/%d: %d points → %s", i + 1, len(chunks), len(chunk), ORS_ELEVATION_URL)
  ```
  **Never log `api_key`, `headers`, or any variable that holds the key value.**
- On 429: `logger.warning("ORS elevation rate limit hit on chunk %d/%d", i + 1, len(chunks))` (before re-raise)
- On timeout: `logger.warning("ORS elevation timed out on chunk %d/%d", i + 1, len(chunks))` (before re-raise)
- On HTTP error: `logger.warning("ORS elevation HTTP error on chunk %d/%d", i + 1, len(chunks))` (before re-raise)
- On KeyError/IndexError from response parse: `logger.error("ORS elevation unexpected response format on chunk %d/%d", i + 1, len(chunks))` (before re-raise)
- After reassembly: `logger.info("Elevation fetch complete: %d points returned", len(all_elevations))`

**S-5 rule:** The only variables logged in `elevation.py` are: chunk index, chunk count, coordinate count, and the URL constant. The `api_key` variable and the `headers` dict are never passed to any logger.

---

#### `hills.py` (router) — Log request lifecycle

```python
import logging
logger = logging.getLogger(__name__)
```

Inside `get_hills`:

- Start: `logger.info("GET /hills/ address=%r radius_m=%d", address, radius_m)`
- After fetch_ways: already logged in overpass.py (no duplication needed)
- If ways truncated by S-4 cap: `logger.warning("Way count capped: %d → %d", original_count, len(ways))`
- Before return: `logger.info("Returning %d hills for address=%r", len(results), address)`

---

## S-4 — Cap on Ways Processed Per Request

**File:** `hill-finder/app/routers/hills.py`  
**Also:** `hill-finder/.env.example`

### Problem

A 10 km radius in a dense urban area can return thousands of OSM ways. All coordinates are flattened and sent to ORS in chunks with no upper bound. A single request could generate dozens of chunked ORS API calls, imposing latency, ORS quota burn, and a potential abuse vector.

### Implementation

Add a configurable cap in the router. Load it once from the environment at module import time:

```python
import os

_MAX_WAYS = int(os.getenv("HILLFINDER_MAX_WAYS", "200"))
```

After `ways = await fetch_ways(...)`, apply the cap:

```python
if len(ways) > _MAX_WAYS:
    logger.warning(
        "Way count capped: %d → %d (set HILLFINDER_MAX_WAYS to change)",
        len(ways),
        _MAX_WAYS,
    )
    ways = ways[:_MAX_WAYS]
```

Add to `.env.example`:

```
HILLFINDER_MAX_WAYS=200
```

### Notes

- Default 200 ways × ~20 coords/way = ~4000 coordinates → 8 ORS chunks. This is a reasonable upper bound for a 3 km radius search.
- The cap is applied after Overpass filters but before the elevation call, so it reduces both ORS quota usage and response latency.
- Ways are returned by Overpass without a grade-based ranking; the cap is arbitrary (first 200 returned). Sprint 4's scoring pass can make truncation smarter if needed.

---

## File Change Summary

| File | Changes |
|------|---------|
| `app/main.py` | Add `logging.basicConfig(...)` before `app = FastAPI(...)` |
| `app/services/geocoding.py` | Add `os` import, env-driven user agent, `asyncio`/`time` imports, `_rate_limit_nominatim()`, log statements |
| `app/services/overpass.py` | Add `logging` import + `logger`, log statements in `fetch_ways` |
| `app/services/elevation.py` | Add `logging` import + `logger`, log statements in `_get_elevations_ors` (never log headers or key) |
| `app/routers/hills.py` | Add `os` import, `_MAX_WAYS` constant, cap + warning after `fetch_ways`, log statements |
| `.env.example` | Add `NOMINATIM_CONTACT_EMAIL` and `HILLFINDER_MAX_WAYS` |

---

## Verification Checklist

After implementation, verify each item manually before committing:

- [ ] **S-1**: `python -c "from app.services.geocoding import NOMINATIM_USER_AGENT; print(NOMINATIM_USER_AGENT)"` — should reflect env var value, not `contact@email.com`
- [ ] **S-2**: Start server; fire two concurrent requests and confirm second request waits ≥1 second (check log timestamps on Nominatim geocode lines)
- [ ] **S-3**: Start server; hit `/hills/?address=Philadelphia,PA` with the ORS key missing — confirm WARNING logs appear in the console before the 500 is returned
- [ ] **S-4**: Set `HILLFINDER_MAX_WAYS=5` in `.env`; hit a dense address — confirm log line `"Way count capped: N → 5"` appears
- [ ] **S-5**: Grep log output for the ORS API key value — must not appear: `grep -i "Bearer\|Authorization\|api_key" <log output>`

---

## Out of Scope

These related improvements are deferred:

| Item | Deferred to |
|------|-------------|
| Unit tests for rate limiter and log output | T-1 through T-4 test coverage batch |
| Structured JSON logging (for log aggregators) | Post-MVP |
| Nominatim caching (prevents repeated geocodes for same address) | Sprint 4 alongside DuckDB |
| ORS quota monitoring / per-user rate limiting | Post-MVP |
