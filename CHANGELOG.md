# Changelog

All notable changes to HillFinder are documented here.

## [0.1.0.0] - 2026-05-28

### Added
- Leaflet map frontend (`frontend/index.html`) — interactive sidebar + map UI showing nearby hills ranked by steepness, with color-coded grade overlays and clickable segment cards
- `GET /` route serves the frontend HTML directly from the API server; excluded from OpenAPI schema
- `NOMINATIM_TIMEOUT_S` environment variable for configurable geocoding timeout
- OpenAPI error responses documented on `GET /hills/` (400, 429, 502, 504)

### Fixed
- Hardcoded `NOMINATIM_TIMEOUT = 10.0` replaced with env-var-driven `NOMINATIM_TIMEOUT_S`
- XSS risk in frontend card rendering — `hill.name` (raw OSM data) now HTML-escaped via `escHtml()` before insertion into `innerHTML`
- `GET /` returning 404 — frontend was built but no route wired it up

### Added (developer tooling)
- `run_server.py` — PORT-env-aware server launcher for Claude Code preview tool
- Regression test (`tests/test_frontend_route_regression_001.py`) covering `GET /` → 200 HTML and schema exclusion
