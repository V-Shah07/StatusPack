"""Phase 5 runner — run the grounding judge over the labeled set and report rates.

Loads evals/labeled_set.json, runs the independent judge on each (facts, summary)
pair, computes catch rate + false-positive rate, records the score in SQLite, and
writes evidence/phase5/eval_results.json (per-item verdicts + the headline rates).

Best-effort: also submits each verdict to Datadog LLM Observability as a custom
evaluation label when the SDK + DD key are available.

Requires a real ANTHROPIC_API_KEY. Usage:
    python -m statuspack.phase5_eval
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from statuspack.config import read_env
from statuspack.incidents import IncidentStore
from statuspack.judge import evaluate, run_judge, verdict_to_dict

_PLACEHOLDER = ("your_anthropic_api_key", "placeholder", "dummy")
DEFAULT_LABELED = Path("evals/labeled_set.json")


def _anthropic_key_ready() -> bool:
    key = read_env("ANTHROPIC_API_KEY").strip()
    return bool(key) and not any(m in key.lower() for m in _PLACEHOLDER)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labeled", default=str(DEFAULT_LABELED))
    parser.add_argument("--out", default="evidence/phase5/eval_results.json")
    parser.add_argument("--db", default="statuspack.db")
    args = parser.parse_args(argv)

    if not _anthropic_key_ready():
        print(
            "ERROR: ANTHROPIC_API_KEY is missing or still a placeholder. Phase 5 needs "
            "a real Anthropic key to run the judge over the labeled set."
        )
        return 2

    data = json.loads(Path(args.labeled).read_text())
    items = data["items"]
    print(f"Running judge over {len(items)} labeled summaries...")

    verdicts = []
    for i, item in enumerate(items, 1):
        v = run_judge(item["facts"], item["summary"])
        verdicts.append(v)
        mark = "OK " if v.verdict == item["label"] else "MISS"
        print(
            f"  [{i:>2}/{len(items)}] {item['id']:<28} label={item['label']:<10} "
            f"judge={v.verdict:<10} conf={v.confidence:.2f} {mark}"
        )

    metrics = evaluate(items, verdicts)

    store = IncidentStore(args.db)
    store.record_eval(
        metrics["labeled_set_size"],
        metrics["catch_rate"],
        metrics["false_positive_rate"],
        details=json.dumps(
            {
                k: metrics[k]
                for k in (
                    "caught",
                    "ungrounded_total",
                    "false_positives",
                    "grounded_total",
                    "accuracy",
                )
            }
        ),
    )

    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "judge_model": read_env("STATUSPACK_JUDGE_MODEL") or "claude-opus-5",
        **{
            k: metrics[k]
            for k in (
                "labeled_set_size",
                "ungrounded_total",
                "grounded_total",
                "caught",
                "false_positives",
                "catch_rate",
                "false_positive_rate",
                "accuracy",
            )
        },
        "per_item": metrics["per_item"],
        "verdicts_raw": [verdict_to_dict(v) for v in verdicts],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True))

    print("\n=== Grounding eval ===")
    print(
        f"Labeled set: {metrics['labeled_set_size']} "
        f"({metrics['ungrounded_total']} ungrounded, {metrics['grounded_total']} grounded)"
    )
    print(
        f"Catch rate:          {metrics['catch_rate'] * 100:.1f}% "
        f"({metrics['caught']}/{metrics['ungrounded_total']} hallucinations flagged)"
    )
    print(
        f"False-positive rate: {metrics['false_positive_rate'] * 100:.1f}% "
        f"({metrics['false_positives']}/{metrics['grounded_total']} grounded wrongly flagged)"
    )
    print(f"Accuracy:            {metrics['accuracy'] * 100:.1f}%")
    print(f"Evidence -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
