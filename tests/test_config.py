import textwrap

import pytest

from statuspack.config import (
    MANAGED_TAG,
    DatadogSettings,
    load_datadog_settings,
    load_services,
)


def _write(tmp_path, content):
    p = tmp_path / "services.yaml"
    p.write_text(textwrap.dedent(content))
    return p


def test_load_services_applies_defaults(tmp_path):
    path = _write(
        tmp_path,
        """
        defaults:
          tick_every: 120
          response_time_ms: 3000
          locations: [aws:us-east-1, aws:eu-west-1]
        services:
          - name: svc-a
            url: https://example.com/a
          - name: svc-b
            url: https://example.com/b
            tick_every: 900
            locations: [aws:ap-southeast-1]
        """,
    )
    services = load_services(path)
    assert [s.name for s in services] == ["svc-a", "svc-b"]

    a, b = services
    assert a.tick_every == 120
    assert a.response_time_ms == 3000
    assert a.locations == ("aws:us-east-1", "aws:eu-west-1")

    # Per-service overrides win over defaults.
    assert b.tick_every == 900
    assert b.locations == ("aws:ap-southeast-1",)


def test_service_tags_are_consistent(tmp_path):
    path = _write(
        tmp_path,
        """
        defaults:
          locations: [aws:us-east-1]
        services:
          - name: my-api
            url: https://example.com
        """,
    )
    (svc,) = load_services(path)
    assert MANAGED_TAG in svc.tags
    assert "service:my-api" in svc.tags


def test_duplicate_service_names_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        defaults:
          locations: [aws:us-east-1]
        services:
          - name: dup
            url: https://example.com/1
          - name: dup
            url: https://example.com/2
        """,
    )
    with pytest.raises(ValueError, match="Duplicate service names"):
        load_services(path)


def test_service_without_locations_rejected(tmp_path):
    path = _write(
        tmp_path,
        """
        services:
          - name: no-loc
            url: https://example.com
        """,
    )
    with pytest.raises(ValueError, match="no locations"):
        load_services(path)


def test_missing_credentials_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("DD_API_KEY", raising=False)
    monkeypatch.delenv("DD_APP_KEY", raising=False)
    # Point at a non-existent .env so the developer's real .env can't satisfy it.
    with pytest.raises(RuntimeError, match="Missing Datadog credentials"):
        load_datadog_settings(require=True, dotenv_path=tmp_path / "absent.env")


def test_api_base_and_app_base():
    s = DatadogSettings(api_key="k", app_key="a", site="datadoghq.eu")
    assert s.api_base == "https://api.datadoghq.eu"
    assert s.app_base == "https://app.datadoghq.eu"

    s2 = DatadogSettings(api_key="k", app_key="a", site="us5.datadoghq.com")
    assert s2.api_base == "https://api.us5.datadoghq.com"
    assert s2.app_base == "https://us5.datadoghq.com"
