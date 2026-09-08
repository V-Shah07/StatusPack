"""Thin client over the Datadog Synthetics + Monitors v1 API.

Only the endpoints StatusPack actually uses. Payload construction is separated
from transport so it can be unit-tested without hitting the network.
"""

from __future__ import annotations

from typing import Any

import requests

from statuspack.config import MANAGED_TAG, DatadogSettings, ServiceTarget


class DatadogError(RuntimeError):
    """Raised when the Datadog API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str, method: str, url: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Datadog API {method} {url} -> HTTP {status_code}: {body[:500]}")


def build_api_test_payload(target: ServiceTarget, message: str) -> dict[str, Any]:
    """Build the request body for POST/PUT /api/v1/synthetics/tests/api.

    Pure function — no network. Kept in sync with the Datadog v1 schema.
    """
    return {
        "name": f"StatusPack - {target.name}",
        "type": "api",
        "subtype": "http",
        "config": {
            "request": {
                "method": target.method,
                "url": target.url,
                "timeout": 30,
            },
            "assertions": [
                {"type": "statusCode", "operator": "is", "target": target.expected_status},
                {
                    "type": "responseTime",
                    "operator": "lessThan",
                    "target": target.response_time_ms,
                },
            ],
        },
        "locations": list(target.locations),
        "options": {
            "tick_every": target.tick_every,
            "min_failure_duration": target.min_failure_duration,
            "min_location_failed": target.min_location_failed,
            "retry": {"count": 0, "interval": 300},
        },
        "message": message,
        "tags": target.tags,
        "status": "live",
    }


class DatadogClient:
    def __init__(self, settings: DatadogSettings, session: requests.Session | None = None):
        self.settings = settings
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "DD-API-KEY": settings.api_key,
                "DD-APPLICATION-KEY": settings.app_key,
                "Content-Type": "application/json",
            }
        )

    # --- transport ---------------------------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.settings.api_base}{path}"
        resp = self.session.request(method, url, timeout=30, **kwargs)
        if not resp.ok:
            raise DatadogError(resp.status_code, resp.text, method, url)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    # --- validation --------------------------------------------------------
    def validate(self) -> bool:
        """Return True if the API key is accepted by /api/v1/validate."""
        url = f"{self.settings.api_base}/api/v1/validate"
        resp = self.session.get(url, timeout=30)
        return resp.ok and bool(resp.json().get("valid"))

    # --- synthetics --------------------------------------------------------
    def list_synthetic_tests(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/v1/synthetics/tests")
        return data.get("tests", []) if isinstance(data, dict) else []

    def find_managed_test(self, service_name: str) -> dict[str, Any] | None:
        """Find an existing StatusPack-managed test for a service, by tags."""
        want = {MANAGED_TAG, f"service:{service_name}"}
        for test in self.list_synthetic_tests():
            tags = set(test.get("tags", []) or [])
            if want.issubset(tags):
                return test
        return None

    def create_api_test(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/v1/synthetics/tests/api", json=payload)

    def update_api_test(self, public_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/v1/synthetics/tests/api/{public_id}", json=payload)

    def get_test(self, public_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/synthetics/tests/{public_id}")

    def get_test_results(self, public_id: str) -> list[dict[str, Any]]:
        data = self._request("GET", f"/api/v1/synthetics/tests/{public_id}/results")
        return data.get("results", []) if isinstance(data, dict) else []

    def get_result_detail(self, public_id: str, result_id: str) -> dict[str, Any]:
        """Full detail for one result (includes httpStatusCode, assertionResults)."""
        return self._request("GET", f"/api/v1/synthetics/tests/{public_id}/results/{result_id}")

    def trigger_tests(self, public_ids: list[str]) -> dict[str, Any]:
        """Run one or more tests on demand (bypasses the tick schedule)."""
        body = {"tests": [{"public_id": pid} for pid in public_ids]}
        return self._request("POST", "/api/v1/synthetics/tests/trigger", json=body)

    # --- monitors ----------------------------------------------------------
    def get_monitor(self, monitor_id: int, group_states: str = "all") -> dict[str, Any]:
        return self._request(
            "GET",
            f"/api/v1/monitor/{monitor_id}",
            params={"group_states": group_states},
        )

    def synthetics_ui_url(self, public_id: str) -> str:
        return f"{self.settings.app_base}/synthetics/details/{public_id}"
