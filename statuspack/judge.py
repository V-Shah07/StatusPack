"""Phase 5 — grounding eval via an independent LLM-as-judge.

The judge is a SEPARATE Claude call from the summarizer (Phase 4). Given the raw
Datadog failure data and a candidate summary, it decides whether the summary
asserts anything NOT supported by the data — especially invented root causes —
and returns a grounded/ungrounded verdict with a confidence.

Pure helpers (prompt building, output parsing, metric computation) are unit-tested
without network; the Anthropic client is injectable.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from statuspack.config import read_env

DEFAULT_JUDGE_MODEL = "claude-opus-5"


def judge_model() -> str:
    return read_env("STATUSPACK_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL


@dataclass
class JudgeVerdict:
    verdict: str  # 'grounded' | 'ungrounded'
    confidence: float
    unsupported_claims: list[str] = field(default_factory=list)
    raw: str = ""


def build_judge_messages(facts: dict[str, Any], summary: str) -> tuple[str, str]:
    system = (
        "You are an independent grounding judge for incident summaries. You are given "
        "the raw monitoring data (JSON) for an incident and a candidate summary. Decide "
        "whether the summary states anything NOT supported by the data.\n\n"
        "Supported facts include: the number of failed checks, which regions failed, the "
        "actual vs. expected HTTP status codes, response times, timing/duration, and any "
        "failure reasons explicitly present in the data (e.g. TIMEOUT, DNS, "
        "INCORRECT_ASSERTION). Reasonable restatements and arithmetic on these are fine.\n\n"
        "A summary is UNGROUNDED if it asserts any cause or fact the data does not show — "
        "for example a database issue, a deploy, an out-of-memory crash, a DDoS attack, "
        "scheduled maintenance, an upstream provider, DNS registrar/domain claims, or a "
        "network partition — when the data only records status codes, timings, regions, "
        "and generic failure reasons. Saying the cause is 'not identifiable from the data' "
        "is grounded.\n\n"
        'Respond with ONLY a JSON object: {"verdict": "grounded" | "ungrounded", '
        '"confidence": <number 0-1>, "unsupported_claims": [<short strings>]}. '
        "unsupported_claims must be empty when verdict is grounded."
    )
    user = (
        f"RAW DATA (JSON):\n{json.dumps(facts, sort_keys=True)}\n\n"
        f"CANDIDATE SUMMARY:\n{summary}\n\n"
        "Return the JSON verdict."
    )
    return system, user


def parse_judge_output(text: str) -> JudgeVerdict:
    """Extract the judge's JSON verdict, tolerant of surrounding prose/code fences."""
    raw = text.strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    verdict = "ungrounded"
    confidence = 0.0
    claims: list[str] = []
    if match:
        try:
            obj = json.loads(match.group(0))
            v = str(obj.get("verdict", "")).strip().lower()
            verdict = "grounded" if v == "grounded" else "ungrounded"
            confidence = float(obj.get("confidence", 0.0) or 0.0)
            raw_claims = obj.get("unsupported_claims") or []
            claims = [str(c) for c in raw_claims] if isinstance(raw_claims, list) else []
        except (ValueError, TypeError):
            pass
    return JudgeVerdict(verdict=verdict, confidence=confidence, unsupported_claims=claims, raw=raw)


def run_judge(
    facts: dict[str, Any],
    summary: str,
    *,
    client: Any | None = None,
    model: str | None = None,
) -> JudgeVerdict:
    model = model or judge_model()
    system, user = build_judge_messages(facts, summary)
    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=read_env("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=model,
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium"},
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    verdict = parse_judge_output(text)
    usage = getattr(resp, "usage", None)
    if usage is not None:
        verdict_in = int(getattr(usage, "input_tokens", 0) or 0)
        verdict_out = int(getattr(usage, "output_tokens", 0) or 0)
        verdict.__dict__["input_tokens"] = verdict_in
        verdict.__dict__["output_tokens"] = verdict_out
    return verdict


def evaluate(items: list[dict[str, Any]], verdicts: list[JudgeVerdict]) -> dict[str, Any]:
    """Compute catch rate and false-positive rate from labels vs. judge verdicts.

    catch_rate: of the deliberately-ungrounded items, the fraction the judge flagged.
    false_positive_rate: of the grounded items, the fraction the judge wrongly flagged.
    """
    if len(items) != len(verdicts):
        raise ValueError("items and verdicts must be the same length")

    ungrounded_total = caught = grounded_total = false_pos = 0
    per_item = []
    for item, v in zip(items, verdicts, strict=True):
        label = item["label"]
        predicted = v.verdict
        correct = label == predicted
        if label == "ungrounded":
            ungrounded_total += 1
            if predicted == "ungrounded":
                caught += 1
        else:
            grounded_total += 1
            if predicted == "ungrounded":
                false_pos += 1
        per_item.append(
            {
                "id": item.get("id"),
                "label": label,
                "predicted": predicted,
                "confidence": v.confidence,
                "correct": correct,
                "unsupported_claims": v.unsupported_claims,
            }
        )

    catch_rate = round(caught / ungrounded_total, 4) if ungrounded_total else 0.0
    fp_rate = round(false_pos / grounded_total, 4) if grounded_total else 0.0
    accuracy = (
        round(sum(1 for p in per_item if p["correct"]) / len(per_item), 4) if per_item else 0.0
    )
    return {
        "labeled_set_size": len(items),
        "ungrounded_total": ungrounded_total,
        "grounded_total": grounded_total,
        "caught": caught,
        "false_positives": false_pos,
        "catch_rate": catch_rate,
        "false_positive_rate": fp_rate,
        "accuracy": accuracy,
        "per_item": per_item,
    }


def verdict_to_dict(v: JudgeVerdict) -> dict[str, Any]:
    return asdict(v)
