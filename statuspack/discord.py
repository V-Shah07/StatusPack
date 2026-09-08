"""Forward a formatted alert to a Discord webhook.

If DISCORD_WEBHOOK_URL is unset or still the placeholder, this becomes a no-op
that reports it was skipped — so the rest of the pipeline runs unchanged with a
dummy value, and flips to real delivery the moment a real URL is provided.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from statuspack.config import read_env

_PLACEHOLDER_MARKERS = ("your_discord_webhook_url", "placeholder", "example.com/webhook")


@dataclass
class DiscordResult:
    delivered: bool
    status_code: int | None
    reason: str


def _webhook_url() -> str:
    return read_env("DISCORD_WEBHOOK_URL").strip()


def is_configured(url: str | None = None) -> bool:
    url = url if url is not None else _webhook_url()
    if not url or not url.startswith("http"):
        return False
    return not any(marker in url.lower() for marker in _PLACEHOLDER_MARKERS)


def format_alert(service: str, transition: str, url: str, detail: str | None = None) -> str:
    emoji = "🔴" if transition.lower() in {"triggered", "alert", "re-triggered"} else "🟢"
    lines = [f"{emoji} **{service}** — {transition}", f"URL: {url}"]
    if detail:
        lines.append(detail)
    return "\n".join(lines)


def send_alert(
    service: str,
    transition: str,
    url: str,
    detail: str | None = None,
    *,
    webhook_url: str | None = None,
    session: requests.Session | None = None,
) -> DiscordResult:
    resolved = webhook_url if webhook_url is not None else _webhook_url()
    content = format_alert(service, transition, url, detail)
    if not is_configured(resolved):
        return DiscordResult(
            delivered=False,
            status_code=None,
            reason="DISCORD_WEBHOOK_URL not configured (dummy/placeholder); skipped.",
        )
    sess = session or requests
    resp = sess.post(resolved, json={"content": content}, timeout=15)
    delivered = 200 <= resp.status_code < 300
    return DiscordResult(
        delivered=delivered,
        status_code=resp.status_code,
        reason="delivered" if delivered else f"Discord returned HTTP {resp.status_code}",
    )
