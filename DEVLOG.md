# Build log & evidence index

This file tracks each phase's **PROVE IT** evidence. Per the README's honesty
rule, no number or artifact here is fabricated — a phase is only marked DONE when
its evidence is a real committed artifact.

## Phase 1 — Provision real Datadog Synthetic tests

**Status: ✅ DONE — proven against real Datadog org 2040770 on 2026-09-08.**

**PROVE IT (real):** `python -m statuspack.provision` created 3 live Datadog
Synthetic API tests in org `2040770` (owner: Vivaan Shah). Raw API responses
committed under `evidence/phase1/`:

| Service | public_id | monitor_id | URL | Regions |
|---|---|---|---|---|
| vivaan-portfolio | `ubu-7wg-emr` | 319919693 | https://vivaanportfolio.vercel.app/ | us-east-1, eu-west-1, ap-southeast-1 |
| example-home | `gd8-7b6-2di` | — | https://example.com/ | us-east-1, eu-west-1, ap-southeast-1 |
| httpbin-canary | `izu-g6a-wku` | — | https://httpbin.org/status/200 | us-east-1, eu-west-1, ap-southeast-1 |

- **N = 3** services monitored, **M = 3** global regions (resume-bullet inputs).
- **Idempotency proven:** first run logged `created`, immediate re-run logged
  `updated`, and the org holds exactly 3 `statuspack:true` tests (no duplicates).
- Datadog auto-created a Monitor per synthetic test — reused in Phase 2.

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
