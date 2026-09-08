from statuspack.webhook import parse_alert


def test_parse_triggered_with_service_field():
    a = parse_alert(
        {
            "transition": "Triggered",
            "service": "httpbin-canary",
            "monitor_id": "319919697",
            "title": "[Triggered] StatusPack - httpbin-canary",
            "date": "1788838887000",
        }
    )
    assert a.service == "httpbin-canary"
    assert a.is_failure is True
    assert a.is_recovery is False
    assert a.monitor_id == 319919697
    assert a.event_time is not None and a.event_time.startswith("2026")


def test_parse_service_from_tags_string():
    a = parse_alert(
        {"transition": "Recovered", "tags": "env:prod,service:vivaan-portfolio,statuspack:true"}
    )
    assert a.service == "vivaan-portfolio"
    assert a.is_recovery is True
    assert a.is_failure is False


def test_parse_service_from_tags_list():
    a = parse_alert({"transition": "Re-Triggered", "tags": ["service:example-home"]})
    assert a.service == "example-home"
    assert a.is_failure is True


def test_parse_unknown_transition_is_neither():
    a = parse_alert({"transition": "", "tags": ["service:x"]})
    assert a.transition == "Unknown"
    assert not a.is_failure and not a.is_recovery


def test_event_time_accepts_seconds_and_millis():
    ms = parse_alert({"transition": "Triggered", "date": "1788838887000"}).event_time
    s = parse_alert({"transition": "Triggered", "date": "1788838887"}).event_time
    assert ms == s  # same instant, whether provided in ms or s
