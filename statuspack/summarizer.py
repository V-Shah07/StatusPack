"""Phase 4 — LLM incident summarizer, traced in Datadog LLM Observability.

Pipeline:
  1. extract_incident_facts(): pull the raw failure data for a test from Datadog
     (failing checks, locations, actual HTTP status codes vs. expected, response
     times, duration) and reduce it to a structured, factual dict.
  2. build_summary_messages(): a prompt constrained to ONLY state what the data
     shows — no speculation about root cause beyond the evidence.
  3. summarize_incident(): call Claude, wrapped in a Datadog LLM Observability
     span (input, output, tokens, cost, latency) submitted agentlessly with the
     Datadog API key.

The Anthropic client is injectable so tests run without network or a real key.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from statuspack.config import read_env
from statuspack.datadog_client import DatadogClient

DEFAULT_MODEL = "claude-opus-5"
# First-party per-1M-token prices (USD). Keep in sync with the model in use.
MODEL_PRICING = {
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def _model() -> str:
    return read_env("STATUSPACK_LLM_MODEL") or DEFAULT_MODEL


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = MODEL_PRICING.get(model, MODEL_PRICING[DEFAULT_MODEL])
    return round(input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price, 6)


def _check_epoch_s(result: dict[str, Any]) -> float:
    ms = result.get("check_time", 0) or 0
    return ms / 1000 if ms > 10_000_000_000 else ms


@dataclass
class IncidentFacts:
    service: str
    public_id: str
    failed_checks: int
    total_checks_in_window: int
    failing_locations: list[str]
    status_codes: dict[str, int]  # actual HTTP status -> count (e.g. {"503": 5})
    expected_status: int | None
    response_ms_min: float | None
    response_ms_max: float | None
    first_fail: str | None
    last_fail: str | None
    duration_s: float | None
    failure_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_facts(
    summary_results: list[dict[str, Any]], detail_results: list[dict[str, Any]]
) -> IncidentFacts | None:
    """Pure reduction of raw Datadog results to structured incident facts.

    summary_results: items from GET .../results (check_time, probe_dc, result.passed).
    detail_results: items from GET .../results/{id} (result.httpStatusCode, assertionResults).
    Returns None if there are no failing checks.
    """
    failing = [r for r in summary_results if (r.get("result") or {}).get("passed") is False]
    if not failing:
        return None

    fail_times = sorted(_check_epoch_s(r) for r in failing)
    locations = sorted({r.get("probe_dc") for r in failing if r.get("probe_dc")})

    status_codes: dict[str, int] = {}
    expected_status: int | None = None
    reasons: set[str] = set()
    resp_ms: list[float] = []
    for d in detail_results:
        res = d.get("result") or {}
        code = res.get("httpStatusCode")
        if code:
            status_codes[str(code)] = status_codes.get(str(code), 0) + 1
        timings = res.get("timings") or {}
        if isinstance(timings.get("total"), int | float):
            resp_ms.append(float(timings["total"]))
        for a in res.get("assertionResults") or []:
            if a.get("valid") is False:
                if a.get("type") == "statusCode" and a.get("expected") is not None:
                    try:
                        expected_status = int(a["expected"])
                    except (TypeError, ValueError):
                        pass
                reasons.add(
                    f"{a.get('type')} {a.get('operator')} expected {a.get('expected')}, "
                    f"got {a.get('actual')}"
                )
        failure = res.get("failure") or {}
        if failure.get("code"):
            reasons.add(str(failure["code"]))

    def _iso(epoch_s: float) -> str:
        return datetime.fromtimestamp(epoch_s, tz=UTC).isoformat()

    return IncidentFacts(
        service="",  # filled by caller
        public_id="",  # filled by caller
        failed_checks=len(failing),
        total_checks_in_window=len(summary_results),
        failing_locations=locations,
        status_codes=status_codes,
        expected_status=expected_status,
        response_ms_min=round(min(resp_ms), 1) if resp_ms else None,
        response_ms_max=round(max(resp_ms), 1) if resp_ms else None,
        first_fail=_iso(fail_times[0]),
        last_fail=_iso(fail_times[-1]),
        duration_s=round(fail_times[-1] - fail_times[0], 1) if len(fail_times) > 1 else 0.0,
        failure_reasons=sorted(reasons),
    )


def extract_incident_facts(
    client: DatadogClient, service: str, public_id: str, *, max_details: int = 8
) -> IncidentFacts | None:
    """Fetch raw Datadog results for a test and reduce them to incident facts."""
    summary_results = client.get_test_results(public_id)
    failing = [r for r in summary_results if (r.get("result") or {}).get("passed") is False]
    details: list[dict[str, Any]] = []
    for r in failing[:max_details]:
        rid = r.get("result_id")
        if rid:
            details.append(client.get_result_detail(public_id, rid))
    facts = summarize_facts(summary_results, details)
    if facts is not None:
        facts.service = service
        facts.public_id = public_id
    return facts


def build_summary_messages(facts: IncidentFacts) -> tuple[str, str]:
    """Return (system, user) prompts constrained to the evidence only."""
    system = (
        "You are an incident summarizer for a status page. Write a 2-3 sentence "
        "factual summary of a monitoring incident using ONLY the data provided. "
        "State what the data shows: how many checks failed, from which regions, the "
        "observed HTTP status codes vs. expected, response times, and duration. Do "
        "NOT speculate about root cause (database, deploy, network, etc.) unless the "
        "data explicitly states it. If the data does not indicate a cause, say the "
        "cause is not identifiable from the monitoring data. No markdown, plain text."
    )
    user = f"Incident data (JSON):\n{facts.to_dict()}\n\nWrite the factual incident summary."
    return system, user


@dataclass
class SummaryResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_s: float


def enable_llmobs(ml_app: str = "statuspack") -> bool:
    """Enable Datadog LLM Observability (agentless, via the DD API key).

    Returns True if enabled, False if the SDK/keys are unavailable.
    """
    api_key = read_env("DD_API_KEY")
    site = read_env("DD_SITE", "datadoghq.com")
    if not api_key:
        return False
    try:
        from ddtrace.llmobs import LLMObs

        LLMObs.enable(
            ml_app=ml_app,
            api_key=api_key,
            site=site,
            agentless_enabled=True,
        )
        return True
    except Exception:
        return False


def summarize_incident(
    facts: IncidentFacts,
    *,
    client: Any | None = None,
    model: str | None = None,
    trace: bool = True,
) -> SummaryResult:
    """Call Claude to summarize the incident, wrapped in an LLM Observability span."""
    model = model or _model()
    system, user = build_summary_messages(facts)

    if client is None:
        import anthropic

        client = anthropic.Anthropic(api_key=read_env("ANTHROPIC_API_KEY"))

    llmobs = None
    if trace:
        try:
            from ddtrace.llmobs import LLMObs as _LLMObs

            llmobs = _LLMObs
        except Exception:
            llmobs = None

    def _do_call() -> SummaryResult:
        start = time.time()
        resp = client.messages.create(
            model=model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low"},
        )
        latency = round(time.time() - start, 3)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        usage = resp.usage
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        result = SummaryResult(
            text=text,
            model=model,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost_usd(model, in_tok, out_tok),
            latency_s=latency,
        )
        if llmobs is not None:
            try:
                llmobs.annotate(
                    input_data=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    output_data=[{"role": "assistant", "content": text}],
                    metrics={
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "total_tokens": in_tok + out_tok,
                    },
                    metadata={"service": facts.service, "public_id": facts.public_id},
                )
            except Exception:
                pass
        return result

    if llmobs is not None:
        try:
            with llmobs.llm(model_name=model, model_provider="anthropic", name="incident_summary"):
                result = _do_call()
            try:
                llmobs.flush()
            except Exception:
                pass
            return result
        except Exception:
            pass
    return _do_call()


def summary_result_to_dict(r: SummaryResult) -> dict[str, Any]:
    d = asdict(r)
    d["generated_at"] = datetime.now(UTC).isoformat()
    d["ml_app"] = os.environ.get("DD_LLMOBS_ML_APP", "statuspack")
    return d
