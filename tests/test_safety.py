import pytest
from fastapi.testclient import TestClient
from app.api import create_app
from app.config import Settings


def test_fail_closed(monkeypatch):
    monkeypatch.setenv("OBR_API_TOKEN", "x" * 32)
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_missing_token(monkeypatch):
    monkeypatch.delenv("OBR_API_TOKEN", raising=False)
    with pytest.raises(ValueError):
        Settings.from_env()


def test_paper_required(monkeypatch):
    monkeypatch.setenv("PAPER_MODE", "false")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_api_auth_and_truthful_status():
    client = TestClient(create_app(Settings("x" * 32)))
    assert client.get("/healthz").json() == {"alive": True}
    assert client.get("/api/v1/status").status_code == 401
    assert client.get("/api/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.get("/api/v1/status", headers={"Authorization": "Bearer " + "x" * 32})
    assert response.json()["live_trading_enabled"] is False
    assert response.json()["mode"] == "WATCH_ONLY"
