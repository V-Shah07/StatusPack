import importlib

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("STATUSPACK_DB_PATH", str(tmp_path / "app.db"))
    # Ensure Discord stays a no-op regardless of any real .env on the machine.
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "your_discord_webhook_url_here")
    import statuspack.app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


def test_healthz(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_webhook_opens_and_resolves_incident(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    fail = client.post(
        "/webhook/datadog",
        json={
            "transition": "Triggered",
            "tags": "service:httpbin-canary,statuspack:true",
            "monitor_id": "319919697",
            "title": "[Triggered] canary",
        },
    )
    assert fail.status_code == 200
    body = fail.json()
    assert body["action"] == "opened"
    assert body["service"] == "httpbin-canary"
    assert body["received_at"]  # timestamp stamped on receipt
    assert body["discord_delivered"] is False  # dummy webhook -> skipped

    recover = client.post(
        "/webhook/datadog",
        json={"transition": "Recovered", "tags": "service:httpbin-canary"},
    )
    assert recover.json()["action"] == "resolved"


def test_webhook_recovery_without_open_incident(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = client.post(
        "/webhook/datadog",
        json={"transition": "Recovered", "tags": "service:ghost"},
    )
    assert r.json()["action"] == "no_open_incident"
