"""Phase 2 (last-mile) — prove the Datadog->app->incident-log->Discord hop.

This sandbox has no public inbound URL, so Datadog's monitor webhook cannot reach
our app directly. To prove that hop works, we POST the SAME payload shape Datadog
sends — built from the REAL incident recorded in evidence/phase2/incident.json —
into the actually-running FastAPI server over HTTP.

The SENDER here is a local injector, not Datadog; everything else (the HTTP
request reaching the app, incident open/resolve in SQLite, the receive-time
stamp, Discord forwarding) is the real production path. Discord is skipped while
its webhook is a placeholder.

Usage (server must be running, e.g. `uvicorn statuspack.app:app --port 8000`):
    python -m statuspack.phase2_local_webhook --url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests


def _epoch_ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def build_payloads(incident: dict) -> tuple[dict, dict]:
    service = incident["service"]
    monitor_id = incident["monitor_id"]
    public_id = incident["public_id"]
    tags = f"statuspack:true,service:{service},env:prod"
    triggered = {
        "transition": "Triggered",
        "title": f"[Triggered] StatusPack - {service}",
        "monitor_id": str(monitor_id),
        "public_id": public_id,
        "tags": tags,
        "date": str(_epoch_ms(incident["t_first_fail"])),
    }
    recovered = {
        "transition": "Recovered",
        "title": f"[Recovered] StatusPack - {service}",
        "monitor_id": str(monitor_id),
        "public_id": public_id,
        "tags": tags,
        "date": str(_epoch_ms(incident["t_recovered"])),
    }
    return triggered, recovered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--incident", default="evidence/phase2/incident.json")
    parser.add_argument("--out", default="evidence/phase2/app_webhook_proof.json")
    args = parser.parse_args(argv)

    incident = json.loads(Path(args.incident).read_text())
    triggered, recovered = build_payloads(incident)

    health = requests.get(f"{args.url}/healthz", timeout=10).json()
    r1 = requests.post(f"{args.url}/webhook/datadog", json=triggered, timeout=15).json()
    r2 = requests.post(f"{args.url}/webhook/datadog", json=recovered, timeout=15).json()

    proof = {
        "note": (
            "Payloads are Datadog's monitor-webhook shape, built from the real "
            "incident in incident.json and POSTed to the running app over HTTP by a "
            "LOCAL injector (Datadog cannot reach this sandbox). The app path — "
            "receive, parse, open/resolve incident, Discord forward — is the real one."
        ),
        "server_health": health,
        "sent_triggered": triggered,
        "app_response_triggered": r1,
        "sent_recovered": recovered,
        "app_response_recovered": r2,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(proof, indent=2, sort_keys=True))
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
