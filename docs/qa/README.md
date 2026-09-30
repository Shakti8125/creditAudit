# Remediation work stream: start here

> **Any new session picking up this work: read this file first, then `.agents/AGENTS.md`, then the plan section for the item you take.**
> This file holds the owner's decisions, the work queue with live status, the protocol for taking and finishing items, and the owner's open action items.

| | |
|---|---|
| **Status (2026-09-30)** | Audit done, plans done, owner decisions recorded. **No application code has been changed yet.** Next item: **PR-00** (see §3). |
| **Where the docs live** | Branch `ccr-39058048-nevlit`. If you are on `main` and `docs/qa/` is missing, fetch that branch or check whether it has been merged. |
| **Audit** | [live-app-audit-2026-09-30.md](live-app-audit-2026-09-30.md): findings QA-001..QA-026 with evidence |
| **Master plan** | [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md): every finding plus NEW-01..NEW-08, the PR breakdown and verification steps |
| **Corpus plan** | [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md) ("CorpusPlan"): the regulatory corpus design, C1..C7 plus C2b |
| **Live app** | Frontend `https://creditaudit-8rht0lyiq-shaktishubhankar.vercel.app/` (Vercel, built from `main` @ `48816f7`). Backend: FastAPI on ECS behind `http://modelaudit-alb-1304868163.us-east-1.elb.amazonaws.com` (Vercel rewrites `/api/*` there). |

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
| **D1** | Corpus scope | **Include Basel and IFRS 9** at go-live, together with the CBUAE Tier 1 documents. | Basel CRE20-22 and CRE30-36, plus IFRS 9 impairment, move from "maybe later" to go-live scope (CorpusPlan §2). Ingest is **licence-gated**: Basel runs in `brief_excerpt` mode until BIS gives written permission, and IFRS 9 runs in `reference_only` mode until the IFRS Foundation grants a licence (CorpusPlan §2.1, §6.3). New PR **C2b**. CBUAE Tier 2 (risk management regulation, capital adequacy) follows in P1. |
| **D2** | AGENTS.md amendments | **Approved** (planner's recommendation). | Applied to `.agents/AGENTS.md` in this change: (a) `regulatory_*` tables are global, with no `tenant_id`; (b) manifest-listed public regulatory text may go to providers unmasked, after the bank-name lint; (c) embeddings never fail over across providers; (d) rule 9 is now "exact model IDs from config", replacing the pin to a retired model. |
| **D3** | Hardcoded fallback and relabelling | **Approved** (planner's recommendation). | Production has no fake fallback: `/regulatory/search` returns 503 while the corpus is empty. Gini, AUC, KS, PSI, HL and Brier results are labelled "Tenant policy (MMS 9.4.1)" instead of "CBUAE MMG" (C7), with a release note. Interim P0a item: label the old citations "illustrative sample" (NEW-02). |
| **D4** | Gemini | **Upgrade it and keep it as the backup provider.** | PR-01: NVIDIA stays primary. Gemini is used **only on failover**: latency-based promotion is off by default. Gemini covers `generate`, `generate_stream` and structured output. It is **never** used for embeddings (D2c), and LLM-as-reranker is off by default. The model ID comes from config, default `gemini-3.6-flash`. **Do not use `gemini-2.5-flash`** (shutdown announced for 2026-10-16). Owner action O2: use a billing-enabled key. |
| **D5** | Self-registration | **Keep open self-registration.** | Registration always creates a *new* tenant with the registrant as its ADMIN (`api/auth.py:27-39`), so there is no tenant takeover. PR-06 and PR-14 add abuse and cost controls: IP and global register caps, a daily AI-call quota per FREE tenant, and an optional Turnstile CAPTCHA behind a flag. There is **no** invite-only mode and no email verification for now. |
| **D6** | HTTPS for the API | **"Choose the most optimal" → CloudFront with a VPC origin in front of an *internal* ALB. No custom domain.** | PR-07: the default `*.cloudfront.net` certificate is free and needs no domain. The CloudFront→ALB leg stays on AWS's private network. The ALB is no longer reachable from the internet, which also closes the direct-ALB bypass of Vercel and the public `/docs`. Vercel rewrites to `https://<dist>.cloudfront.net`. Upgrade path: add a custom domain and an ACM certificate to the distribution later; nothing else changes. Details in master plan NEW-01. |
| D7 | Demo account (planner default) | No shared demo account in production. | PR-16 removes the fictitious-but-real-bank demo credentials from the docs. QA sessions use per-session QA accounts (§6). |
| D8 | Rate-limit tiers (planner default) | FREE capacity 30, refill 1/s; cheap GETs cost 1; expensive calls per the cost table; daily AI quota for FREE tenants. | PR-06. The owner can override. |
| D9 | Environment isolation (planner default) | Verify in PR-00; split staging and prod task definitions (PR-18) **before** the first corpus ingest to staging. | This is a gate on C5. |

---

## 3. Work queue and live status

**Rules:** take the first `TODO` row whose dependencies are `DONE`, unless it is marked parallel-safe. Rows in the same "lane" can run in parallel sessions. Update the status in **your first commit** and again when you finish. Status values: `TODO`, `IN PROGRESS (<branch>)`, `BLOCKED (<reason>)`, `DONE (<PR link>, <date>)`.

| Order | ID | Title (plan section) | Depends on | Lane | Effort | Status |
|---|---|---|---|---|---|---|
| 0 | — | Live QA audit | — | — | — | DONE (commit `1d9dbbd`, 2026-09-30) |
| 0 | — | Remediation and corpus plans, owner decisions, AGENTS.md amendments | — | — | — | DONE (commits `aeda727` and this one, 2026-09-30) |
| 1 | **PR-00** | Verification runbook: ECS env names, CloudWatch queries, Pinecone describe, provider probes, CloudTrail (master §2) | owner O1 | A | S | TODO. **Next up.** Needs AWS read access (O1). |
| 2 | PR-01 | Providers: NVIDIA reranker successor; **Gemini upgraded as backup (D4)**; embeddings pinned, no failover; per-method breakers; startup probe; weekly canary (master QA-006) | PR-00 | A | S/M | TODO |
| 2 | PR-02 | Structured output: `nvext.guided_json`, thinking off, validate + one repair, token budgets; works on NVIDIA **and** Gemini (master QA-005) | PR-00 | A | M | TODO |
| 2 | PR-04 | Chat prompt privacy: `DOC-n` aliases, deterministic registry, no filenames in Pinecone (master QA-004, QA-011) | — | B | M | TODO (parallel-safe) |
| 2 | PR-05 | Masking: public vocabulary (incl. Basel/IFRS terms) and phone masking (master QA-009, QA-010) | — | C | S/M | TODO (parallel-safe) |
| 3 | PR-03 | UI: surface gap-analysis failures, truncation indicator (master QA-023) | PR-02 | A | S | TODO |
| 3 | PR-06 | Rate limiting: config validation, fallback bucket, `/auth` IP limiter, **self-registration abuse and cost controls (D5, D8)** (master QA-007) | PR-00 | D | S/M | TODO |
| 3 | PR-07 | Edge: **CloudFront + VPC origin + internal ALB (D6)**, `vercel.json` → https, SSE heartbeat, API docs off (master NEW-01, QA-020) | PR-00, owner O5 | E | S + infra | TODO |
| 3 | NEW-02 interim | Label old `CBUAE-MMG-2022` citations "illustrative sample, not official text" (master NEW-02) | — | C | S | TODO (parallel-safe) |
| 4 | PR-18 | Infra hygiene: separate staging task definition, Pinecone tenant namespaces (master NEW-06, NEW-07). **The staging split is a gate for C5.** | PR-00 | E | S/M | TODO |
| 4 | C1 | Corpus: migration, ORM, manifest schema **with licence and ingest-mode gates**, catalog upsert, seed/index shims that exit 1 (CorpusPlan §20) | — | F | M | TODO (parallel-safe) |
| 5 | C2 | Corpus: `rulebook_html` parser, `RegulatoryChunker`, lint (CBUAE sources) | C1 | F | L | TODO |
| 5 | **C2b** | Corpus: `bis_html` parser (Basel `brief_excerpt` mode) and IFRS 9 reference cards (`reference_only` mode) with the reviewed-card gate (CorpusPlan §6.1, §6.3) | C1 | G | M/L | TODO (parallel with C2) |
| 6 | C3 | Corpus: ingest orchestrator, CLI, S3, ledger, Pinecone upsert/GC, `CorpusRegistry`, BM25, stats, health | C2, C2b, PR-01 | F | L | TODO |
| 7 | C4 | Corpus: dual-scope retrieval, prompts, citation fields, remove the hardcoded corpus, 503 | C3, PR-04 | F | M | TODO |
| 8 | C5 | Corpus: workflows, IAM and S3 (O5), first staging ingest, then production | C4, PR-05, PR-18 (staging split) | F | S/M | TODO |
| 9 | C6 | Golden set v2 (incl. Basel and IFRS 9 cases) and eval baseline (CorpusPlan AC5) | C5, PR-01 | F | M | TODO |
| 10 | C7 | Thresholds wiring: tenant-policy relabel (D3), `regulatory_refs`, catalog-driven gap analysis (master QA-008) | C6, PR-02 | F | M | TODO |
| P1 | PR-08 | Input validation: settings bounds, question length (master QA-012, QA-018) | — | H | S | TODO (parallel-safe) |
| P1 | PR-09 | Safe markdown rendering and citation chips (master QA-014) | — | H | S/M | TODO (parallel-safe) |
| P1 | PR-10 | Streaming Regulatory Q&A (master QA-015) | PR-01, PR-02, C4 | F | M | TODO |
| P1 | PR-11 | Mobile header and menu (master QA-013) | — | H | S/M | TODO (parallel-safe) |
| P1 | PR-12 | Regulatory Library UX (master QA-016) | C1, C4 | F | M | TODO |
| P2 | PR-13 | Overlay accessibility (master QA-017) | — | H | S | TODO |
| P2 | PR-14 | Auth hardening: refresh rotation, logout revocation, **self-registration kept (D5)** (master QA-019) | PR-06 | D | M | TODO |
| P2 | PR-15 | Document lifecycle (master QA-021) | — | H | S/M | TODO |
| P2 | PR-16 | Docs: deployment drift, **no demo account (D7)**, runbooks (master QA-022, QA-024) | C5 | H | S | TODO |
| P2 | PR-17 | Self-hosted fonts, Docling warm-up (master QA-025, QA-026) | — | H | S | TODO |
| P1 | C-T2 | CBUAE Tier 2 sources (risk management regulation, capital adequacy); link CAR, Tier 1 and NPA thresholds (CorpusPlan §2) | C5 | F | M | TODO |

Lanes: A = providers, B = chat privacy, C = masking, D = auth and limits, E = infra, F = corpus main line, G = Basel and IFRS, H = frontend and validation.

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

---

## 6. Environment notes for agents

- **Reaching the app from a cloud sandbox**: the default network policy blocks `*.vercel.app`, but the backend ALB answers over HTTP. To drive the real frontend against the production backend:
  1. Copy `frontend/vite.config.ts` to an **untracked** `frontend/vite.qa.config.ts` with the proxy target set to the ALB URL (after PR-07: the CloudFront URL).
  2. Run `npx vite --config vite.qa.config.ts`, then use Playwright. Chromium is at `/opt/pw-browsers`.
  3. Delete the temporary config afterwards.

  To test the Vercel site itself, the owner must allow the host in the environment's network settings (O6).
- **QA accounts**: the audit registered `qa.agent.20260930@example.com` (tenant `QA Test Tenant`). Its password is not stored in the repo; ask the owner. Alternatively, register a fresh account named `qa.agent.<YYYYMMDD>@example.com` with tenant `QA Test Tenant <YYYYMMDD>`, which also exercises self-registration (D5). Record the email, never the password, in §5.
- **Audit leftovers in prod** (no delete API exists): the QA tenant and user, 2 models (including version `2.0-qa`), chat sessions, RAG traces and notifications.
- **AWS**: region `us-east-1`, cluster `modelaudit-cluster`, services `modelaudit-prod-service` and `modelaudit-staging-service`, task-definition family `modelaudit-backend-task` (shared by staging and prod; D9). Deploys: `.github/workflows/deploy-{staging,production}.yml`. Confirm the names in PR-00.
- **Unverified items to settle in PR-00**: the rate-limiter prod config (QA-007); the live Pinecone index dimension versus `nemotron-3-embed-1b` (2048 native); whether staging and prod share the DB and Pinecone (NEW-06); the Pinecone plan tier (NEW-07); and the structured-output parameter shape honoured by the hosted NIM (QA-005).

---

## 7. Owner action items

| # | Action | Blocks | Status |
|---|---|---|---|
| O1 | Re-authorise the AWS connector in claude.ai connector settings (or run the PR-00 commands yourself and paste the output into the PR) | PR-00, and through it PR-01, PR-02, PR-06, PR-07 | OPEN |
| O2 | Put a **billing-enabled** Gemini API key in Secrets Manager. On unpaid tiers, Google may use prompts to improve its products, which is not acceptable here even for masked text. | PR-01 (Gemini backup go-live) | OPEN |
| O3 | Email the IFRS Foundation (`permissions@ifrs.org`) for a licence to use IFRS 9 text in the app. Until one is granted, IFRS 9 stays `reference_only`. | Full-text IFRS 9 (C2b runs without it) | OPEN |
| O4 | Optional: ask BIS for written permission to use the full Basel Framework text. Without it, the app uses brief excerpts with the source stated, which BIS's standard notice allows. | Full-text Basel (C2b runs without it) | OPEN |
| O5 | Approve, or run, the infra changes: the CloudFront distribution with VPC origin, the internal ALB and the security groups (PR-07); the S3 bucket and task-role policy (C5); and the staging task definition (PR-18) | PR-07, C5, PR-18 | OPEN |
| O6 | Optional: allow `creditaudit-8rht0lyiq-shaktishubhankar.vercel.app` in the cloud environment's network settings so agents can test the Vercel site directly | Nothing (there is a workaround, §6) | OPEN |
| O7 | Optional: a human with IFRS 9 expertise reviews the reference cards drafted in C2b. Unreviewed cards are refused in production. | IFRS 9 go-live in production | OPEN |

---

## 8. Change log

- 2026-09-30: Live QA audit (`live-app-audit-2026-09-30.md`); remediation and corpus plans; owner decisions D1-D6 recorded; planner defaults D7-D9; `.agents/AGENTS.md` amended per D2; `HANDOFF.md` points here; the plans were updated for D1 (C2b, licence gates), D4 (Gemini backup), D5 (self-registration controls) and D6 (CloudFront).
