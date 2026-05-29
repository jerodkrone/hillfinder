# Regression: ISSUE-001 — GET / returned 404; frontend/index.html was never served
# Found by /qa on 2026-05-28
# Report: .gstack/qa-reports/qa-report-hillfinder-2026-05-28.md

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_root_serves_frontend_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"HillFinder" in response.content
    assert b"leaflet" in response.content.lower()


def test_root_not_in_openapi_schema(client):
    schema = client.get("/openapi.json").json()
    assert "/" not in schema["paths"]
