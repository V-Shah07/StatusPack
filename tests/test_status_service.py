from statuspack.incidents import Incident
from statuspack.status_service import incident_duration_s, summarize_results


def _result(check_time_ms, passed, dc="aws:us-east-1", total_ms=None):
    r = {"check_time": check_time_ms, "probe_dc": dc, "result": {"passed": passed}}
    if total_ms is not None:
        r["result"]["timings"] = {"total": total_ms}
    return r


def test_summarize_empty_is_operational_no_data():
    s = summarize_results([])
    assert s["has_data"] is False
    assert s["operational"] is True
    assert s["uptime_pct"] == 0.0
    assert s["total"] == 0


def test_summarize_uptime_and_latest_status():
    results = [
        _result(1_000_000_000_000, True, "aws:us-east-1", total_ms=210),
        _result(1_000_000_060_000, False, "aws:eu-west-1"),
        _result(1_000_000_120_000, True, "aws:ap-southeast-1", total_ms=305),
    ]
    s = summarize_results(results)
    assert s["total"] == 3
    assert s["passed"] == 2
    assert s["uptime_pct"] == 66.67
    # Latest check (max check_time) passed -> operational.
    assert s["operational"] is True
    assert s["latest_response_ms"] == 305
    assert s["regions"] == ["aws:ap-southeast-1", "aws:eu-west-1", "aws:us-east-1"]


def test_summarize_down_when_latest_failed():
    results = [
        _result(1_000_000_000_000, True),
        _result(1_000_000_120_000, False),
    ]
    s = summarize_results(results)
    assert s["operational"] is False
    assert s["uptime_pct"] == 50.0


def test_incident_duration():
    inc = Incident(
        id=1,
        service="httpbin-canary",
        public_id="izu-g6a-wku",
        monitor_id=1,
        status="resolved",
        started_at="2026-09-08T03:50:28.167000+00:00",
        detected_at="2026-09-08T03:50:28.167000+00:00",
        resolved_at="2026-09-08T03:51:27+00:00",
        alert_transition="Triggered",
        summary=None,
        raw_alert=None,
    )
    assert incident_duration_s(inc) == 58.8

    inc_open = Incident(
        id=2,
        service="x",
        public_id=None,
        monitor_id=None,
        status="open",
        started_at="2026-09-08T03:50:28+00:00",
        detected_at="2026-09-08T03:50:28+00:00",
        resolved_at=None,
        alert_transition="Triggered",
        summary=None,
        raw_alert=None,
    )
    assert incident_duration_s(inc_open) is None
