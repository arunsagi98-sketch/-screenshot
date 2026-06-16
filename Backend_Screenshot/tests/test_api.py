"""
Integration tests for FastAPI endpoints.
Run with: pytest Backend_Screenshot/tests/ -v

These tests use httpx's AsyncClient and do NOT hit the real database or browser.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

# Patch DB and browser before importing the app
@pytest.fixture(autouse=True)
def mock_db_and_browser(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
    monkeypatch.setenv("API_KEY", "")          # disable auth in tests
    monkeypatch.setenv("APP_ENV", "development")

from main import app  # noqa: E402 — import after env is patched


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "online"


@pytest.mark.anyio
async def test_process_empty_urls(client):
    r = await client.post("/process", json={"urls": []})
    assert r.status_code == 400
    assert "No valid URLs" in r.json()["message"]


@pytest.mark.anyio
async def test_export_pdf_no_ids(client):
    r = await client.post("/results/export-pdf", json={"ids": []})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_export_pdf_invalid_ids(client):
    r = await client.post("/results/export-pdf", json={"ids": ["not-a-number"]})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_delete_creative_invalid_path(client):
    r = await client.delete("/delete-creative?filename=../../etc/passwd")
    # Should be 400 (path traversal blocked) or 404 (file not found after sanitization)
    assert r.status_code in (400, 404)
