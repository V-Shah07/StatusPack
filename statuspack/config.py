"""Configuration loading for StatusPack.

Two sources:
  * Environment (secrets + site) — loaded from a .env file if present.
  * services.yaml (the target URLs and check parameters).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SERVICES_PATH = REPO_ROOT / "services.yaml"
DEFAULT_DOTENV_PATH = REPO_ROOT / ".env"

# Consistent tag applied to every StatusPack-managed Datadog resource. Used for
# idempotent lookups so we update rather than duplicate on re-run.
MANAGED_TAG = "statuspack:true"


def read_env(key: str, default: str = "", *, dotenv_path: str | Path | None = None) -> str:
    """Read a config value, preferring a local .env file over the process env.

    Uses dotenv_values (which does NOT mutate os.environ) so calling this never
    clobbers unrelated environment variables. .env wins because this container
    may carry stale/placeholder values in the real process environment; in CI
    (no .env) the process environment is used.
    """
    path = Path(dotenv_path) if dotenv_path is not None else DEFAULT_DOTENV_PATH
    file_vals = dotenv_values(path) if path.exists() else {}
    value = file_vals.get(key)
    if value:
        return value
    return os.environ.get(key, default)


@dataclass(frozen=True)
class DatadogSettings:
    api_key: str
    app_key: str
    site: str = "datadoghq.com"

    @property
    def api_base(self) -> str:
        return f"https://api.{self.site}"

    @property
    def app_base(self) -> str:
        # The Synthetics UI lives on the app host, used only to build human links.
        host = self.site
        if host.startswith("us3.") or host.startswith("us5.") or host.startswith("ap1."):
            return f"https://{host}"
        if host == "datadoghq.eu":
            return "https://app.datadoghq.eu"
        return "https://app.datadoghq.com"


@dataclass(frozen=True)
class ServiceTarget:
    name: str
    url: str
    method: str = "GET"
    expected_status: int = 200
    tick_every: int = 300
    response_time_ms: int = 5000
    locations: tuple[str, ...] = ()
    min_failure_duration: int = 0
    min_location_failed: int = 1

    @property
    def tags(self) -> list[str]:
        return [MANAGED_TAG, f"service:{self.name}", "env:prod"]


@dataclass(frozen=True)
class Config:
    datadog: DatadogSettings
    services: list[ServiceTarget] = field(default_factory=list)


def load_datadog_settings(
    require: bool = True, *, dotenv_path: str | Path | None = None
) -> DatadogSettings:
    """Load Datadog credentials, preferring .env over the process environment.

    Raises RuntimeError with an actionable message if required keys are missing
    (unless require=False, used by tests).
    """
    api_key = read_env("DD_API_KEY", dotenv_path=dotenv_path)
    app_key = read_env("DD_APP_KEY", dotenv_path=dotenv_path)
    site = read_env("DD_SITE", "datadoghq.com", dotenv_path=dotenv_path)

    if require and (not api_key or not app_key):
        missing = [k for k, v in (("DD_API_KEY", api_key), ("DD_APP_KEY", app_key)) if not v]
        raise RuntimeError(
            f"Missing Datadog credentials: {', '.join(missing)}. "
            "Set them in your environment or .env (see .env.example)."
        )
    return DatadogSettings(api_key=api_key, app_key=app_key, site=site)


def load_services(path: str | Path | None = None) -> list[ServiceTarget]:
    """Parse services.yaml into ServiceTarget objects, applying defaults."""
    path = Path(path) if path else DEFAULT_SERVICES_PATH
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}

    defaults = raw.get("defaults", {}) or {}
    default_locations = tuple(defaults.get("locations", []) or [])

    targets: list[ServiceTarget] = []
    for entry in raw.get("services", []) or []:
        if "name" not in entry or "url" not in entry:
            raise ValueError(f"Each service needs 'name' and 'url'; got: {entry!r}")
        locations = tuple(entry.get("locations", default_locations) or default_locations)
        if not locations:
            raise ValueError(f"Service {entry['name']!r} has no locations configured.")
        targets.append(
            ServiceTarget(
                name=str(entry["name"]),
                url=str(entry["url"]),
                method=str(entry.get("method", "GET")).upper(),
                expected_status=int(entry.get("expected_status", 200)),
                tick_every=int(entry.get("tick_every", defaults.get("tick_every", 300))),
                response_time_ms=int(
                    entry.get("response_time_ms", defaults.get("response_time_ms", 5000))
                ),
                locations=locations,
                min_failure_duration=int(
                    entry.get("min_failure_duration", defaults.get("min_failure_duration", 0))
                ),
                min_location_failed=int(
                    entry.get("min_location_failed", defaults.get("min_location_failed", 1))
                ),
            )
        )

    names = [t.name for t in targets]
    if len(names) != len(set(names)):
        raise ValueError(f"Duplicate service names in services.yaml: {names}")
    if not targets:
        raise ValueError("No services defined in services.yaml.")
    return targets


def load_config(services_path: str | Path | None = None, require_datadog: bool = True) -> Config:
    return Config(
        datadog=load_datadog_settings(require=require_datadog),
        services=load_services(services_path),
    )
