# Build log & evidence index

This file tracks each phase's **PROVE IT** evidence. Per the README's honesty
rule, no number or artifact here is fabricated — a phase is only marked DONE when
its evidence is a real committed artifact.

## Phase 1 — Provision real Datadog Synthetic tests

**Status: CODE COMPLETE, PROVE IT BLOCKED on Datadog credentials.**

Built:
- `services.yaml` — 3 target services (idempotent, tagged `statuspack:true` + `service:<name>`).
- `statuspack/config.py` — env + YAML config loader.
- `statuspack/datadog_client.py` — Synthetics/Monitors v1 API client + pure payload builder.
- `statuspack/provision.py` — idempotent create-or-update, writes raw API responses to `evidence/phase1/`.
- `tests/` — 10 unit tests (payload shape, idempotency, config defaults), all passing.
- `.github/workflows/ci.yml` — ruff lint + format check + pytest.

**Blocker (needs the user):** The `DD_API_KEY` present in this environment is
rejected by Datadog. `GET https://api.datadoghq.com/api/v1/validate` (which needs
only the API key) returns **HTTP 403 `{"errors":["Forbidden"]}`**, and the same
403 comes back from every Datadog site (us1/us3/us5/eu/ap1). Listing synthetic
tests returns **HTTP 401 `{"errors":["Unauthorized"]}`**. These are Datadog's own
error bodies, so the requests reach Datadog and the key is invalid — not a proxy
block (proxy status shows no relay failures).

To unblock: provide a valid `DD_API_KEY` + `DD_APP_KEY` (app key scoped for
`synthetics_read`/`synthetics_write`) for a real Datadog org, and the correct
`DD_SITE`. Then:

```
python -m statuspack.provision      # creates real tests, writes evidence/phase1/*.json
```

The committed `evidence/phase1/summary.json` + per-service response JSON will be
the Phase 1 PROVE IT artifact (real `public_id`s from the Datadog API).
