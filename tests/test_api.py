"""API-level smoke tests using httpx (no browser needed).

Requires a running WizzardChat server. Set env vars before running:
    WIZZARDCHAT_URL  (default: http://127.0.0.1:8091)
    WIZZARDCHAT_ADMIN_USER  (default: admin)
    WIZZARDCHAT_ADMIN_PASS  (required)
"""

import os
import httpx
import pytest

BASE_URL = os.getenv("WIZZARDCHAT_URL", "http://127.0.0.1:8091")
ADMIN_USER = os.getenv("WIZZARDCHAT_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("WIZZARDCHAT_ADMIN_PASS")

if not ADMIN_PASS:
    pytest.skip(
        "WIZZARDCHAT_ADMIN_PASS env var not set — skipping integration tests",
        allow_module_level=True,
    )


@pytest.fixture(scope="module")
def token() -> str:
    resp = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ──── Health ────

def test_health():
    r = httpx.get(f"{BASE_URL}/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ──── Auth ────

def test_login_success():
    r = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["user"]["username"] == "admin"


def test_login_invalid():
    r = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        data={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401


def test_me(token):
    r = httpx.get(f"{BASE_URL}/api/v1/auth/me", headers=_headers(token))
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


# ──── Auth required on protected endpoints ────

@pytest.mark.parametrize("endpoint", [
    "/api/v1/users",
    "/api/v1/flows",
    "/api/v1/queues",
    "/api/v1/contacts",
    "/api/v1/campaigns",
    "/api/v1/teams",
    "/api/v1/settings",
])
def test_unauthenticated_rejected(endpoint):
    """All resource endpoints must reject requests without a Bearer token."""
    r = httpx.get(f"{BASE_URL}{endpoint}")
    assert r.status_code == 401, f"{endpoint} returned {r.status_code} without auth"


# ──── Flows CRUD ────

def test_flows_crud(token):
    h = _headers(token)

    # Create
    r = httpx.post(f"{BASE_URL}/api/v1/flows", headers=h, json={
        "name": "Test Flow", "channel": "voice", "description": "E2E test"
    })
    assert r.status_code == 201
    flow = r.json()
    flow_id = flow["id"]
    assert flow["name"] == "Test Flow"

    # List
    r = httpx.get(f"{BASE_URL}/api/v1/flows", headers=h)
    assert r.status_code == 200
    assert any(f["id"] == flow_id for f in r.json())

    # Get
    r = httpx.get(f"{BASE_URL}/api/v1/flows/{flow_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == flow_id

    # Update
    r = httpx.patch(f"{BASE_URL}/api/v1/flows/{flow_id}", headers=h, json={
        "name": "Renamed Flow"
    })
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed Flow"

    # Delete
    r = httpx.delete(f"{BASE_URL}/api/v1/flows/{flow_id}", headers=h)
    assert r.status_code == 204


# ──── Settings ────

def test_settings_list(token):
    h = _headers(token)
    r = httpx.get(f"{BASE_URL}/api/v1/settings", headers=h)
    assert r.status_code == 200
    settings = r.json()
    keys = [s["key"] for s in settings]
    assert "locale" in keys
    assert "timezone" in keys


def test_settings_update_admin(token):
    h = _headers(token)
    r = httpx.put(f"{BASE_URL}/api/v1/settings/locale", headers=h, json={"value": "en-US"})
    assert r.status_code == 200
    assert r.json()["value"] == "en-US"
    # Reset
    httpx.put(f"{BASE_URL}/api/v1/settings/locale", headers=h, json={"value": "en-ZA"})


# ──── Register requires admin ────

def test_register_rejects_unauthenticated():
    r = httpx.post(f"{BASE_URL}/api/v1/auth/register", json={
        "email": "hacker@example.com",
        "username": "hacker",
        "password": "password123",
        "full_name": "Hacker",
        "role": "agent",
    })
    assert r.status_code == 401, "Register should require authentication"
