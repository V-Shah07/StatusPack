"""Parse Datadog monitor webhook payloads.

Datadog webhooks send a JSON body we define in the monitor's webhook integration.
StatusPack configures the body to include these fields (Datadog template vars):

    {
      "transition": "$ALERT_TRANSITION",   # Triggered | Recovered | Re-Triggered | No Data
      "title":      "$EVENT_TITLE",
      "monitor_id": "$ALERT_ID",
      "tags":       "$TAGS",                # comma-separated, includes service:<name>
      "event_id":   "$ID",
      "date":       "$DATE"                 # epoch millis
    }

Parsing is pure so it can be unit-tested without a running server.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

TRIGGER_TRANSITIONS = {"triggered", "re-triggered", "alert", "warn", "no data"}
RECOVER_TRANSITIONS = {"recovered", "recovery", "ok"}


@dataclass
class ParsedAlert:
    service: str | None
    transition: str
    monitor_id: int | None
    public_id: str | None
    title: str | None
    is_failure: bool
    is_recovery: bool
    event_time: str | None  # ISO-8601 UTC if derivable


def _service_from_tags(tags: object) -> str | None:
    if isinstance(tags, str):
        parts = [t.strip() for t in tags.replace(" ", "").split(",") if t.strip()]
    elif isinstance(tags, list | tuple):
        parts = [str(t).strip() for t in tags]
    else:
        return None
    for p in parts:
        if p.startswith("service:"):
            return p.split(":", 1)[1]
    return None


def _to_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _event_time(value: object) -> str | None:
    """Datadog $DATE is epoch millis; accept seconds too."""
    ms = _to_int(value)
    if ms is None:
        return None
    # Heuristic: 13 digits -> millis, 10 digits -> seconds.
    secs = ms / 1000 if ms > 10_000_000_000 else ms
    try:
        return datetime.fromtimestamp(secs, tz=UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def parse_alert(payload: dict) -> ParsedAlert:
    transition_raw = str(payload.get("transition", "") or "").strip()
    transition_l = transition_raw.lower()
    service = payload.get("service") or _service_from_tags(payload.get("tags"))
    is_failure = transition_l in TRIGGER_TRANSITIONS
    is_recovery = transition_l in RECOVER_TRANSITIONS
    return ParsedAlert(
        service=str(service) if service else None,
        transition=transition_raw or "Unknown",
        monitor_id=_to_int(payload.get("monitor_id")),
        public_id=(str(payload["public_id"]) if payload.get("public_id") else None),
        title=(str(payload["title"]) if payload.get("title") else None),
        is_failure=is_failure,
        is_recovery=is_recovery,
        event_time=_event_time(payload.get("date")),
    )
