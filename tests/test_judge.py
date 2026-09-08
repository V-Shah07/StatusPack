import json
from pathlib import Path
from types import SimpleNamespace

from statuspack.judge import (
    JudgeVerdict,
    build_judge_messages,
    evaluate,
    parse_judge_output,
    run_judge,
)

LABELED = Path(__file__).resolve().parent.parent / "evals" / "labeled_set.json"


def test_labeled_set_is_well_formed():
    data = json.loads(LABELED.read_text())
    items = data["items"]
    assert 15 <= len(items) <= 25
    labels = {i["label"] for i in items}
    assert labels == {"grounded", "ungrounded"}
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))  # unique ids
    for i in items:
        assert i["summary"] and isinstance(i["facts"], dict)
        if i["label"] == "ungrounded":
            assert i["injected_claim"]  # every hallucination documents its claim


def test_build_judge_messages_independent_of_summarizer():
    system, user = build_judge_messages({"status_codes": {"503": 5}}, "some summary")
    assert "independent grounding judge" in system
    assert "UNGROUNDED" in system
    assert "CANDIDATE SUMMARY" in user


def test_parse_judge_output_variants():
    v = parse_judge_output('{"verdict":"ungrounded","confidence":0.9,"unsupported_claims":["db"]}')
    assert v.verdict == "ungrounded" and v.confidence == 0.9 and v.unsupported_claims == ["db"]

    fenced = '```json\n{"verdict": "grounded", "confidence": 0.8, "unsupported_claims": []}\n```'
    v2 = parse_judge_output(fenced)
    assert v2.verdict == "grounded" and v2.unsupported_claims == []

    v3 = parse_judge_output("not json at all")
    assert v3.verdict == "ungrounded"  # safe default (flag for review)


def test_evaluate_catch_and_false_positive_rates():
    items = [
        {"id": "a", "label": "ungrounded"},
        {"id": "b", "label": "ungrounded"},
        {"id": "c", "label": "grounded"},
        {"id": "d", "label": "grounded"},
    ]
    verdicts = [
        JudgeVerdict("ungrounded", 0.9),  # caught
        JudgeVerdict("grounded", 0.4),  # missed
        JudgeVerdict("grounded", 0.8),  # correct
        JudgeVerdict("ungrounded", 0.7),  # false positive
    ]
    m = evaluate(items, verdicts)
    assert m["ungrounded_total"] == 2 and m["caught"] == 1
    assert m["catch_rate"] == 0.5
    assert m["grounded_total"] == 2 and m["false_positives"] == 1
    assert m["false_positive_rate"] == 0.5
    assert m["accuracy"] == 0.5


def test_run_judge_with_mock_client():
    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"]
            return SimpleNamespace(
                content=[
                    SimpleNamespace(
                        type="text",
                        text='{"verdict":"ungrounded","confidence":0.95,'
                        '"unsupported_claims":["database connection pool exhaustion"]}',
                    )
                ],
                usage=SimpleNamespace(input_tokens=500, output_tokens=30),
            )

    client = SimpleNamespace(messages=FakeMessages())
    v = run_judge(
        {"status_codes": {"503": 8}},
        "... caused by db pool exhaustion",
        client=client,
        model="claude-opus-5",
    )
    assert v.verdict == "ungrounded"
    assert v.confidence == 0.95
    assert "database connection pool exhaustion" in v.unsupported_claims
