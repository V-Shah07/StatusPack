"""StatusPack FastAPI app.

Routes:
  GET  /                  -> public status page (Phase 3)
  GET  /healthz           -> liveness
  POST /webhook/datadog   -> receives Datadog monitor alerts (Phase 2)

The webhook records an incident (open on failure, resolve on recovery), stamps
the receive time (for the paging-latency measurement), forwards to Discord, and
— from Phase 4 — attaches an LLM incident summary.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from statuspack import discord
from statuspack.config import load_config
from statuspack.datadog_client import DatadogClient
from statuspack.incidents import IncidentStore
from statuspack.status_service import build_context
from statuspack.webhook import parse_alert

app = FastAPI(title="StatusPack", version="0.1.0")

_TEMPLATES = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


def render_status_page(db_path: str | None = None) -> str:
    """Render the status page HTML from live Datadog results + the incident log."""
    config = load_config()
    client = DatadogClient(config.datadog)
    store = IncidentStore(db_path or _db_path())
    context = build_context(config, client, store)
    return _TEMPLATES.get_template("status.html").render(**context)


def _db_path() -> str:
    return os.environ.get("STATUSPACK_DB_PATH", "statuspack.db")


def get_store() -> IncidentStore:
    return IncidentStore(_db_path())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "time": datetime.now(UTC).isoformat()}


@app.post("/webhook/datadog")
async def datadog_webhook(request: Request) -> JSONResponse:
    received_at = datetime.now(UTC).isoformat()
    try:
        payload = await request.json()
    except Exception:
        body = (await request.body()).decode("utf-8", "replace")
        payload = {"_raw": body}

    alert = parse_alert(payload if isinstance(payload, dict) else {})
    store = get_store()
    service = alert.service or "unknown"

    action = "ignored"
    incident_id: int | None = None
    if alert.is_failure:
        incident_id = store.open_incident(
            service,
            public_id=alert.public_id,
            monitor_id=alert.monitor_id,
            started_at=alert.event_time or received_at,
            alert_transition=alert.transition,
            raw_alert=json.dumps(payload),
        )
        action = "opened"
    elif alert.is_recovery:
        incident_id = store.resolve_incident(service, resolved_at=alert.event_time or received_at)
        action = "resolved" if incident_id else "no_open_incident"

    # Forward to Discord (no-op if the webhook URL is still a dummy).
    detail = alert.title or (f"transition={alert.transition}")
    dr = discord.send_alert(service, alert.transition, alert.public_id or service, detail)

    return JSONResponse(
        {
            "received_at": received_at,
            "service": service,
            "transition": alert.transition,
            "action": action,
            "incident_id": incident_id,
            "discord_delivered": dr.delivered,
            "discord_reason": dr.reason,
        }
    )


@app.get("/", response_class=HTMLResponse)
def status_page() -> HTMLResponse:
    try:
        return HTMLResponse(render_status_page())
    except Exception as exc:  # pragma: no cover - defensive; surfaced on the page
        return HTMLResponse(
            f"<h1>StatusPack</h1><p>Could not render status: {exc}</p>", status_code=500
        )
