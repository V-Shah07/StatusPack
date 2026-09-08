# Build log & evidence index

This file tracks each phase's **PROVE IT** evidence. Per the README's honesty
rule, no number or artifact here is fabricated — a phase is only marked DONE when
its evidence is a real committed artifact.

## Phase 5 — Grounding eval (LLM-as-judge)

**Status: ✅ DONE — real judge run on 2026-09-08 (claude-opus-5).**

**PROVE IT (real):** `python -m statuspack.phase5_eval` ran the independent judge
over all 20 labeled summaries. Results in `evidence/phase5/eval_results.json`:

- **Catch rate: 100.0% (9/9** injected hallucinations flagged) — every ungrounded
  root-cause claim (db pool, deploy, OOM, DDoS, maintenance, expired domain,
  upstream Stripe, network partition, CDN) was caught.
- **False-positive rate: 9.1% (1/11** grounded summaries wrongly flagged — item
  `g10-two-region-500`). An honest, non-padded number.
- **Accuracy: 95.0%** overall.

This is the "blocking X% of ungrounded claims across N=20 examples" bullet: **100%
catch on 9 hallucinations, 9.1% false-positive on 11 grounded, 20-item set.**

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

**Status: ✅ DONE — real traced summary on 2026-09-08 (claude-opus-5).**

**PROVE IT (real):** Triggered a fresh canary 503, then
`python -m statuspack.phase4_summarize` generated a grounded summary via Claude,
wrapped in a Datadog LLM Observability span. Verified in Datadog by querying the
LLM Obs spans API (`@ml_app:statuspack`) — `evidence/phase4/llmobs_trace.json` +
`llmobs_trace_summary.json`:

| Field | Value (from Datadog's own LLM Obs span) |
|---|---|
| ml_app | `statuspack` |
| model | `claude-opus-5` (provider anthropic) |
| trace_id | `6a9f96f9000000004c6a51e009a7ef48` |
| input / output / total tokens | 458 / 212 / **670** |
| cost | **$0.00759** |
| latency | **4.221 s** |

The summary stayed grounded ("the cause is not identifiable from the available
monitoring data") — no invented root cause. Full summary + numbers in
`evidence/phase4/summary.json`. This backs the "traced every AI summary end-to-end
in Datadog LLM Observability, tracking token cost and latency" bullet.

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

> **Phases 4 & 5 unblocked and proven** with a real `ANTHROPIC_API_KEY` on
> 2026-09-08 (SDK bumped to anthropic 1.4.0 for claude-opus-5 support).

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
