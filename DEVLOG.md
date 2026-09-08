# Build log & evidence index

This file tracks each phase's **PROVE IT** evidence. Per the README's honesty
rule, no number or artifact here is fabricated — a phase is only marked DONE when
its evidence is a real committed artifact.

## Phase 5 — Grounding eval (LLM-as-judge)

**Status: ✅ CODE COMPLETE + labeled set committed. PROVE IT (judge run) blocked
on a real ANTHROPIC_API_KEY.**

- `evals/labeled_set.json`: **20 labeled items** (11 grounded, 9 ungrounded). Each
  pairs raw Datadog facts with a candidate summary; the 9 ungrounded ones inject a
  specific unsupported root cause (db pool exhaustion, bad deploy, OOM crash, DDoS,
  datacenter maintenance, expired domain, upstream Stripe, network partition, CDN
  cache misses). The grounded ones derive from real incidents incl. the Phase 2 503.
- `statuspack/judge.py`: an **independent** judge (separate Claude call from the
  summarizer) → `{verdict, confidence, unsupported_claims}`; pure metric computation
  for catch rate + false-positive rate.
- `statuspack/phase5_eval.py`: runs the judge over the set, records the score in
  SQLite, writes `evidence/phase5/eval_results.json`.
- 6 unit tests (labeled-set integrity, judge prompt independence, output parsing,
  metric math, mocked judge run).

**PROVE IT to produce (needs Anthropic key):** `python -m statuspack.phase5_eval`
→ catch rate / false-positive rate over the 20-item set, committed with per-item
verdicts. This is the "blocking X% of ungrounded claims across N=20 examples" bullet.

## Phase 4 — LLM incident summarizer, traced in LLM Observability

**Status: ✅ CODE COMPLETE. PROVE IT (real trace w/ tokens+cost) blocked on a real
ANTHROPIC_API_KEY.**

- `statuspack/summarizer.py`: pulls real failure data from Datadog (failing checks,
  regions, actual vs. expected HTTP status via the detailed-result API, response
  times, duration); a grounded prompt that states ONLY what the data shows; a Claude
  call wrapped in a **Datadog LLM Observability** `llm` span (input/output/tokens/
  cost/latency), submitted agentlessly with the (valid) DD API key; per-model cost calc.
- `statuspack/phase4_summarize.py`: runner that generates the traced summary from the
  real incident, stores it on the incident, writes `evidence/phase4/summary.json`.
- 5 unit tests with a mocked Anthropic client. `ddtrace` LLM Obs import verified.

**PROVE IT to produce (needs Anthropic key):** `python -m statuspack.phase4_summarize`
→ a real trace in Datadog LLM Observability (ml_app `statuspack`) with token count +
cost, plus the committed summary JSON.

> **Single remaining blocker for Phases 4 & 5:** a real `ANTHROPIC_API_KEY`
> (currently a dummy, per instruction). The Datadog side (LLM Obs ingestion, the
> real failure data) is fully wired and validated. Provide the key and both PROVE
> ITs run in two commands.

## Phase 3 — Public status page

**Status: ✅ DONE — renders real Datadog result history + the real Phase 2 outage.**

`GET /` pulls each test's recent results from the Synthetics API and renders a
server-side Jinja2 page: per-service current status, uptime % over the window,
and an incident timeline from SQLite.

**PROVE IT (real):** `evidence/phase3/status.png` + `status.html`, rendered
2026-09-08T03:56 UTC against the live org:

| Service | Status | Uptime (window) |
|---|---|---|
| vivaan-portfolio | Operational | 100.0% (15/15), last 77 ms |
| example-home | Operational | 100.0% (15/15), last 30 ms |
| httpbin-canary | Operational | **72.22% (39/54)** — the Phase 2 outage dip |

Past-incidents table shows the real outage: httpbin-canary down
`03:50:28` → recovered `03:51:27`, **59 s**, resolved — matching Phase 2's
Datadog timestamps. Canary is green again post-recovery; its uptime bar visibly
reflects the outage. Regenerate: `python -m statuspack.render_status`
(screenshot via Playwright/Chromium — command in commit history).

## Phase 2 — Monitors + real alert delivery

**Status: ✅ Core proven with a REAL triggered failure (2026-09-08). Last-mile
Datadog→app webhook + Discord deferred (see blocker below).**

Datadog auto-creates a Monitor per synthetic API test (fires on failure &
recovery). We triggered a **real** failure: re-pointed `httpbin-canary` at
`https://httpbin.org/status/503`, let Datadog observe it across all 3 regions,
then restored it. All timestamps below are real (evidence/phase2/):

| Event | Time (UTC) | From break |
|---|---|---|
| `t_break` — we broke the endpoint | 03:50:26.6 | 0s |
| `t_first_fail` — Datadog recorded FAILED checks (all 3 regions) | 03:50:28.2 | **1.6s** |
| `t_alert` — Monitor TRIGGERED (Datadog would page) | 03:50:57 | **30.4s** |
| `t_restore` — we restored the endpoint | 03:51:03.0 | — |
| `t_recovered` — Monitor RECOVERED | 03:51:27 | outage **60.4s** |

- **Paging latency = ~30s** from a real triggered failure (break → monitor
  Triggered). This is the "paging on-call within Xs" resume-bullet number.
- Raw multi-region result history: `evidence/phase2/canary_results.json`
  (independently shows all-green before, all-3-regions-red at 03:50:28, green after).
- **App hop proven** over real HTTP: `evidence/phase2/app_webhook_proof.json` — a
  Datadog-shaped payload (built from the real incident) POSTed to the running
  FastAPI server opened then resolved incident #1; `evidence/phase2/incident_log.json`
  is the resulting SQLite record with the real down/recovery timestamps.

**Deferred (needs the user), not a fabrication:** Datadog's monitor webhook can't
reach this sandbox (no public inbound URL), and `DISCORD_WEBHOOK_URL` is still a
placeholder. So the *real* "Datadog delivered the webhook" and "Discord message
landed" timestamps aren't captured yet. Options to finish this hop: (a) a public
tunnel/deploy for the app + a real Discord webhook, or (b) accept the ~30s
Datadog-side paging latency as the headline number (the app+Discord path is
code-complete and locally proven). See chat for the decision.

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
