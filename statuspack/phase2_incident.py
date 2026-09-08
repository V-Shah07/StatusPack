"""Phase 2 — trigger a REAL synthetic failure and measure real paging latency.

What it does, against the live Datadog org:
  1. Re-points the `httpbin-canary` synthetic test at https://httpbin.org/status/503
     (the moment the "service goes down") and triggers it on demand.
  2. Polls Datadog until it observes the failure and the monitor transitions to
     Alert, recording the real timestamps:
        - t_break        : when we broke the endpoint (our action)
        - t_first_fail   : first failing synthetic result Datadog recorded
        - t_alert        : monitor last_triggered_ts (when Datadog would page)
  3. Restores the canary to /status/200 and waits for Datadog to record recovery
     (t_recovered) so Phase 3 has an accurate outage window.
  4. Writes evidence/phase2/incident.json — all real, from a real triggered failure.

The Datadog -> our-app webhook hop and the Discord delivery are exercised
separately/locally (see phase2_local_webhook.py) because this sandbox has no
public inbound URL and Discord is a placeholder for now.
"""

from __future__ import annotations

import dataclasses
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from statuspack.config import ServiceTarget, load_config
from statuspack.datadog_client import DatadogClient, build_api_test_payload

CANARY = "httpbin-canary"
BROKEN_URL = "https://httpbin.org/status/503"
HEALTHY_URL = "https://httpbin.org/status/200"
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 420


def _iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()


def _now_epoch() -> float:
    return datetime.now(UTC).timestamp()


def _set_canary_url(client: DatadogClient, target: ServiceTarget, url: str) -> None:
    payload = build_api_test_payload(
        dataclasses.replace(target, url=url),
        "StatusPack canary fault-injection (Phase 2).",
    )
    client.update_api_test(target_public_id(client, target.name), payload)


def target_public_id(client: DatadogClient, service: str) -> str:
    existing = client.find_managed_test(service)
    if not existing:
        raise RuntimeError(f"No managed test for {service}; run provisioning first.")
    return existing["public_id"]


def _first_failing_result_after(
    client: DatadogClient, public_id: str, after_epoch_s: float
) -> dict[str, Any] | None:
    for r in client.get_test_results(public_id):
        check_ms = r.get("check_time", 0)
        check_s = check_ms / 1000 if check_ms > 10_000_000_000 else check_ms
        if check_s < after_epoch_s - 5:
            continue
        passed = (r.get("result") or {}).get("passed")
        if passed is False:
            r["_check_epoch_s"] = check_s
            return r
    return None


def _monitor_triggered_after(
    client: DatadogClient, monitor_id: int, after_epoch_s: float
) -> float | None:
    mon = client.get_monitor(monitor_id)
    if mon.get("overall_state") not in {"Alert", "Warn"}:
        return None
    groups = (mon.get("state") or {}).get("groups") or {}
    best = None
    for g in groups.values():
        ts = g.get("last_triggered_ts")
        if ts and ts >= after_epoch_s - 5:
            best = max(best or ts, ts)
    return float(best) if best else None


def _monitor_resolved_after(
    client: DatadogClient, monitor_id: int, after_epoch_s: float
) -> float | None:
    mon = client.get_monitor(monitor_id)
    if mon.get("overall_state") not in {"OK"}:
        return None
    groups = (mon.get("state") or {}).get("groups") or {}
    best = None
    for g in groups.values():
        ts = g.get("last_resolved_ts")
        if ts and ts >= after_epoch_s - 5:
            best = max(best or ts, ts)
    return float(best) if best else None


def run(evidence_dir: Path) -> dict[str, Any]:
    config = load_config()
    client = DatadogClient(config.datadog)
    target = next(t for t in config.services if t.name == CANARY)
    public_id = target_public_id(client, CANARY)
    monitor_id = client.get_test(public_id)["monitor_id"]

    print(f"Canary {CANARY}: public_id={public_id} monitor_id={monitor_id}")
    evidence: dict[str, Any] = {
        "service": CANARY,
        "public_id": public_id,
        "monitor_id": monitor_id,
        "broken_url": BROKEN_URL,
    }

    try:
        # --- break it -----------------------------------------------------
        t_break = _now_epoch()
        evidence["t_break"] = _iso(t_break)
        print(f"[{evidence['t_break']}] breaking canary -> {BROKEN_URL}")
        _set_canary_url(client, target, BROKEN_URL)
        time.sleep(3)
        client.trigger_tests([public_id])

        # --- wait for Datadog to observe the failure ----------------------
        t_first_fail = None
        t_alert = None
        deadline = time.time() + POLL_TIMEOUT_S
        while time.time() < deadline:
            if t_first_fail is None:
                r = _first_failing_result_after(client, public_id, t_break)
                if r:
                    t_first_fail = r["_check_epoch_s"]
                    evidence["t_first_fail"] = _iso(t_first_fail)
                    evidence["failing_location"] = r.get("probe_dc")
                    print(
                        f"[{evidence['t_first_fail']}] Datadog recorded a FAILED check "
                        f"from {r.get('probe_dc')}"
                    )
            if t_alert is None:
                ts = _monitor_triggered_after(client, monitor_id, t_break)
                if ts:
                    t_alert = ts
                    evidence["t_alert"] = _iso(t_alert)
                    print(f"[{evidence['t_alert']}] Monitor TRIGGERED (Datadog would page now)")
            if t_first_fail and t_alert:
                break
            client.trigger_tests([public_id])
            time.sleep(POLL_INTERVAL_S)

        if t_first_fail:
            evidence["detection_latency_s"] = round(t_first_fail - t_break, 1)
        if t_alert:
            evidence["alert_latency_s"] = round(t_alert - t_break, 1)
            if t_first_fail:
                evidence["fail_to_alert_s"] = round(t_alert - t_first_fail, 1)
    finally:
        # --- always restore healthy --------------------------------------
        t_restore = _now_epoch()
        evidence["t_restore"] = _iso(t_restore)
        print(f"[{evidence['t_restore']}] restoring canary -> {HEALTHY_URL}")
        _set_canary_url(client, target, HEALTHY_URL)
        time.sleep(3)
        client.trigger_tests([public_id])

    # --- wait for recovery (best-effort) ----------------------------------
    deadline = time.time() + POLL_TIMEOUT_S
    while time.time() < deadline:
        ts = _monitor_resolved_after(client, monitor_id, t_restore)
        if ts:
            evidence["t_recovered"] = _iso(ts)
            print(f"[{evidence['t_recovered']}] Monitor RECOVERED")
            if "t_break" in evidence and "t_recovered" in evidence:
                evidence["outage_duration_s"] = round(ts - t_break, 1)
            break
        client.trigger_tests([public_id])
        time.sleep(POLL_INTERVAL_S)

    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "incident.json").write_text(json.dumps(evidence, indent=2, sort_keys=True))
    print("\nEvidence:\n" + json.dumps(evidence, indent=2, sort_keys=True))
    return evidence


if __name__ == "__main__":
    run(Path("evidence/phase2"))
