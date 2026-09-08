import responses

from statuspack.config import Config, DatadogSettings, ServiceTarget
from statuspack.datadog_client import DatadogClient, build_api_test_payload
from statuspack.provision import provision

SETTINGS = DatadogSettings(api_key="k", app_key="a", site="datadoghq.com")


def _target(name="svc-a", url="https://example.com/a"):
    return ServiceTarget(
        name=name,
        url=url,
        locations=("aws:us-east-1", "aws:eu-west-1"),
        tick_every=300,
        response_time_ms=5000,
    )


def test_build_api_test_payload_shape():
    payload = build_api_test_payload(_target(), "hello")
    assert payload["type"] == "api"
    assert payload["subtype"] == "http"
    assert payload["config"]["request"]["url"] == "https://example.com/a"
    assert payload["locations"] == ["aws:us-east-1", "aws:eu-west-1"]
    assert payload["options"]["tick_every"] == 300
    assert {"type": "statusCode", "operator": "is", "target": 200} in payload["config"][
        "assertions"
    ]
    assert "statuspack:true" in payload["tags"]
    assert "service:svc-a" in payload["tags"]


@responses.activate
def test_provision_creates_when_absent(tmp_path):
    base = "https://api.datadoghq.com"
    # No existing tests -> create.
    responses.get(f"{base}/api/v1/synthetics/tests", json={"tests": []}, status=200)
    responses.post(
        f"{base}/api/v1/synthetics/tests/api",
        json={"public_id": "abc-def-ghi", "name": "StatusPack - svc-a"},
        status=200,
    )

    config = Config(datadog=SETTINGS, services=[_target()])
    client = DatadogClient(SETTINGS)
    results = provision(config, client, evidence_dir=tmp_path)

    assert len(results) == 1
    assert results[0]["action"] == "created"
    assert results[0]["public_id"] == "abc-def-ghi"
    # Evidence file written with the raw response.
    assert (tmp_path / "svc-a.json").exists()


@responses.activate
def test_provision_updates_when_present(tmp_path):
    base = "https://api.datadoghq.com"
    existing = {
        "public_id": "old-pub-id",
        "tags": ["statuspack:true", "service:svc-a", "env:prod"],
    }
    responses.get(f"{base}/api/v1/synthetics/tests", json={"tests": [existing]}, status=200)
    put = responses.put(
        f"{base}/api/v1/synthetics/tests/api/old-pub-id",
        json={"public_id": "old-pub-id", "name": "StatusPack - svc-a"},
        status=200,
    )

    config = Config(datadog=SETTINGS, services=[_target()])
    client = DatadogClient(SETTINGS)
    results = provision(config, client, evidence_dir=tmp_path)

    assert results[0]["action"] == "updated"
    assert results[0]["public_id"] == "old-pub-id"
    # Idempotency: an existing managed test triggers a PUT, not a second POST.
    assert put.call_count == 1


@responses.activate
def test_find_managed_test_matches_by_tags():
    base = "https://api.datadoghq.com"
    tests = [
        {"public_id": "x", "tags": ["service:other", "statuspack:true"]},
        {"public_id": "y", "tags": ["statuspack:true", "service:svc-a"]},
    ]
    responses.get(f"{base}/api/v1/synthetics/tests", json={"tests": tests}, status=200)
    client = DatadogClient(SETTINGS)
    found = client.find_managed_test("svc-a")
    assert found is not None
    assert found["public_id"] == "y"
