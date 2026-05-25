# HillFinder Sprint 1 — Code Review Report

**Date:** 2026-05-25  
**Scope:** `hill-finder/` against the Sprint 1 plan (geocode → Overpass → ORS elevation → grade computation → ranked JSON via FastAPI).  
**Verdict:** The core pipeline is implemented correctly and the stated design decisions are sound. Several findings warrant attention before Sprint 2 builds on this foundation.

---

## 1. Bugs / Logic Errors

**B-1 — `max_grade` counts steep descents, not just ascents** (`app/utils/geo.py:27`)

`pair_grade = abs(elev_diff) / dist * 100` — the `abs()` means a sharp downhill counts toward `grade_max_pct`. For a hill-finder the stated intent is "steepest consecutive node pair," which in a running context should mean uphill. This is a semantic mismatch with the model docstring. `grade_avg_pct` correctly counts only upward gain (`if elev_diff > 0`), but `grade_max_pct` does not follow the same logic.

**B-2 — `ValueError` from `compute_grades` is unhandled in the router** (`app/routers/hills.py:26–38`)

`compute_grades` raises `ValueError` for a length mismatch between `coords` and `elevations`. The router calls it without a try/except. If a chunking edge case ever produces a count mismatch, the client gets a raw 500 with a Python traceback detail. The Overpass `< 2` geometry filter prevents one known case, but the elevation-slice logic `all_elevations[start:end]` could silently produce the wrong count if `get_elevations` returns fewer points than expected (e.g., ORS drops a boundary point).

**B-3 — `_chunk_coordinates` degenerates for exact multiples of `chunk_size`** (`app/services/elevation.py:9–24`)

With 1000 coords and `chunk_size=500`: the loop produces 3 chunks (`[0:500]`, `[499:999]`, `[998:1000]`) instead of 2. The reassembly count is still correct (500 + 499 + 1 = 1000), but the third chunk contains only 2 points, wasting an ORS API round-trip. Not data-corrupting, but worth fixing before Sprint 4 adds caching keyed on chunk boundaries.

**B-4 — Empty `address` string is valid input** (`app/routers/hills.py:13`)

`address: str` has no `Query(min_length=1)` constraint. An empty string passes validation and hits Nominatim before failing with a 400. Easily fixed with a Query annotation.

---

## 2. Duplicate Code

**D-1 — `ORS_API_KEY` checked in two places** (`app/routers/hills.py:16–17`, `app/services/elevation.py:33–35`)

`os.getenv("ORS_API_KEY")` is called at the start of the router and again inside `_get_elevations_ors`. The second check is dead code in normal flow (router always fires first). The design decision to put it in the router was the right call — the `elevation.py` copy should be removed, or kept with a comment explaining it is a defense-in-depth fallback for callers that bypass the router.

**D-2 — `ORS_API_KEY` re-read from the environment on every request**

Related to D-1: even if both checks stay, the key is re-read from `os.environ` on every request rather than being loaded once at startup. For Sprint 4, a config object would prevent this pattern from spreading further.

---

## 3. Missing Error Handling

**E-1 — ORS response `KeyError` is unhandled** (`app/services/elevation.py:57`)

`result["geometry"]["coordinates"]` — if ORS returns a malformed or unexpected JSON structure (missing `geometry` or `coordinates` key), the `KeyError` propagates as an unhandled 500. The `except Exception` in `overpass.py` handles this for Overpass, but `elevation.py` has no analogous catch.

**E-2 — Bare `except Exception` in `overpass.py` is too broad** (`app/services/overpass.py:38`)

The intended purpose is catching `json.JSONDecodeError`, but it also silently swallows unexpected runtime errors like `AttributeError` and labels them "Failed to parse Overpass response," making debugging difficult. Should be narrowed to `except (ValueError, KeyError)` or `json.JSONDecodeError` specifically.

**E-3 — No guard for zero-length ways in the ranked output** (`app/utils/geo.py:31`, `app/routers/hills.py`)

`compute_total_length_m` returns `0.0` for coincident points; `compute_grades` returns `(0.0, 0.0)` for zero distance. These produce `HillSegment(length_m=0.0, grade_avg_pct=0.0, ...)` entries that appear at the bottom of the ranked output. Sprint 2's min-grade filter will catch most of these, but there is no guard at the data layer.

---

## 4. Missing Tests

**T-1 — `geocoding.py` has zero tests**

No coverage for: successful geocoding, empty result → 400, timeout → 504, HTTP error → 502, connection error → 502.

**T-2 — `overpass.py` has zero tests**

No coverage for: way parsing, `_classify_surface` logic (6 surface tag values × 2 highway-type fallback paths), minimum geometry filter (nodes < 2 skipped), Overpass error responses.

**T-3 — `get_elevations` / `_get_elevations_ors` have no tests**

Only `_chunk_coordinates` is tested. The actual HTTP interaction, coordinate-order transformation (`[lon, lat]` GeoJSON), 429 handling, timeout handling, and multi-chunk reassembly are all untested.

**T-4 — Router integration tests are minimal**

Two tests exist: OpenAPI docs and missing API key. No coverage for: valid end-to-end pipeline (mocked HTTP), empty `ways` returning `[]`, geocoding failure propagating correctly, Overpass failure propagating correctly, elevation failure propagating correctly, result sort order.

**T-5 — `compute_grades` edge cases not covered**

No test for: exactly 2 points (minimum valid input), all-downhill segment (avg=0, max>0 under current abs logic), the `coordinates`/`elevations` length-mismatch `ValueError`.

**T-6 — Tests live in `conftest.py`** (`tests/conftest.py:13–20`)

