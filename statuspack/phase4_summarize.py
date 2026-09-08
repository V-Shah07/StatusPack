"""Phase 4 runner — generate a traced LLM incident summary from real data.

Pulls the real failure data for a service's synthetic test from Datadog, sends it
to Claude wrapped in a Datadog LLM Observability span, stores the summary on the
incident, and writes evidence/phase4/summary.json (text, tokens, cost, latency).

Requires a real ANTHROPIC_API_KEY. The LLM Obs trace is submitted to Datadog with
the DD API key and appears in the LLM Observability UI (ml_app "statuspack").

Usage:
    python -m statuspack.phase4_summarize --service httpbin-canary
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from statuspack.config import load_config, read_env
from statuspack.datadog_client import DatadogClient
from statuspack.incidents import IncidentStore
from statuspack.summarizer import (
    enable_llmobs,
    extract_incident_facts,
    summarize_incident,
    summary_result_to_dict,
)

_PLACEHOLDER = ("your_anthropic_api_key", "placeholder", "dummy")


def _anthropic_key_ready() -> bool:
    key = read_env("ANTHROPIC_API_KEY").strip()
    return bool(key) and not any(m in key.lower() for m in _PLACEHOLDER)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--service", default="httpbin-canary")
    parser.add_argument("--out", default="evidence/phase4/summary.json")
    parser.add_argument("--db", default="statuspack.db")
    parser.add_argument("--no-trace", action="store_true")
    args = parser.parse_args(argv)

    if not _anthropic_key_ready():
        print(
            "ERROR: ANTHROPIC_API_KEY is missing or still a placeholder. Phase 4 needs "
            "a real Anthropic key to produce a real traced summary (tokens + cost).\n"
            "Set ANTHROPIC_API_KEY in .env and re-run."
        )
        return 2

    config = load_config()
    client = DatadogClient(config.datadog)
    target = next((t for t in config.services if t.name == args.service), None)
    if target is None:
        print(f"ERROR: no service named {args.service} in services.yaml")
        return 2
    existing = client.find_managed_test(args.service)
    if not existing:
        print(f"ERROR: no managed synthetic test for {args.service}")
        return 2
    public_id = existing["public_id"]

    facts = extract_incident_facts(client, args.service, public_id)
    if facts is None:
        print(
            f"No failing checks found for {args.service} in the recent window. "
            "Trigger a failure (python -m statuspack.phase2_incident) first."
        )
        return 3

    traced = enable_llmobs() and not args.no_trace
    print(f"LLM Observability enabled: {traced}")
    result = summarize_incident(facts, trace=traced)

    # Attach to the incident log if one is open/most-recent for this service.
    store = IncidentStore(args.db)
    incidents = [i for i in store.list_incidents() if i.service == args.service]
    if incidents:
        store.set_summary(incidents[0].id, result.text)

    out = summary_result_to_dict(result)
    out["facts"] = facts.to_dict()
    out["traced_in_llmobs"] = traced
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True))
    print("\n--- Incident summary ---\n" + result.text)
    print(
        f"\nmodel={result.model} input_tokens={result.input_tokens} "
        f"output_tokens={result.output_tokens} cost=${result.cost_usd} "
        f"latency={result.latency_s}s"
    )
    print(f"Evidence -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
