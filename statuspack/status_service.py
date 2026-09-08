"""Compute status-page data from real Datadog results + the SQLite incident log.

Pure summarization functions (unit-tested without network) plus a builder that
pulls live Datadog result history and assembles the template context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from statuspack.config import Config
from statuspack.datadog_client import DatadogClient
from statuspack.incidents import Incident, IncidentStore


@dataclass
class ServiceStatus:
    name: str
    url: str
    public_id: str | None
    ui_url: str | None
    operational: bool
    uptime_pct: float
    total_checks: int
    passed_checks: int
    latest_check_time: str | None
    latest_response_ms: float | None
    regions: list[str] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return "Operational" if self.operational else "Down"


def _check_epoch_s(result: dict[str, Any]) -> float:
    ms = result.get("check_time", 0) or 0
    return ms / 1000 if ms > 10_000_000_000 else ms


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Reduce a test's raw result list to status + uptime over the window."""
    total = len(results)
    passed = sum(1 for r in results if (r.get("result") or {}).get("passed") is True)
    uptime = round(100.0 * passed / total, 2) if total else 0.0

    latest = max(results, key=_check_epoch_s) if results else None
    latest_passed = None
    latest_time = None
    latest_ms = None
    regions: list[str] = sorted({r.get("probe_dc") for r in results if r.get("probe_dc")})
    if latest is not None:
        latest_passed = (latest.get("result") or {}).get("passed")
        latest_time = datetime.fromtimestamp(_check_epoch_s(latest), tz=UTC).isoformat()
        timings = (latest.get("result") or {}).get("timings") or {}
        latest_ms = timings.get("total")

    return {
        "total": total,
        "passed": passed,
        "uptime_pct": uptime,
        # Operational unless we have data and the most recent check failed.
        "operational": True if latest_passed is None else bool(latest_passed),
        "has_data": total > 0,
        "latest_check_time": latest_time,
        "latest_response_ms": latest_ms,
        "regions": regions,
    }


def build_service_statuses(config: Config, client: DatadogClient) -> list[ServiceStatus]:
    statuses: list[ServiceStatus] = []
    for target in config.services:
        existing = client.find_managed_test(target.name)
        public_id = existing["public_id"] if existing else None
        results = client.get_test_results(public_id) if public_id else []
        s = summarize_results(results)
        statuses.append(
            ServiceStatus(
                name=target.name,
                url=target.url,
                public_id=public_id,
                ui_url=client.synthetics_ui_url(public_id) if public_id else None,
                operational=s["operational"],
                uptime_pct=s["uptime_pct"],
                total_checks=s["total"],
                passed_checks=s["passed"],
                latest_check_time=s["latest_check_time"],
                latest_response_ms=s["latest_response_ms"],
                regions=s["regions"] or list(target.locations),
            )
        )
    return statuses


def incident_duration_s(incident: Incident) -> float | None:
    if not incident.resolved_at:
        return None
    try:
        start = datetime.fromisoformat(incident.started_at)
        end = datetime.fromisoformat(incident.resolved_at)
    except (TypeError, ValueError):
        return None
    return round((end - start).total_seconds(), 1)


def build_context(config: Config, client: DatadogClient, store: IncidentStore) -> dict[str, Any]:
    statuses = build_service_statuses(config, client)
    incidents = store.list_incidents(limit=50)
    all_up = all(s.operational for s in statuses) if statuses else True
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "all_operational": all_up,
        "overall_label": "All systems operational" if all_up else "Partial outage",
        "services": statuses,
        "incidents": incidents,
        "incident_duration_s": incident_duration_s,
    }