`test_openapi_docs_available` and `test_missing_ors_key_returns_500` are defined in `conftest.py`. This works but is unconventional — `conftest.py` is for fixtures. If test discovery assumptions change (e.g., a CI runner with a non-standard pytest config), these tests could be silently skipped. They belong in `tests/test_main.py`.

---

## 5. Security / Logging Hygiene

**S-1 — Nominatim User-Agent contains a placeholder email** (`app/services/geocoding.py:6`)

`"HillFinder/0.1 (contact@email.com)"` — Nominatim's usage policy requires a real contact address. Using a placeholder can result in blocked requests or policy violations. This should be configurable via an env var (e.g., `NOMINATIM_CONTACT_EMAIL`).

**S-2 — No rate limiting on Nominatim calls** (`app/services/geocoding.py`)

Nominatim enforces a 1 request/second policy. Concurrent FastAPI requests will violate this. No throttle, queue, or semaphore is in place.

**S-3 — No logging anywhere in the codebase**

There is no `logging` usage in any module. No request-level logging (address searched, radius, way count returned), no error-path logging, no ORS call logging. When something fails in a deployed environment, the only signal is the HTTP status code. At minimum, errors caught in the service layer should be logged at `WARNING`/`ERROR` level before re-raising.

**S-4 — No cap on ways processed per request** (`app/routers/hills.py`)

A 10 km radius in a dense urban area can return thousands of OSM ways. All coordinates are flattened and sent to ORS in chunks, but there is no upper bound on the number of ways or total coordinate count. A single request could generate dozens of chunked ORS API calls, making this both a latency and a potential abuse vector.

**S-5 — ORS API key log-masking** (`app/services/elevation.py`)

Not a current issue since there are no logs, but when logging is added (S-3), care must be taken not to log request headers that include the `Authorization: <api_key>` value.

---

## 6. Minor / Code Quality

**Q-1 — Bottom import in `main.py` is a code smell** (`app/main.py:17–18`)

`from app.routers import hills` is placed after `app = FastAPI(...)` with `# noqa: E402` to suppress the linting warning. This is done to avoid a circular import, but the router does not import `app` directly — it reads `request.app.state.http_client` at request time. The circular import concern appears unfounded; standard top-of-file import ordering should work.

**Q-2 — `tags` dict is dead data** (`app/services/overpass.py:52`, `app/routers/hills.py`)

`fetch_ways` includes `"tags": tags` in each way dict, but the router never reads it. Either remove it from the returned dict, or leave it with a note that Sprint 2 will use it for `access` tag filtering on private roads.

**Q-3 — Weak type hints in `elevation.py`** (`app/services/elevation.py:9, 29`)

`_chunk_coordinates(coordinates: list, ...)` and `get_elevations(coordinates: list, ...)` use bare `list`. Should be `list[tuple[float, float]]` for consistency with the rest of the codebase.

**Q-4 — `HillSegment.name` should default to `None`** (`app/models/hill.py:6`)

`name: str | None` without a default makes it a required field in Pydantic v2 (callers must explicitly pass `name=None`). The router does pass it, but `name: str | None = None` better expresses intent and is safer for future deserialization contexts.

**Q-5 — `surface` field is unvalidated** (`app/models/hill.py:9`)

`surface: str` accepts any string at the model boundary. Using `Literal["road", "trail", "unknown"]` would enforce the three values produced by `_classify_surface` and catch regressions if that function is modified.

---

## Summary Table

| ID | Category | Severity | Location |
|----|----------|----------|----------|
| B-1 | Bug | Medium | `app/utils/geo.py:27` |
| B-2 | Bug | Medium | `app/routers/hills.py:26–38` |
| B-3 | Bug | Low | `app/services/elevation.py:9–24` |
| B-4 | Bug | Low | `app/routers/hills.py:13` |
| D-1 | Duplicate | Low | `hills.py` + `elevation.py` |
| D-2 | Duplicate | Low | `hills.py` + `elevation.py` |
| E-1 | Error handling | Medium | `app/services/elevation.py:57` |
| E-2 | Error handling | Low | `app/services/overpass.py:38` |
| E-3 | Error handling | Low | `app/utils/geo.py:31` |
| T-1 | Test coverage | High | `app/services/geocoding.py` |
| T-2 | Test coverage | High | `app/services/overpass.py` |
| T-3 | Test coverage | High | `app/services/elevation.py` |
| T-4 | Test coverage | High | `app/routers/hills.py` |
| T-5 | Test coverage | Medium | `app/utils/geo.py` |
| T-6 | Test coverage | Low | `tests/conftest.py` |
| S-1 | Security | Medium | `app/services/geocoding.py:6` |
| S-2 | Security | Medium | `app/services/geocoding.py` |
| S-3 | Logging | High | all services |
| S-4 | Security | Low | `app/routers/hills.py` |
| S-5 | Security | Low | `app/services/elevation.py` |
| Q-1 | Code quality | Low | `app/main.py:17–18` |
| Q-2 | Code quality | Low | `app/services/overpass.py:52` |
| Q-3 | Code quality | Low | `app/services/elevation.py:9, 29` |
| Q-4 | Code quality | Low | `app/models/hill.py:6` |
| Q-5 | Code quality | Low | `app/models/hill.py:9` |

---

## Recommended Priority Before Sprint 2

1. **T-1 through T-4** — Test coverage gaps will make Sprint 2's `respx` mock work harder to add safely. The service layer needs unit tests with mocked HTTP before new logic is built on top.
2. **S-3** — Add structured logging to all service modules. Debugging against live external APIs without logs is painful; Sprint 2 will add more failure modes.
3. **B-1** — `grade_max_pct` semantics affect the correctness of the ranked output. Decide whether max grade should be uphill-only or absolute before Sprint 2 adds segment splitting that depends on grade thresholds.
4. **S-1** — Replace the placeholder Nominatim email before any shared or deployed use.
