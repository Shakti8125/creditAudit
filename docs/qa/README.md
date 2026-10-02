# Remediation work stream: start here

> **Any new session picking up this work: read this file first, then `.agents/AGENTS.md`, then the plan section for the item you take.**
> This file holds the owner's decisions, the work queue with live status, the protocol for taking and finishing items, and the owner's open action items.

| | |
|---|---|
| **Status (2026-10-02)** | Audit done, plans done, owner decisions recorded. **No application code has been changed yet.** **D12 (AWS retired, backend local-only) changes the plan.** The re-scope is written and **awaits the owner's answers** (O11): see [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) and the cost report [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md). **Do not start AWS-dependent items** (PR-07, PR-18, C5's workflows, anything that needs ECS, S3 or CloudWatch). PR-00 now means local probes only. Before merging anything to `main`, the owner disables the AWS deploy workflows (O9). |
| **Where the docs live** | On `main` (merged in PR #3 and PR #4). |
| **Audit** | [live-app-audit-2026-09-30.md](live-app-audit-2026-09-30.md): findings QA-001..QA-026 with evidence |
| **Master plan** | [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md): every finding plus NEW-01..NEW-08, the PR breakdown and verification steps |
| **AWS exit plan** | [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md): D12, the workflow shutdown steps, the item-by-item re-scope, new items X-01..X-03, V-01 and L-01..L-03, and the questions for the owner. Cost report: [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md). |
| **Corpus plan** | [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md) ("CorpusPlan"): the regulatory corpus design, C1..C7 plus C2b |
| **Live app** | **No live backend.** The AWS stack is gone: on 2026-10-02 `/api/health` returns 502 `DNS_HOSTNAME_EMPTY`. The frontend `https://creditaudit.vercel.app` still loads, but its sign-in cannot work until V-01 adds an offline view. The app now runs locally only (plan §5, L-01). |

---

## 1. Background in five lines

1. The QA audit confirmed the regulatory corpus is empty in production: the Pinecone regulatory namespace has 0 vectors and the `regulatory_standards` catalog has 0 rows. The only regulatory "content" is 10 hardcoded paragraphs in `hybrid_retriever.py`.
2. Planning showed those 10 paragraphs and the old seed script contain thresholds that **CBUAE never published** (NEW-02). **Never run `scripts/seed_regulatory_standards.py` or `scripts/index_regulatory_corpus.py`.**
3. Separately, gap analysis and compare fail (QA-005), the reranker is 100% down (QA-006) and the Gemini fallback is dead (retired models). Follow-up chat turns return 422 (QA-004), rate limiting is not enforced (QA-007), and the Vercel→ALB hop is plain HTTP (NEW-01).
4. The fix is sequenced as P0a (stop the bleeding) → P0b (real corpus) → P1 (correctness and UX) → P2 (hardening).
5. The owner took the decisions in §2 on 2026-09-30. They are binding for every item below.

---

## 2. Owner decisions (2026-09-30), binding

| # | Question | Decision | What it changes (details in the linked sections) |
|---|---|---|---|
| **D1** (revised 2026-09-30) | Corpus scope | **Include Basel III and IFRS 9 in full text.** This is a personal, non-commercial project. | Basel III (Basel Framework CRE20-22, CRE30-36, RBC20, RBC30) and the IFRS 9 issued standard go live in **full text**, together with the CBUAE Tier 1 documents (CorpusPlan §2). The ingest enforces a **licence profile** (`CORPUS_LICENSE_PROFILE=personal`, CorpusPlan §2.1): attribution under every Basel and IFRS 9 citation, a "personal, non-commercial project" notice in the app, source files only in private S3 and never in git. Switching the profile to `commercial` makes the ingest refuse those sources in one step. Heads-up: open self-registration (D5) means anyone who signs up can read retrieved passages; revisit if the app is promoted or monetised. The IFRS 9 PDF needs a free ifrs.org login, so the owner downloads it (O3). New PR **C2b**. CBUAE Tier 2 follows in P1. |
| **D2** | AGENTS.md amendments | **Approved** (planner's recommendation). | Applied to `.agents/AGENTS.md` in this change: (a) `regulatory_*` tables are global, with no `tenant_id`; (b) manifest-listed public regulatory text may go to providers unmasked, after the bank-name lint; (c) embeddings never fail over across providers; (d) rule 9 is now "exact model IDs from config", replacing the pin to a retired model. |
| **D3** | Hardcoded fallback and relabelling | **Approved** (planner's recommendation). | Production has no fake fallback: `/regulatory/search` returns 503 while the corpus is empty. Gini, AUC, KS, PSI, HL and Brier results are labelled "Tenant policy (MMS 9.4.1)" instead of "CBUAE MMG" (C7), with a release note. Interim P0a item: label the old citations "illustrative sample" (NEW-02). |
| **D4** | Gemini | **Upgrade it and keep it as the backup provider.** | PR-01: NVIDIA stays primary. Gemini is used **only on failover**: latency-based promotion is off by default. Gemini covers `generate`, `generate_stream` and structured output. It is **never** used for embeddings (D2c), and LLM-as-reranker is off by default. Default model `gemini-3.6-flash`, then `gemini-3.5-flash`, then the `gemini-flash-latest` alias as a last resort (PR-01b chains, D10). **Do not use `gemini-2.5-flash`** (shutdown announced for 2026-10-16). The **free (unpaid) Gemini tier** is used (D11); no billing. |
| **D5** | Self-registration | **Keep open self-registration.** | Registration always creates a *new* tenant with the registrant as its ADMIN (`api/auth.py:27-39`), so there is no tenant takeover. PR-06 and PR-14 add abuse and cost controls: IP and global register caps, a daily AI-call quota per FREE tenant, and an optional Turnstile CAPTCHA behind a flag. There is **no** invite-only mode and no email verification for now. **Update (D12): the abuse and cost controls are deferred until the backend is exposed to anyone but the owner (plan §7).** |
| **D6** (superseded by D12) | HTTPS for the API | **"Choose the most optimal" → CloudFront with a VPC origin in front of an *internal* ALB. No custom domain.** | PR-07: the default `*.cloudfront.net` certificate is free and needs no domain. The CloudFront→ALB leg stays on AWS's private network. The ALB is no longer reachable from the internet, which also closes the direct-ALB bypass of Vercel and the public `/docs`. Vercel rewrites to `https://<dist>.cloudfront.net`. Upgrade path: add a custom domain and an ACM certificate to the distribution later; nothing else changes. Details in master plan NEW-01. |
| **D10** | LLM robustness (owner request, 2026-09-30) | **Make the LLM layer robust to frequent model updates.** | New **PR-01b** (master plan §4 NEW-09): model IDs move from code into role-based **model chains** (`models.yaml`, plus an optional SSM override that needs no deploy); a retired model is remembered as **gone** after one failed call; errors are classified so each kind gets the right retry or failover; unknown new models work with conservative capability defaults; a **daily canary** runs live contract tests on every candidate, discovers newer GA models and **opens a PR** adding them as fallbacks; traces record the model that actually served each call; a quality check runs whenever the active model changes. Embeddings stay a single pinned model (never a chain). |
| D7 | Demo account (planner default) | No shared demo account in production. | PR-16 removes the fictitious-but-real-bank demo credentials from the docs. QA sessions use per-session QA accounts (§6). |
| D8 | Rate-limit tiers (planner default) | FREE capacity 30, refill 1/s; cheap GETs cost 1; expensive calls per the cost table; daily AI quota for FREE tenants. | PR-06. The owner can override. |
| D9 (superseded by D12) | Environment isolation (planner default) | Verify in PR-00; split staging and prod task definitions (PR-18) **before** the first corpus ingest to staging. | This is a gate on C5. |
| **D11** | Cost (owner, 2026-09-30) | **Build it free of cost.** | Use free tiers only and add **no new paid services**: (1) **Gemini**: the free, unpaid API tier. It covers the Flash models used by the backup role, with limits of roughly 10-15 requests per minute and some hundreds to about 1,500 requests per day per model, which is ample for a failover-only backup. Pro models need billing and are not used. (2) **Accepted trade-off**: on the unpaid tier, Google may use prompts and outputs to improve its products, and human reviewers may read them. Prompts are masked before they leave the app (no bank, organisation or person names), but numbers and document wording are not, so **do not upload real confidential bank documents while Gemini is on the free tier**. Use synthetic or public documents. (3) **Everything else in the plan**: NVIDIA developer API (free, rate-limited), Pinecone Starter, Upstash free tier, CloudFront free tier, SSM standard parameters, GitHub Actions (free for this public repo), Dependabot. AWS WAF (PR-07 item 8) is **not** used, because it is paid. (4) **Not free, and outside this plan**: the existing AWS base (Fargate, ALB, NAT gateway, and RDS after its free-tier year). The plan adds no new paid AWS resources: PR-07 swaps one ALB for another, and the S3 corpus bucket costs cents. A cost-reduction review of the base infra would be a separate request. |
| **D12** (owner, 2026-10-02) | Where the app runs | **AWS is retired and the backend runs locally, only to demo to interviewers. Nothing paid runs anywhere.** The AWS account was deactivated after the always-on stack used up its credits ([cost report](aws-cost-report-2026-10-02.md)). | Supersedes **D6** (CloudFront edge) and **D9** (staging split). Extends **D11** (free of cost) from building to hosting. Defers the public-exposure items (abuse controls, auth hardening). The consequences are **proposed**, not yet confirmed: [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) (questions in its §9). |

---

## 3. Work queue and live status

**Rules:** take the first `TODO` row whose dependencies are `DONE`, unless it is marked parallel-safe. Rows in the same "lane" can run in parallel sessions. Update the status in **your first commit** and again when you finish. Status values: `TODO`, `IN PROGRESS (<branch>)`, `BLOCKED (<reason>)`, `DONE (<PR link>, <date>)`, plus (2026-10-02, D12) `SUPERSEDED (<why>)` and `DEFERRED (<trigger>)`. Rows marked *awaiting owner* depend on an answer in the plan's §9.

| Order | ID | Title (plan section) | Depends on | Lane | Effort | Status |
|---|---|---|---|---|---|---|
| 0 | — | Live QA audit | — | — | — | DONE (commit `1d9dbbd`, 2026-09-30) |
| 0 | — | Remediation and corpus plans, owner decisions, AGENTS.md amendments | — | — | — | DONE (commits `aeda727` and this one, 2026-09-30) |
| 0 | **X-01** | Archive the AWS deploy workflows; Vercel's Git integration deploys the site (plan §3) | owner O9, Q2 | E | S | TODO (awaiting owner: Q2) |
| 0 | **X-02** | Trim PR #5: keep `pr00_probe.py`, drop `pr00_aws.py` and its test, rewrite the runbook for local runs (plan §5) | — | A | S | TODO |
| 0 | **X-03** | Docs and AGENTS.md for the local-only world: banners, archive `deployment_steps.md`, README §6 (plan §4.6, §5) | Q3 | H | S | TODO (awaiting owner: Q3) |
| 1 | **V-01** | Vercel front door: drop the dead `/api` rewrite, add `BackendGate` and an offline view (plan §5) | X-01 | H | S | TODO |
| 1 | **L-01** | Local demo kit: one env file, compose fixes, Docling warm-up, seed, preflight, reset, `docs/LOCAL_DEMO.md` (plan §5) | PR-00 | H | M | TODO |
| 1 | **PR-00** | **Rescoped (D12), called PR-00L in the exit plan: local probes only.** Run `backend/scripts/diag/pr00_probe.py` with a local `.env`: provider probes, Pinecone describe, structured-output variants, embedding dimension. The ECS, CloudWatch and CloudTrail steps are void (master §2, plan §4.2) | owner: local `.env` (O10) | A | S | TODO. Tooling and sandbox checks are in [PR #5](https://github.com/Shakti8125/creditAudit/pull/5) (`ccr-69721f6f-73mabp`); the runbook is rewritten for local use by X-02. |
| 2 | PR-01 | Providers: NVIDIA reranker successor; **Gemini upgraded as backup (D4)**; embeddings pinned, no failover; per-method breakers; startup probe; weekly canary (master QA-006) | PR-00 | A | S/M | TODO |
| 2 | PR-02 | Structured output: `nvext.guided_json`, thinking off, validate + one repair, token budgets; works on NVIDIA **and** Gemini (master QA-005) | PR-00 | A | M | TODO |
| 3 | **PR-01b** | **Model lifecycle resilience (D10)**: process-wide provider pool, model chains in config, gone-model memory, error taxonomy, capability adapters, deadlines, daily canary with discovery and auto-PR. **Rescoped (D12):** the SSM override becomes a local file `LLM_MODELS_OVERRIDE_FILE`, the CloudWatch alarm becomes a GitHub issue; after M1 (master NEW-09, plan §4.2) | PR-01, PR-02 | A | M/L | TODO |
| 2 | PR-04 | Chat prompt privacy: `DOC-n` aliases, deterministic registry, no filenames in Pinecone (master QA-004, QA-011) | — | B | M | TODO (parallel-safe) |
| 2 | PR-05 | Masking: public vocabulary (incl. Basel/IFRS terms) and phone masking (master QA-009, QA-010) | — | C | S/M | TODO (parallel-safe) |
| 3 | PR-03 | UI: surface gap-analysis failures, truncation indicator (master QA-023) | PR-02 | A | S | TODO |
| 3 | PR-06 | Rate limiting, **lite only (D12)**: config validation, state in `/health`, `EVAL` fallback, in-process fallback bucket (master QA-007). The `/auth` IP limiter, register caps, daily AI quota, Turnstile and alarms are **deferred** (plan §4.2, §7) | PR-00 | D | S | TODO (lite); rest DEFERRED (trigger: backend exposed to others) |
| 3 | PR-07 | ~~Edge: CloudFront + VPC origin + internal ALB (D6), `vercel.json` → https, SSE heartbeat, API docs off~~ (master NEW-01, QA-020) | — | E | — | SUPERSEDED (D12: no AWS edge). NEW-01 closed, QA-020 accepted while local-only, the dead rewrite is fixed by V-01, the SSE heartbeat is deferred |
| 3 | NEW-02 interim | Label old `CBUAE-MMG-2022` citations "illustrative sample, not official text" (master NEW-02) | — | C | S | TODO (parallel-safe) |
| 4 | PR-18 | ~~Infra hygiene: separate staging task definition~~, Pinecone tenant namespaces (master NEW-06, NEW-07) | — | E | S | SUPERSEDED (D12: the staging split and NEW-06 are void). NEW-07 stays as an optional guard (plan §4.2) |
| 4 | C1 | Corpus: migration, ORM, manifest schema **with the licence profile checks**, catalog upsert, seed/index shims that exit 1 (CorpusPlan §20) | — | F | M | TODO (parallel-safe) |
| 5 | C2 | Corpus: `rulebook_html` parser, `RegulatoryChunker`, lint (CBUAE sources) | C1 | F | L | TODO |
| 5 | **C2b** | Corpus: `bis_html` parser (Basel III CRE20-22, CRE30-36, RBC20, RBC30) and `ifrs_pdf` parser (IFRS 9), both **full text** (D1 revised); licence profile, attribution and notice (CorpusPlan §2.1, §6.1) | C1 | G | M/L | TODO (parallel with C2) |
| 6 | C3 | Corpus: ingest orchestrator, CLI, **local source store instead of S3 (D12)**, ledger, Pinecone upsert/GC, `CorpusRegistry`, BM25, stats, health | C2, C2b, PR-01 | F | L | TODO |
| 7 | C4 | Corpus: dual-scope retrieval, prompts, citation fields, remove the hardcoded corpus, 503 | C3, PR-04 | F | M | TODO |
| 8 | C5 | **C5L (D12): local ingest run.** `acquire`, `verify`, `ingest` against the local stack and record the counts in §5. No workflows, IAM, S3 or staging (plan §4.4) | C4, PR-05 | F | S | TODO |
| 9 | C6 | Golden set v2 (incl. Basel and IFRS 9 cases) and eval baseline (CorpusPlan AC5) | C5, PR-01 | F | M | TODO |
| 10 | C7 | Thresholds wiring: tenant-policy relabel (D3), `regulatory_refs`, catalog-driven gap analysis (master QA-008) | C6, PR-02 | F | M | TODO |
| P1 | PR-08 | Input validation: settings bounds, question length (master QA-012, QA-018) | — | H | S | TODO (parallel-safe) |
| P1 | PR-09 | Safe markdown rendering and citation chips (master QA-014) | — | H | S/M | TODO (parallel-safe) |
| P1 | PR-10 | Streaming Regulatory Q&A (master QA-015) | PR-01, PR-02, C4 | F | M | TODO |
| P1 | PR-11 | Mobile header and menu (master QA-013) | — | H | S/M | TODO (parallel-safe) |
| P1 | PR-12 | Regulatory Library UX (master QA-016) | C1, C4 | F | M | TODO |
| P2 | PR-13 | Overlay accessibility (master QA-017) | — | H | S | TODO |
| P2 | PR-14 | Auth hardening: refresh rotation, logout revocation, **self-registration kept (D5)** (master QA-019) | PR-06 | D | M | DEFERRED (D12; trigger: backend exposed to others) |
| P2 | PR-15 | Document lifecycle (master QA-021) | — | H | S/M | TODO |
| P2 | PR-16 | Docs: scrub the real bank names and credentials when `deployment_steps.md` is archived (QA-024); the CorpusPlan runbook becomes local. The rest is absorbed by X-03, L-01 and L-02 (master QA-022, QA-024) | X-03 | H | S | TODO |
| P2 | PR-17 | Self-hosted fonts (master QA-025). The Docling warm-up (QA-026) moved into L-01 | — | H | S | TODO |
| P1 | C-T2 | CBUAE Tier 2 sources (risk management regulation, capital adequacy); link CAR, Tier 1 and NPA thresholds (CorpusPlan §2) | C5 | F | M | TODO |
| P1 | **L-02** | Portfolio README, screenshots, demo video (recorded last), repo tidy (plan §5) | M1 done | H | S/M | TODO |
| — | L-03 | Optional: CI smoke test of the demo kit, only if the image fits the runner (plan §5) | L-01 | H | S | OPTIONAL |
| — | C2c | *Not scheduled.* Commercial-profile fallback modes (Basel excerpts, IFRS 9 summary cards). Only if the app goes commercial without licences (CorpusPlan §6.3). | C2b | G | M | NOT SCHEDULED |

Lanes: A = providers and LLM resilience, B = chat privacy, C = masking, D = auth and limits, E = infra, F = corpus main line, G = Basel and IFRS, H = frontend and validation.

---

## 4. Protocol for an agent taking an item

1. **Read first**: `.agents/AGENTS.md` (the rules, including the 2026-09-30 amendments), this README, and the item's plan section. The plans cite `file:line` at `48816f7`. Re-check them, because earlier PRs may have moved code.
2. **Claim it**: in your first commit, set the tracker row to `IN PROGRESS (<branch>)`. Use the branch your session was assigned. If you choose it yourself, use `fix/<id>-<slug>` (e.g. `fix/pr-01-providers`). Target `main`. One tracker item per PR, unless the plan groups them.
3. **Implement to the plan.** If the code contradicts the plan, fix the plan text in the same PR and add a line to §8 (change log). Never silently diverge. If an owner decision would have to change, stop and ask the owner. Do not decide it yourself.
4. **Local checks before pushing** (from `HANDOFF.md` §1):
   ```bash
   cd backend && DATABASE_URL=sqlite+aiosqlite:///./ci_test.db python -m pytest -q && python -m ruff check app --select E9,F63,F7,F82
   cd ../frontend && npm ci && npm run lint && npm run build
   ```
   Add the tests listed for the item in the plan.
5. **Definition of done**: merged to `main`, CI green, deployed, **and** the item's "Prod verification" steps run and recorded in §5 below (date, what was run, result). For infra items, record the resource IDs, never secrets.
6. **Close out**: set the row to `DONE (<PR link>, <date>)` and add a §8 change-log line. If you found new issues, add them to the master plan as `NEW-09`, `NEW-10`, and so on, with severity and evidence, and add a tracker row.

**Safety rules (production)**
- Test production only with QA accounts (§6). Only delete or modify objects your session created. Restore any settings you change.
- Keep LLM usage in production modest: at most one eval run per verification unless the item says otherwise.
- AWS: read-only unless the item is an infra item **and** the owner has approved or is executing it (O5). Print env and secret **names** only, never values.
- Never commit secrets or passwords. The QA account password is **not** in the repo.
- Never run the old seed or index scripts (see §1).
- Corpus: never ingest full text for a source whose manifest `license.status` does not allow it (CorpusPlan §2.1).

---

## 5. Verification log

Append one line per verification run against staging or production.

| Date | Item | Environment | What was run | Result | By (session) |
|---|---|---|---|---|---|
| 2026-09-30 | Audit | prod | Full UI and API sweep with Playwright (audit §2) | 26 findings | QA session |
| 2026-09-30 | PR-00 steps 1, 2, 5 | prod (AWS) | AWS connector, first call (ECS and STS describe) | **Not run.** The connector answered "needs sign-in again" (O1 reopened). Nothing was read from AWS. | PR-00 session (`ccr-69721f6f-73mabp`) |
| 2026-09-30 | PR-00 (sandbox) | prod | Plain HTTP to the ALB: `GET /health`, `/docs`, `/openapi.json` | `/health` 200 with `db: connected`. `/docs` and `/openapi.json` return 200 to anyone, so QA-020 still holds. The live OpenAPI has 40 paths, exactly the set of routes declared on `main`, and the backend code is unchanged since `48816f7`. With the successful "Deploy Production" run for `e338639` (2026-09-30, 10:36 UTC), this says ECS runs `main`'s backend. | PR-00 session |
| 2026-09-30 | PR-00 steps 3-4 (reachability) | sandbox | `curl` to the provider hosts, no keys | The sandbox egress policy blocks `integrate.api.nvidia.com`, `ai.api.nvidia.com` and `api.pinecone.io`. `generativelanguage.googleapis.com` is reachable. The keys are not in the sandbox either, so steps 3-4 need the one-off ECS task (runbook step B, O8). | PR-00 session |
| 2026-09-30 | PR-00 step 4 (web re-check) | public docs | Live fetch of Google's Gemini deprecations page and NVIDIA's `llama-3_2-nv-rerankqa-1b-v2` page | **Gemini**: `gemini-2.0-flash` shut down 2026-06-01 (replacement `gemini-3.6-flash`). `text-embedding-004` shut down 2026-01-14. `gemini-embedding-001` shuts down 2028-05-14. `gemini-3.5-flash`, `gemini-3.6-flash`, `gemini-3.8-flash` (released 2026-09-02) and `gemini-embedding-2` have no shutdown date. **`gemini-2.5-flash`: "No shutdown date announced"**, although the plan says 2026-10-16 (see §8). **NVIDIA**: "This NIM Endpoint has been deprecated"; the page names no successor. This is documentation only; it does not replace the keyed probes. | PR-00 session |
| 2026-10-02 | AWS exit (facts) | prod, Vercel, GitHub | Live fetch of `creditaudit.vercel.app` and `/api/health`; Vercel project and deployment list; GitHub Actions run history; DNS | **Backend gone**: `/api/health` returns 502 `DNS_HOSTNAME_EMPTY`; the old ALB hostname does not resolve. The Vercel alias is public and serves the login page. Vercel's Git integration builds previews and production. `deploy-production.yml` ran 21 times (first success 2 Sep 16:19 UTC, none for 22.9 days, last 30 Sep); `deploy-staging.yml` ran 0 times. The AWS connector still asks for sign-in, and the GitHub proxy blocks the secrets API. | PR-00 session |
| 2026-10-02 | AWS cost (modelled) | AWS Price List | ECS, VPC, EC2, RDS, CloudWatch and ECR offer files plus the ELB pricing page; no bill access | About $205 a month as documented ($126 at the minimum plausible footprint, $261 at the maximum). Fargate and the NAT gateways are about 74%. $113.62 a month bills with zero tasks running. See [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md). | PR-00 session |

---

## 6. Environment notes for agents

- **Running the app (D12)**: locally only. A cloud sandbox cannot reach the owner's laptop, so a sandbox session cannot drive the real app. To drive the frontend, run backend and frontend locally; the Vite proxy in `frontend/vite.config.ts` targets `localhost:8001` (L-01 packages this). The sandbox's default network policy blocks `*.vercel.app` (O6); the Vercel alias can be checked with the Firecrawl scraper.
- **QA accounts**: the AWS database is gone, so the earlier QA tenants no longer exist. Register a fresh account named `qa.agent.<YYYYMMDD>@example.com` with tenant `QA Test Tenant <YYYYMMDD>`, which also exercises self-registration (D5). Record the email, never the password, in §5.
- **Audit leftovers**: they lived in the AWS database and are gone with it.
- **AWS**: retired (D12). The names (region `us-east-1`, cluster `modelaudit-cluster`, services `modelaudit-prod-service` and `modelaudit-staging-service`, task definition `modelaudit-backend-task`) are kept for history in the archived deployment guide. The account's state and what to do about it: plan §2 (O10).
- **Model churn**: do not trust any model ID in these docs without re-checking it. Google and NVIDIA retire models often. PR-00 probes, and later the PR-01b canary, are the source of truth.
- **Unverified items to settle in PR-00 (now local probes)**: the live Pinecone index dimension versus `nemotron-3-embed-1b` (2048 native), the structured-output parameter shape honoured by the hosted NIM (QA-005), and the Pinecone plan tier (NEW-07; the Pinecone API does not expose it, so the owner reads it in the console). **All still open**: the probe is ready ([pr-00-runbook.md](pr-00-runbook.md)) but has not run against real keys. **Void under D12**: the rate-limiter production config (QA-007) and whether staging and prod share the DB (NEW-06).

---

## 7. Owner action items

| # | Action | Blocks | Status |
|---|---|---|---|
| O1 | Re-authorise the AWS connector in claude.ai connector settings (or run the PR-00 commands yourself and paste the output into the PR). The owner re-authorised it on 2026-09-30, but the PR-00 session's first call still got "needs sign-in again". Re-authorise at claude.ai/customize/connectors, then start a **new** session (connectors load at session start). The alternative is to run `python -m scripts.diag.pr00_aws inspect` yourself ([runbook](pr-00-runbook.md) step A). | PR-00, and through it PR-01, PR-02, PR-06, PR-07 | CLOSED (superseded by D12, 2026-10-02): the AWS inspection is void |
| O2 | ~~Billing-enabled Gemini key~~ Not needed (D11: free tier). The existing NVIDIA and Gemini keys are already in AWS and the GitHub secrets; no rotation. | — | CLOSED (2026-09-30) |
| O3 | Download the IFRS 9 issued-standard PDF from ifrs.org with a free "Basic" account, then either upload it with `python -m scripts.regulatory acquire --from-file <pdf> --doc-key ifrs-9` or hand it to the session running C5. It must not be committed to git. | IFRS 9 ingest (C5) | OPEN |
| O4 | ~~Ask BIS for permission for full Basel text~~ | — | CLOSED: not needed (D1 revised: personal, non-commercial) |
| O5 | Approve, or run, the infra changes: the CloudFront distribution with VPC origin, the internal ALB and the security groups (PR-07); the S3 bucket and task-role policy (C5); and the staging task definition (PR-18) | PR-07, C5, PR-18 | CLOSED (superseded by D12): no PR-07, S3 corpus bucket or staging task definition |
| O6 | Optional: allow `creditaudit-8rht0lyiq-shaktishubhankar.vercel.app` in the cloud environment's network settings so agents can test the Vercel site directly | Nothing (there is a workaround, §6) | OPEN |
| O7 | ~~Review IFRS 9 reference cards~~ | — | CLOSED: not needed (D1 revised: full text, no summary cards) |
| O8 | Approve (or run) the PR-00 one-off probe task: one Fargate task from the prod task definition, in the prod service's network, that runs `scripts/diag/pr00_probe.py` pinned to commit `c6953eb` and SHA-256 `d8c822e8…2cc570`. It prints names, status codes and booleans only, makes about 14 NVIDIA calls and at most 5 Gemini generation calls on the free tiers, and writes nothing ([runbook](pr-00-runbook.md) step B). | PR-00 steps 3-4, and through them PR-01, PR-02, PR-06 | CLOSED (superseded by D12): the probes run locally |
| O9 | **Urgent, one minute:** in GitHub, Actions, disable the *Deploy Production* and *Deploy Staging* workflows (plan §3, W0) **before merging PR #5 or anything else to `main`**; otherwise the push turns `main` red. | merging to `main` | OPEN |
| O10 | AWS account follow-up (plan §2): find out the plan type (Free plan or legacy/Paid) and any balance; **do not upgrade** to reopen; export the Cost Explorer CSVs if actual numbers are wanted ([cost report](aws-cost-report-2026-10-02.md) §7); delete the AWS secrets from GitHub (plan §3, W2); create a local `backend/.env` with provider keys from their dashboards and a new RS256 key pair (or leave it empty for ephemeral dev keys). | PR-00, X-01, L-01 | OPEN |
| O11 | Answer the six questions in [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) §9 (D12 wording, Vercel front door, AGENTS.md amendments, local seed account, interview date, AWS plan type). | X-01, X-03, the scheduling of M1-M3 | OPEN |

---

## 8. Change log

- 2026-10-02 (AWS exit): **D12**: the AWS account was deactivated; the backend runs locally, only to demo, and nothing paid runs anywhere. Added [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md) (modelled; the bill could not be read) and [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) (workflow shutdown steps, item-by-item re-scope, new items X-01..X-03, V-01, L-01..L-03, questions Q1-Q6). Tracker: PR-00 rescoped to local probes; PR-07 and PR-18 superseded; PR-06 reduced to lite; PR-14 deferred; C3 and C5 rescoped to a local source store and a local ingest (C5L); PR-01b, PR-16 and PR-17 adjusted; O1, O5 and O8 closed; O9-O11 added. D6 and D9 are superseded and D5's controls are deferred. The consequences are **proposed pending Q1-Q6**; `.agents/AGENTS.md` is **not** amended yet (plan §4.6). Banners added to the two plans, HANDOFF §6-7 and `deployment_steps.md`.
- 2026-09-30 (PR-00, part 1): verification tooling (`backend/scripts/diag/pr00_probe.py`, `backend/scripts/diag/pr00_aws.py`, and tests that no secret, env value, account ID or tenant ID reaches the output) and [pr-00-runbook.md](pr-00-runbook.md). Master plan §2 changes: the Gemini key goes in a header, the planned `structured_output_probe.py` is folded into `pr00_probe.py` with a seventh, as-deployed variant, and a CLI command that printed an env value is removed. Sandbox checks are recorded in §5. O1 is reopened (the AWS connector asked for sign-in again) and O8 is added (approve the probe task). **For the owner**: Google's deprecations page lists no shutdown date for `gemini-2.5-flash`, although D4, master plan §0 and AGENTS.md rule 9 cite 2026-10-16. D4's exclusion of 2.5-flash stays in force; the stated reason needs the owner's confirmation or a correction. `gemini-3.8-flash` (2026-09-02) is newer than the D4 default and is included in the probe.
- 2026-09-30 (latest): D11 (free of cost). The Gemini backup uses the free unpaid tier: O2 is closed, and real confidential documents must not be uploaded while it is in use. PR-01b gains a `NotEntitled` error class for paid-only models; WAF is dropped from PR-07. The existing keys stay (no rotation). O1 (AWS connector) was re-authorised by the owner; it takes effect in a new session.
- 2026-09-30 (later): The owner revised D1 (Basel III and IFRS 9 in full text, personal non-commercial project; O4 and O7 closed; O3 is now a manual PDF download) and added D10 (LLM robustness). The master plan gains NEW-09 (a per-request router throws away all resilience state), NEW-10 (the Gemini provider has no resilience) and PR-01b. The corpus plan gains the licence profile, the `ifrs_pdf` parser and C2c (not scheduled). AGENTS.md rule 9 was re-amended for model chains.
- 2026-09-30: Live QA audit (`live-app-audit-2026-09-30.md`); remediation and corpus plans; owner decisions D1-D6 recorded; planner defaults D7-D9; `.agents/AGENTS.md` amended per D2; `HANDOFF.md` points here; the plans were updated for D1 (C2b, licence gates), D4 (Gemini backup), D5 (self-registration controls) and D6 (CloudFront).
