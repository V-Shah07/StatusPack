# StatusPack — Datadog-Powered Status Page + AI Incident Responder

> **For the autonomous coding session.** Single source of truth for this repo. Build in phase order. Every phase ends with **PROVE IT** — a real API response, a passing test, or a logged number against a real Datadog org. The resume bullets at the bottom are the contract: every one must be backed by something committed to the repo (an API response dump, a test log, an eval score).

---

## 0. What you're building & what actually matters

A status-page generator where **Datadog Synthetic Monitoring is the actual monitoring engine** — not a wrapper around your own polling code. You register real URLs as Datadog synthetic tests via the API, let Datadog's global infrastructure run the checks, and consume Datadog's Monitors, alerts, and result history to build: a public status page, an AI incident summarizer, a hallucination-catching eval, and — if time allows — confidence-gated auto-remediation for your own services.

**The credibility chain is: real Datadog org → real synthetic tests → a real failure you trigger on purpose → a real alert → a real LLM trace in Datadog LLM Observability → a real eval score.** Every phase's PROVE IT must trace back to something that actually happened in your Datadog account, not a mock.

### Scope decisions already made (do not re-expand)
- **Language:** Python 3.11. One service, one language, stay consistent.
- **Datadog does the checking.** Do not build your own poller/crawler — that would make Datadog decorative. Synthetic tests run on Datadog's schedule; you only consume results and receive alert webhooks.
- **LLM:** Anthropic Claude API for both the summarizer and the judge (two separate calls, not one call doing both jobs — the judge must be independent of the summarizer to mean anything).
- **Targets:** 2–4 real URLs you control (your own deployed side projects or a friend's, with permission). Auto-remediation (Phase 6) only ever applies to services in your own allow-list — never a third party's.
- **Priority if time runs out:** a working status page + real LLM Observability trace + one honest eval score beats an unfinished remediation phase. Phases 1–5 are the core project; Phase 6 is a stretch that meaningfully strengthens it but isn't required to be a complete, honest project.

---

## 1. Tech stack (final)

| Layer | Choice |
|---|---|
| Language | Python 3.11 |
| Web/API | FastAPI |
| Status page rendering | Jinja2 (server-rendered HTML, no frontend framework needed) |
| Storage | SQLite (incident log, eval scores, remediation log) |
| Monitoring engine | Datadog Synthetic Monitoring + Monitors (via Datadog API) |
| LLM | Anthropic Claude API |
| LLM tracing | Datadog LLM Observability SDK (`ddtrace` LLM Obs) |
| Alerting | Discord webhook (Monitor → webhook → your FastAPI endpoint) |
| Remediation targets | Hosting provider API (e.g. Render/Fly/Railway restart endpoint) — config-driven allow-list |
| CI | GitHub Actions (lint + unit tests) |
| Container | Docker (single container) |

---

## 2. Build order (phases)

Each phase: build → **PROVE IT** (real API call output / real test log / real eval number) → commit. Do not fabricate any output — if a phase can't produce a real number yet, the phase isn't done.

### Phase 1 — Provision real Datadog Synthetic tests ⭐
- Setup script reads a config file (`services.yaml`) listing your 2–4 target URLs.
- For each URL, create a Datadog Synthetic API test via the Datadog API (`POST /api/v1/synthetics/tests/api`), tagged consistently (e.g. `statuspack:true`, `service:<name>`).
- Script is idempotent — re-running it updates existing tests instead of duplicating them.

**PROVE IT:** commit the actual JSON response from Datadog confirming each test was created, plus a screenshot or API dump showing the tests live in your Datadog org's Synthetics list.

### Phase 2 — Monitors + real alert delivery ⭐
- Create a Datadog Monitor per synthetic test (or one grouped monitor) that fires on failure and recovery.
- Wire the monitor's notification to a webhook pointing at your FastAPI app; the app also forwards a formatted alert to a Discord webhook.
- Intentionally break one of your real target services (stop it, or point the test at a bad path) and let the failure propagate for real.

**PROVE IT:** log the timestamp the service actually went down, the timestamp the Datadog alert webhook hit your app, and the timestamp the Discord message landed. This latency number is the "paging within Xs of failure" bullet — it must come from a real triggered failure, not a hardcoded value.

### Phase 3 — Public status page ⭐
- FastAPI route pulls each test's recent result history via the Synthetics API (`GET /api/v1/synthetics/tests/{public_id}/results`).
- Render a status page: current status per service, uptime % over the tracked window, and a timeline of past incidents pulled from your SQLite incident log.

**PROVE IT:** a screenshot/HTML dump of the page correctly showing the real outage from Phase 2 (red during the outage window, green after recovery, with accurate duration).

### Phase 4 — LLM incident summarizer, traced in LLM Observability ⭐⭐
- On a failure webhook, pull the raw result data for that test (status codes, response time series, failing location(s), duration).
- Send that data to Claude with a prompt constrained to **only state what the data shows** — no speculation about root cause beyond the evidence (e.g. "5 consecutive 503s from the US-East location over 6 minutes, latency rising from 210ms to 4.8s before failure" is fine; "likely a database connection pool exhaustion" is not, unless the data actually shows that).
- Wrap this call with the Datadog LLM Observability SDK so it appears as a traced span (input, output, tokens, cost, latency).
- Post the summary to the status page's incident entry and to Discord.

**PROVE IT:** a real trace visible in your Datadog LLM Observability UI for the incident generated in Phase 2/3 (screenshot or exported trace JSON), including token count and cost.

### Phase 5 — Grounding eval (LLM-as-judge) ⭐⭐ (the differentiating piece)
- Build a small labeled set: 15–20 incident summaries, a mix of real ones from your system and a few you deliberately write with an unsupported root-cause claim injected.
- Build an independent judge prompt: given the raw failure data + the summary, does the summary state anything **not supported by the data**? Output a grounded/ungrounded verdict + confidence.
- Run the judge over your labeled set and submit the results as a custom eval via Datadog's LLM Observability evaluations (custom LLM-as-judge or external eval submission via the API).
- Report catch rate (how many of your deliberately-hallucinated summaries the judge correctly flagged) and false-positive rate (how many real, honest summaries it wrongly flagged).

**PROVE IT:** commit the labeled set, the judge's verdicts on each item, and the resulting catch rate / false-positive rate. This number is the "blocking X% of ungrounded claims" bullet — it must come from this actual labeled run, not an estimate.

### Phase 6 — Confidence-gated remediation (stretch) ⭐⭐⭐
- Per service in `services.yaml`, define a fixed allow-list of safe actions (e.g. `restart`, `rollback`) mapped to real hosting-provider API calls. No arbitrary command execution.
- On failure, Claude proposes an action **from the allow-list only**, with a confidence score, based on the failure data.
- The Phase 5 judge gates execution: action only fires if it's in the allow-list **and** confidence clears a threshold **and** the judge confirms the reasoning is grounded in the actual failure data. Otherwise, it falls through to Phase 4's summary + page-a-human behavior.
- Log every proposal, gate decision, and (if executed) whether the next synthetic check actually passed afterward.

**PROVE IT:** at least one real triggered failure where the gate correctly executed an allowed fix and the next Datadog synthetic check confirmed recovery, **and** at least one case where the gate correctly refused a low-confidence or out-of-list proposal. Both logged with real timestamps.

### Phase 7 — Polish: README, CI, Docker, final numbers table ⭐
- README explains the architecture, includes a diagram, and states plainly which parts of the resume bullets each phase backs.
- GitHub Actions running lint + your test suite. Dockerfile for the single service.
- Compile a final table: number of services monitored, alert latency, LLM Obs trace count, eval catch/false-positive rate, remediation stats if Phase 6 was built.

**PROVE IT:** CI green on the final commit; the numbers table checked into the README, each cell linked to the commit/log that produced it.

---

## 3. Where to spend vs save time

- **Spend** on: Phase 1 and 2 being genuinely real (a Datadog test that doesn't actually exist, or an alert you never triggered, poisons every later phase's credibility). Phase 5's labeled eval set — a sloppy 3-item set makes the whole eval bullet meaningless.
- **Save** on: status page visual design (plain, clean HTML is fine — this isn't a design project), and Phase 6's action list (2 actions — restart and rollback — is enough; don't build a general-purpose runbook engine).
- **Highest value-per-hour:** Phase 4 + 5 together. A traced LLM call plus one honest eval score is the single most differentiating pair in this project.

---

## 4. Interview talking points (put in README)

- **Why let Datadog run the checks instead of writing your own poller?** Multi-region synthetic checks, historical retention, and alerting infra are exactly what Datadog already solves well — rebuilding it would be redundant engineering, not a stronger project.
- **Why does the judge need to be a separate call from the summarizer?** A model grading its own work has no independent signal — it will tend to rubber-stamp itself. Separation is what makes the eval mean anything.
- **What does "grounded" mean here and why does it matter operationally?** An incident summary that states an unverified root cause can send an on-call engineer down the wrong path during a real outage — the cost of a hallucinated claim here isn't cosmetic.
- **Why gate remediation on confidence AND allow-list membership, not just one?** Confidence alone can be high and wrong; an allow-list alone doesn't stop a bad call within scope. Both together bound the blast radius.
- **What would you need before trusting this on someone else's infrastructure?** A much bigger labeled eval set, human-in-the-loop approval before the first several real executions, and audit logging — this version deliberately only touches services you own.

---

## 5. Resume bullets (the contract — every one must end up TRUE)

Fill X/Y/Z from the committed logs and eval runs. Never invent numbers — a smaller honest number is a stronger bullet than a padded one.

- Monitored **N** production services with Datadog Synthetic Monitoring across **M** global regions, auto-generating public status pages and paging on-call within **X**s of a real triggered failure (Phase 2 log).
- Built an LLM-as-judge eval in Datadog LLM Observability to catch ungrounded root-cause claims, blocking **X%** of hallucinated incident summaries across a labeled set of **N** examples (Phase 5 log).
- Traced every AI-generated incident summary end-to-end in Datadog LLM Observability, tracking token cost and latency per incident (Phase 4 log).
- *(If Phase 6 built)* Auto-resolved **X** of **N** triggered incidents via confidence-gated remediation (restart/rollback), with the eval correctly blocking **Y** low-confidence proposals from executing (Phase 6 log).

> **Bullet honesty rule:** every X/Y/Z must trace to a specific committed artifact (an API response, a test log, a labeled eval run) — not an estimate of what it "should" be. If your eval only catches 60% of hallucinations on a small set, say 60% on that set size. A small, real, specific number is a stronger signal than a big vague one.
