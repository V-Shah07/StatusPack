"""Phase 1 — provision real Datadog Synthetic tests from services.yaml.

Idempotent: matches existing tests by the `statuspack:true` + `service:<name>`
tags and updates them in place instead of creating duplicates.

Usage:
    python -m statuspack.provision                 # provision / update all
    python -m statuspack.provision --dry-run       # print payloads, no API calls
    python -m statuspack.provision --evidence-dir evidence/phase1

Writes one JSON file per service (the raw Datadog API response) plus a summary
to the evidence directory, so the PROVE IT artifact is a real committed response.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from statuspack.config import Config, load_config
from statuspack.datadog_client import DatadogClient, build_api_test_payload


def _notification_message() -> str:
    # Monitors (Phase 2) render this; the @webhook handle is wired up there.
    return "StatusPack synthetic check failed. See the status page and Discord alert for details."


def provision(
    config: Config,
    client: DatadogClient,
    evidence_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Create-or-update a synthetic test for every configured service.

    Returns a list of result records (one per service) describing what happened.
    """
    results: list[dict[str, Any]] = []
    for target in config.services:
        payload = build_api_test_payload(target, _notification_message())
        existing = client.find_managed_test(target.name)
        if existing:
            public_id = existing["public_id"]
            response = client.update_api_test(public_id, payload)
            action = "updated"
        else:
            response = client.create_api_test(payload)
            public_id = response["public_id"]
            action = "created"

        record = {
            "service": target.name,
            "action": action,
            "public_id": public_id,
            "url": target.url,
            "locations": list(target.locations),
            "tags": target.tags,
            "ui_url": client.synthetics_ui_url(public_id),
            "response": response,
        }
        results.append(record)
        print(f"[{action}] {target.name} -> {public_id}  ({target.url})")

        if evidence_dir is not None:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            out = evidence_dir / f"{target.name}.json"
            out.write_text(json.dumps(response, indent=2, sort_keys=True))
    return results


def _write_summary(results: list[dict[str, Any]], evidence_dir: Path) -> None:
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "count": len(results),
        "tests": [
            {
                "service": r["service"],
                "public_id": r["public_id"],
                "action": r["action"],
                "url": r["url"],
                "locations": r["locations"],
                "ui_url": r["ui_url"],
            }
            for r in results
        ],
    }
    (evidence_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provision Datadog synthetic tests.")
    parser.add_argument("--services", default=None, help="Path to services.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads without calling the Datadog API.",
    )
    parser.add_argument(
        "--evidence-dir",
        default="evidence/phase1",
        help="Directory to write raw API responses (PROVE IT artifacts).",
    )
    args = parser.parse_args(argv)

    if args.dry_run:
        # No credentials required for a dry run.
        config = load_config(args.services, require_datadog=False)
        for target in config.services:
            payload = build_api_test_payload(target, _notification_message())
            print(f"--- {target.name} ---")
            print(json.dumps(payload, indent=2))
        return 0

    config = load_config(args.services)
    client = DatadogClient(config.datadog)
    if not client.validate():
        print(
            "ERROR: Datadog credentials were rejected by /api/v1/validate. "
            "Check DD_API_KEY, DD_APP_KEY, and DD_SITE.",
            file=sys.stderr,
        )
        return 2

    evidence_dir = Path(args.evidence_dir)
    results = provision(config, client, evidence_dir=evidence_dir)
    _write_summary(results, evidence_dir)
    print(f"\nProvisioned {len(results)} test(s). Evidence written to {evidence_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
