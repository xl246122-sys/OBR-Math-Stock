from fastapi.testclient import TestClient
import pytest
from app.api import create_app
from app.config import Settings


@pytest.mark.parametrize("path", ["metrics", "signals", "outcomes", "alerts", "reports", "reports/2026-10-31", "universe", "positions", "fees"])
def test_monitoring_routes_require_auth(path):
    client = TestClient(create_app(Settings("x"*32)))
    assert client.get("/api/v1/"+path).status_code == 401


def test_public_shell_contains_no_credentials_or_sensitive_data():
    client = TestClient(create_app(Settings("private-token-value")))
    response = client.get("/")
    assert response.status_code == 200
    assert "private-token-value" not in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/v1/metrics", headers={"Authorization":"Bearer private-token-value"}).status_code == 503
