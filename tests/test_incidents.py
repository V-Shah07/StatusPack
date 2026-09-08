from statuspack.incidents import IncidentStore


def test_open_and_resolve_incident(tmp_path):
    store = IncidentStore(tmp_path / "t.db")
    iid = store.open_incident("svc-a", public_id="pub", monitor_id=1, alert_transition="Triggered")
    assert iid > 0
    open_inc = store.get_open_incident("svc-a")
    assert open_inc is not None and open_inc.status == "open"

    resolved_id = store.resolve_incident("svc-a")
    assert resolved_id == iid
    assert store.get_open_incident("svc-a") is None
    assert store.get_incident(iid).status == "resolved"


def test_open_incident_is_deduped_while_open(tmp_path):
    store = IncidentStore(tmp_path / "t.db")
    a = store.open_incident("svc", alert_transition="Triggered")
    b = store.open_incident("svc", alert_transition="Re-Triggered")
    assert a == b  # second failure does not create a duplicate open incident
    assert len(store.list_incidents()) == 1


def test_resolve_without_open_returns_none(tmp_path):
    store = IncidentStore(tmp_path / "t.db")
    assert store.resolve_incident("nope") is None


def test_summary_and_eval_and_remediation(tmp_path):
    store = IncidentStore(tmp_path / "t.db")
    iid = store.open_incident("svc", alert_transition="Triggered")
    store.set_summary(iid, "5 consecutive 503s from us-east-1.")
    assert store.get_incident(iid).summary.startswith("5 consecutive")

    eid = store.record_eval(18, catch_rate=0.83, false_positive_rate=0.06, details="{}")
    assert eid > 0

    rid = store.log_remediation(
        "svc",
        proposed_action="restart",
        confidence=0.91,
        gate_decision="executed",
        reason="grounded + in allow-list",
        recovered=True,
    )
    assert rid > 0
