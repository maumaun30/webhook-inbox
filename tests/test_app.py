import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    monkeypatch.setenv("CRON_SECRET", "cron")
    monkeypatch.delenv("VERCEL", raising=False)
    db.reset_for_tests()
    yield TestClient(app)
    db.reset_for_tests()


AUTH = ("admin", "secret")


def test_capture_and_list(client):
    r = client.post("/hook/maya", json={"status": "PAYMENT_SUCCESS"})
    assert r.status_code == 200 and r.json()["ok"]
    hooks = client.get("/api/hooks", auth=AUTH).json()
    assert len(hooks) == 1 and hooks[0]["source"] == "maya"
    assert hooks[0]["signature_status"] == "unchecked"


def test_admin_requires_auth(client):
    assert client.get("/api/hooks").status_code == 401
    assert client.get("/").status_code == 401
    assert client.get("/", auth=AUTH).status_code == 200


def test_refuses_without_token_on_vercel(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    monkeypatch.setenv("VERCEL", "1")
    assert client.get("/api/hooks").status_code == 503


def test_invalid_source(client):
    assert client.post("/hook/Bad_Name!", content=b"x").status_code == 404


def test_shopify_signature(client, monkeypatch):
    monkeypatch.setenv("SECRET_SHOPIFY", "shh")
    body = b'{"id":1}'
    good = base64.b64encode(hmac.new(b"shh", body, hashlib.sha256).digest()).decode()
    client.post("/hook/shopify", content=body, headers={"X-Shopify-Hmac-Sha256": good})
    client.post("/hook/shopify", content=body, headers={"X-Shopify-Hmac-Sha256": "nope"})
    statuses = [h["signature_status"] for h in client.get("/api/hooks", auth=AUTH).json()]
    assert statuses == ["invalid", "valid"]


def test_github_style_signature(client, monkeypatch):
    monkeypatch.setenv("SECRET_GITHUB", "gh")
    body = b'{"ref":"main"}'
    sig = "sha256=" + hmac.new(b"gh", body, hashlib.sha256).hexdigest()
    client.post("/hook/github", content=body, headers={"X-Hub-Signature-256": sig})
    assert client.get("/api/hooks", auth=AUTH).json()[0]["signature_status"] == "valid"


def test_binary_body_roundtrip(client):
    raw = bytes(range(256))
    hook_id = client.post("/hook/bin", content=raw).json()["id"]
    hook = client.get(f"/api/hooks/{hook_id}", auth=AUTH).json()
    assert hook["body_is_base64"] and base64.b64decode(hook["body"]) == raw


def test_search_and_detail_and_delete(client):
    client.post("/hook/aiosell", json={"booking": "GS-1001"})
    client.post("/hook/aiosell", json={"booking": "GS-2002"})
    found = client.get("/api/hooks", params={"q": "GS-2002"}, auth=AUTH).json()
    assert len(found) == 1
    hid = found[0]["id"]
    page = client.get(f"/h/{hid}", auth=AUTH)
    assert page.status_code == 200 and "GS-2002" in page.text
    assert client.delete(f"/api/hooks/{hid}", auth=AUTH).json()["ok"]
    assert client.get(f"/api/hooks/{hid}", auth=AUTH).status_code == 404


def test_replay_unreachable_target(client):
    hid = client.post("/hook/maya", json={"a": 1}).json()["id"]
    r = client.post(f"/api/hooks/{hid}/replay", json={"target_url": "http://127.0.0.1:9/x"}, auth=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is False and "error" in r.json()


def test_keepalive(client):
    assert client.get("/api/cron/keepalive").status_code == 401
    r = client.get("/api/cron/keepalive", headers={"Authorization": "Bearer cron"})
    assert r.json() == {"ok": True}
