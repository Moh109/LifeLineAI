import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import config
from app.main import app

client = TestClient(app)  # no "with": the app doesn't start or touch the database


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setattr(config, "DISPATCH_KEY", "test-key-123")


@pytest.mark.parametrize("method,path", [
    ("get", "/api/cases"), ("get", "/api/cases/1"), ("get", "/api/stats"),
    ("post", "/api/cases/1/assign"), ("post", "/api/cases/1/status"), ("post", "/api/cases/1/location"),
    ("post", "/api/cases/1/callback"), ("post", "/api/intake/text"),
    ("post", "/api/demo/surge"), ("post", "/api/demo/reset"),
])
def test_dashboard_routes_need_the_key(method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"X-Dispatch-Key": "wrong"}).status_code == 401


def test_health_stays_open():
    assert client.get("/api/health").status_code == 200


def test_tool_routes_keep_their_own_secret():
    r = client.post("/tools/lookup_caller", json={})
    assert r.json().get("detail") != "dispatch key required"


def test_websocket_refused_without_key():
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws?key=wrong") as ws:
            ws.receive_text()
