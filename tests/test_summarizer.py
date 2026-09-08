from types import SimpleNamespace

from statuspack.summarizer import (
    build_summary_messages,
    cost_usd,
    summarize_facts,
    summarize_incident,
)


def _summary(check_ms, passed, dc):
    return {"check_time": check_ms, "probe_dc": dc, "result": {"passed": passed}}


def _detail(status, expected="200", total_ms=16.3):
    return {
        "result": {
            "httpStatusCode": status,
            "timings": {"total": total_ms},
            "assertionResults": [
                {
                    "valid": False,
                    "actual": status,
                    "expected": expected,
                    "type": "statusCode",
                    "operator": "is",
                },
            ],
            "failure": {"code": "INCORRECT_ASSERTION"},
        }
    }


def test_summarize_facts_none_when_all_pass():
    assert summarize_facts([_summary(1_700_000_000_000, True, "aws:us-east-1")], []) is None


def test_summarize_facts_aggregates_real_shape():
    summaries = [
        _summary(1_700_000_000_000, True, "aws:us-east-1"),
        _summary(1_700_000_060_000, False, "aws:us-east-1"),
        _summary(1_700_000_061_000, False, "aws:eu-west-1"),
        _summary(1_700_000_090_000, False, "aws:ap-southeast-1"),
    ]
    details = [_detail(503), _detail(503), _detail(503)]
    facts = summarize_facts(summaries, details)
    assert facts is not None
    assert facts.failed_checks == 3
    assert facts.failing_locations == ["aws:ap-southeast-1", "aws:eu-west-1", "aws:us-east-1"]
    assert facts.status_codes == {"503": 3}
    assert facts.expected_status == 200
    assert facts.duration_s == 30.0
    assert facts.response_ms_max == 16.3
    assert any("INCORRECT_ASSERTION" in r for r in facts.failure_reasons)


def test_cost_calc_opus5():
    # 1000 in, 500 out at $5/$25 per 1M
    assert cost_usd("claude-opus-5", 1000, 500) == round(1000 / 1e6 * 5 + 500 / 1e6 * 25, 6)


def test_build_summary_messages_constrains_to_evidence():
    facts = summarize_facts([_summary(1_700_000_060_000, False, "aws:us-east-1")], [_detail(503)])
    system, user = build_summary_messages(facts)
    assert "ONLY the data provided" in system
    assert "Do NOT speculate about root cause" in system
    assert "503" in user


def test_summarize_incident_with_mock_client_no_trace():
    facts = summarize_facts(
        [
            _summary(1_700_000_060_000, False, "aws:us-east-1"),
            _summary(1_700_000_090_000, False, "aws:eu-west-1"),
        ],
        [_detail(503), _detail(503)],
    )

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"]
            assert "system" in kwargs
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text", text="2 checks failed with HTTP 503 from 2 regions."
                    )
                ],
                usage=SimpleNamespace(input_tokens=320, output_tokens=42),
            )

    fake_client = SimpleNamespace(messages=FakeMessages())
    res = summarize_incident(facts, client=fake_client, model="claude-opus-5", trace=False)
    assert "503" in res.text
    assert res.input_tokens == 320
    assert res.output_tokens == 42
    assert res.cost_usd == cost_usd("claude-opus-5", 320, 42)
    assert res.latency_s >= 0
