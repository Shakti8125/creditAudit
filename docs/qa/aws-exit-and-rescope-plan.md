# AWS exit and re-scope plan (D12)

Date: 2026-10-02. Status: **accepted on 2026-10-04.** D12 is the owner's own decision (their message of 2026-10-02). The owner then delegated the open questions ("choose what is best for the interviews"), so §9 is answered (see its end). **X-01, X-02 and X-03 are done in PR #5 (merge pending).**
Inputs: the owner's message ("have a local backend, only to show the interviewers the demo"), [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md), and the facts measured on 2026-10-02 (§1).
Reads with: [README.md](README.md) (owner decisions and tracker), [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md) ("master plan") and [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md) ("CorpusPlan"). Where those mention ECS, ALB, CloudFront, S3, SSM, CloudWatch, IAM, OIDC or a staging environment, **this plan overrides them.**
Implemented so far: X-01, X-02 and X-03 (workflows archived, AWS helper removed, docs and AGENTS.md updated). Nothing else is implemented, and nothing changes application code yet.

---

## 0. In short

- **D12.** The AWS account is deactivated. The backend runs **locally, only to demo to interviewers**, and nothing paid runs anywhere. This extends D11 (free of cost) from "build" to "host".
- **Is Vercel useless now? For interactive use, yes; as a front door, no.** A browser on an interviewer's machine reaches Vercel, and Vercel's rewrite runs on Vercel's servers, so it cannot reach `localhost` on the owner's laptop. A live demo therefore runs the frontend locally too. But the Vercel site is free, public and the link on the resume, so it should become a **static front door** (what it is, a demo video, the repo, how to run it) instead of a broken login form. See V-01.
- **Today the resume link is broken.** `creditaudit.vercel.app` loads a login page, and `/api/health` returns `502 DNS_HOSTNAME_EMPTY`. After W0, V-01 is the first change to make.
- **The AWS deploy workflows are archived in PR #5 (X-01)**, so merging it triggers nothing and `main` stays green (§3). Vercel's own Git integration already deploys the site, so no replacement workflow is needed. The one-minute UI disable (W0) is now only an optional stop-gap.
- **Re-scope result (§4).** Providers, structured output, chat privacy, masking and the whole regulatory corpus **stay**. Superseded: the CloudFront edge (PR-07), the staging split (PR-18), the S3/ECS/IAM parts of the corpus rollout. Deferred until the backend is exposed to anyone else: abuse controls, auth hardening. New: a local demo kit, a front door, a portfolio README.
- **Order (§6).** M1 "interview-safe demo", then M2 "real regulatory corpus", then M3 "proof and polish". The video is recorded last, after the fixes.

---

## 1. Facts measured on 2026-10-02

| # | Fact | How |
|---|---|---|
| F1 | The backend is gone. `creditaudit.vercel.app/api/health` returns **502 `DNS_HOSTNAME_EMPTY`**, and the old ALB hostname does not resolve. | live fetch, `curl` |
| F2 | The Vercel project `credit_audit` is on a **personal account** (no team). Its production aliases are `creditaudit.vercel.app` and `creditaudit-shaktishubhankar.vercel.app`. The alias is **public**: a no-login fetch returned the app. Vercel Authentication is enabled (scope `all_except_custom_domains`), so per-deployment and preview URLs probably ask for a Vercel login (not tested). Share only the alias. | Vercel API, live fetch |
| F3 | Vercel's **Git integration is connected**: it builds a preview for every branch push (including the `ccr-*` branches that no workflow deploys) and a production deployment for `main`. The Actions job that also deploys to Vercel therefore appears to duplicate it. | Vercel deployments list |
| F4 | GitHub has two AWS deploy workflows. `deploy-production.yml` ran **21 times**. `deploy-staging.yml` ran **0 times**; its `develop` branch does not exist. | GitHub Actions API |
| F5 | The next push to `main` runs *Deploy Production*. Its `backend` job can no longer reach AWS, so `main` shows a red mark and sends a failure email on a public repo. PR #5 is open and mergeable, so merging it triggers this. | workflow files **Resolved on 2026-10-04 by X-01: PR #5 archives the workflows, so its merge triggers neither.** |
| F6 | The AWS connector still asks for sign-in, so no billing data was read. This session's GitHub proxy blocks the secrets and environments APIs (403), so the secret names in §3 come from the workflow files and the owner must confirm them. | connector, `gh api` |
| F7 | The account's plan type (Free plan with credits, or legacy/Paid) is **unknown**. | cost report §1 |
| F8 | The repo's local run path has defects: `docker-compose.yml` reads `.env` at the repo root while the full example is `backend/.env.example` (the two example files have drifted); it starts a local Redis that the Upstash REST client cannot use; it has no frontend service; the Dockerfile sets a `python3.13` path on a Python 3.12 image. | repo files |

---

## 2. The AWS account: what the owner should do

It is not yet known whether the account was suspended for an unpaid bill (the first assumption in this session) or closed because its Free-plan credits ran out. On the **Free plan nothing is owed**; on a legacy or Paid account a balance is.

| If the account was on... | What AWS says | What to do |
|---|---|---|
| **Free plan** | Closes when credits run out or after six months. AWS keeps the content for **90 days**; upgrading to a Paid plan inside that window reopens it and restores the resources. | **Do not upgrade.** Reopening restores access to whatever AWS still holds, and billing resumes (the documented stack cost about $205 a month, cost report §5). Nothing in AWS is needed: the RDS database held only QA leftovers, the corpus was never loaded, the code is in Git, and the secrets are re-created locally. |
| **Legacy free tier or Paid plan** | Suspended for an unpaid balance. Resources can be deleted at any time while suspended, and the account closes about 30 days after suspension unless reactivated (AWS's own pages differ on the later windows; read the notice email for the exact dates). | Open a billing case (account-reinstatement category). Ask what is owed, whether charges have stopped accruing, and for a one-time adjustment for unexpected charges. Do not reactivate just to host. |

In both cases (**owner action O10**):
1. Note the plan type, the credits used, and AWS's emails, then export the Cost Explorer CSVs (cost report §7) **before the billing pages stop working**, if actual numbers are wanted.
2. Remove the AWS secrets from GitHub (§3, W2).
3. If console access ever returns, delete the IAM access key that GitHub used.
4. Re-issue what lived in AWS. GitHub secrets cannot be read back and SSM is gone, so create a fresh local `backend/.env`: provider keys from the NVIDIA, Gemini, Pinecone and Upstash dashboards (create new ones if needed; they are free), and a **new** RS256 key pair (or leave it empty for ephemeral dev keys). No rotation is needed for leakage: the old copies sat in an account only the owner could reach.

---

## 3. Disabling the AWS deploy workflows

### 3.1 Inventory

| File | Trigger | Jobs | AWS secrets it reads | Notes |
|---|---|---|---|---|
| `deploy-production.yml` | push to `main`, manual | `backend` (ECR build and push, Alembic one-off task, ECS update); `frontend` (Vercel CLI, production) | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROD_PRIVATE_SUBNET`, `AWS_PROD_ECS_SG`; environment `production` | 21 runs. The two jobs are independent. |
| `deploy-staging.yml` | push to `develop` | `backend`, `frontend` (Vercel preview) | `AWS_STAGING_PRIVATE_SUBNET`, `AWS_STAGING_ECS_SG`; environment `staging` | 0 runs. |
| `ci.yml` | pull requests, push to `main` or `develop` | backend (compile, ruff, pytest on SQLite), frontend (tsc, build) | none | **Keep.** |
| `nightly-eval.yml` | daily 02:00 UTC, manual | privacy and security stress tests on SQLite | none | **Keep.** Green every night. |

Vercel secrets used by the two `frontend` jobs: `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`.

### 3.2 End state: choose one (recommended: A)

| Option | What | For | Against |
|---|---|---|---|
| **A (recommended)** | Archive both AWS workflows. No replacement. Vercel's Git integration deploys the site. | Fewest moving parts. No Vercel token in GitHub. No red runs. | Relies on the integration staying connected (verified by W1.1 and W4). |
| B | Archive both, and add a frontend-only `deploy-frontend.yml` (§3.5). | Deploys stay visible in Actions. | Two production deployments per push (integration and Actions). Needs the three Vercel secrets. |
| C | Only disable in the GitHub UI. | One minute. | Dead files stay and go red if re-enabled. Use only as the stop-gap W0. |

### 3.3 Steps

| Step | Who | What | Verify | Rollback |
|---|---|---|---|---|
| **W0** stop-gap, 1 minute | owner | GitHub, Actions, *Deploy Production*, menu, **Disable workflow**; the same for *Deploy Staging*. Equivalent API call: `gh api -X PUT repos/Shakti8125/creditAudit/actions/workflows/347782831/disable` (production) and `.../347782833/disable` (staging). **Optional since 2026-10-04**: PR #5 archives the workflows, so the merge triggers neither. Still the quickest way to stop them if anything else is pushed to `main` first. | Both workflows show "disabled". | Enable workflow. |
| **W1** code, one PR, size S | agent | **Done 2026-10-04 in PR #5 (merge pending).** (1) Confirm in Vercel, Project, Settings, Git: repository connected and Production Branch is `main` (already evidenced by F3). (2) `git mv` both workflows to `docs/archive/aws/workflows/` as `deploy-production.aws.yml` and `deploy-staging.aws.yml`; GitHub only runs files in `.github/workflows/`. (3) Add `docs/archive/aws/README.md`: what they were, when retired, how to re-enable (recreate the stack per the archived `deployment_steps.md`, restore the secrets, `git mv` back). (4) Leave `ci.yml` and `nightly-eval.yml` untouched. | `git grep -nE "aws-actions\|AWS_" .github` finds nothing; `actionlint` passes on the remaining files (checked: it passes today on `ci.yml`, `nightly-eval.yml` and on the Option B file). | `git revert`. |
| **W2** secrets, 5 minutes | owner | GitHub, Settings, Secrets and variables, Actions. Delete `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_PROD_PRIVATE_SUBNET`, `AWS_PROD_ECS_SG`, `AWS_STAGING_PRIVATE_SUBNET`, `AWS_STAGING_ECS_SG` (repository or environment level). Option A: also delete `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` and revoke the token in Vercel, Account, Tokens. Delete the `staging` and `production` environments if unused. Keep provider keys only if the PR-01 canary will use them. **Confirm the real list**: this session cannot read it. | The secrets page shows no `AWS_*`. | Re-create the secret. |
| **W3** AWS side | owner | Per §2. If the console is reachable, delete the IAM user or access key that GitHub used. | | |
| **W4** verify | agent and owner | After the W1 PR merges: only CI (and nightly) run; no red mark on `main`; Vercel shows a **production** deployment for the merge commit created by the integration (`target=production`, ref `main`); `gh api repos/Shakti8125/creditAudit/actions/workflows` no longer lists the deploy workflows as active. | | If no production deployment appears: switch to Option B. |
| **W5** docs, X-03 | agent | §5, X-03. | | |

Merge order: W1 is bundled into PR #5, so its merge commit no longer contains the workflows and triggers nothing. W0 is optional. After the merge, the owner does W2 and the agent checks W4.

### 3.4 Failure modes handled

- **A push lands before W0 or W1**: *Deploy Production* fails in `backend` and sends one email. The `frontend` job is independent, so the site is unaffected. No data is at risk.
- **Vercel integration turns out to be disconnected**: W4 detects it (no production deployment). Fall back to Option B.
- **A later session re-adds an AWS step by habit**: README §6 and AGENTS.md (X-03) say AWS is retired.

### 3.5 Option B file (validated, only used if Option A fails)

`actionlint` (1.7.12) passes on this file.

```yaml
name: Deploy Frontend (Vercel)

on:
  push:
    branches: [main]
    paths:
      - "frontend/**"
      - ".github/workflows/deploy-frontend.yml"
  workflow_dispatch:

concurrency:
  group: deploy-frontend
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  frontend:
    name: Deploy frontend to Vercel (production)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      # Run from the repo root: the Vercel project already sets rootDirectory=frontend.
      - name: Install and deploy to Vercel
        env:
          VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}
          VERCEL_ORG_ID: ${{ secrets.VERCEL_ORG_ID }}
          VERCEL_PROJECT_ID: ${{ secrets.VERCEL_PROJECT_ID }}
        run: |
          npm i -g vercel
          vercel pull --yes --environment=production --token "$VERCEL_TOKEN"
          vercel build --prod --token "$VERCEL_TOKEN"
          vercel deploy --prebuilt --prod --token "$VERCEL_TOKEN"
```

### 3.6 Checklist

- [ ] W0: both deploy workflows disabled in the UI
- [ ] Vercel Git integration confirmed (Settings, Git)
- [ ] W1 PR merged; `main` has no AWS workflow
- [ ] W2: AWS (and, for Option A, Vercel) secrets deleted; environments removed
- [ ] W3: IAM key deleted if reachable
- [ ] W4: next push shows only CI, and a Vercel production deployment from the integration

---

## 4. Re-scope of the remediation plans

### 4.1 Rules used

| Label | Meaning |
|---|---|
| **KEEP** | Does not depend on where the backend runs. |
| **CHANGE** | Still needed, but a part that assumed AWS is replaced. |
| **SUPERSEDED** | Only existed because of AWS. Removed. |
| **DEFER** | Only matters when the backend is reachable by someone other than the owner. It has a trigger (§7). |
| **NEW** | Created by D12. |

Two properties decide the rest. **The privacy rules and the free-of-cost rule (D11) do not change.** And the demo is only as good as the **corpus, the providers and the first-upload experience**, so those move to the front.

### 4.2 Tracker rows (README §3)

| ID | Was | Now | What changes |
|---|---|---|---|
| PR-00 | ECS env names, CloudWatch queries, Pinecone describe, provider probes, CloudTrail | **CHANGE → PR-00L** | Run only the keyed probes, **locally**: `cd backend && python -m scripts.diag.pr00_probe --only nvidia,gemini,pinecone` with a local `.env`. The probe already reads `app.config.settings`. Steps 1, 2, 5 (ECS, CloudWatch, CloudTrail), the O1 and O8 blockers, NEW-06 and the QA-007 production-config question are **void**. X-02 trims PR #5 accordingly. |
| PR-01 | Providers: reranker, Gemini backup, pinned embeddings, canary | **KEEP** | **The weekly canary is dropped:** a scheduled job that calls the providers needs `NVIDIA_API_KEY` and `GEMINI_API_KEY` as GitHub secrets (PR-01 adds no secret-dependent CI job), and the keyless alternative is not a signal (NVIDIA keeps retired models listed). The local equivalents are `scripts/demo.sh preflight` and `python -m scripts.diag.pr00_probe`. The "backup drill on staging" becomes a local drill with an invalid `NVIDIA_API_KEY` in `.env`. |
| PR-02 | Structured output | **KEEP** | |
| PR-01b | Model lifecycle resilience (D10) | **CHANGE** | The SSM override becomes a local file, `LLM_MODELS_OVERRIDE_FILE` (same schema, polled every 5 minutes). The CloudWatch alarm becomes a GitHub issue. The "fit under CloudFront's 60 s" deadline rationale goes; the budgets stay for UX. The staging drill becomes a local one. Sequenced after M1. |
| PR-03 | Surface gap-analysis failures | **KEEP** | |
| PR-04 | Chat prompt privacy | **KEEP** | QA-011 (empty Privacy Inspector log) came from several workers and tasks. A single local worker hides it, but the deterministic registry stays: the privacy rules require it. |
| PR-05 | Masking vocabulary and phones | **KEEP** | A prerequisite for the corpus. |
| NEW-02 interim | Label old citations "illustrative sample" | **KEEP** | Demo-critical until the corpus lands. |
| PR-06 | Rate limiting plus self-registration abuse controls (D5, D8) | **CHANGE → PR-06-lite, rest DEFER** | Keep: startup validation of the limiter config, its state in `/health`, `EVAL` when the script SHA is missing, and an in-process fallback bucket instead of fail-open. Defer: the `/auth` IP limiter, register caps, the daily AI quota, Turnstile, the CloudWatch alarms and the D8 tiers. |
| PR-07 | CloudFront, VPC origin, internal ALB, `vercel.json` to https, SSE heartbeat, docs off | **SUPERSEDED** | No AWS edge. NEW-01 (plain-HTTP hop) is **closed**: the hop is gone. QA-020 (public `/docs`) is **accepted** while local-only; it is useful in a demo. The dead rewrite is fixed by V-01. The SSE heartbeat is deferred (trigger: any proxy or tunnel with an idle timeout). |
| PR-18 | Staging task definition; Pinecone tenant namespaces | **SUPERSEDED / DEFER** | The staging split, D9 and NEW-06 are void: there is one local environment. NEW-07 (Pinecone Starter's 100-namespace cap) becomes an optional guard: return a clear error and add a startup warning when the namespace count is above 60. |
| C1 | Corpus schema, manifest, licence gates, shims | **KEEP** | |
| C2 | CBUAE parser, chunker, lint | **KEEP** | |
| C2b | Basel III and IFRS 9 parsers (full text, licence profile) | **KEEP** | |
| C3 | Ingest orchestrator, CLI, **S3**, ledger, registry, BM25 | **CHANGE** | Sources and run artifacts go to a **local directory**, not S3 (§4.4). No `boto3`. |
| C4 | Dual-scope retrieval, prompts, remove the hardcoded corpus | **KEEP** | |
| C5 | Workflows, IAM and S3 (O5), first staging ingest, then production | **CHANGE → C5L** | Run the ingest **locally**: `acquire`, `verify`, `ingest`. Record the counts in README §5. No workflow, IAM, S3 or staging. O5 is void; O3 (the IFRS 9 PDF) stays. |
| C6 | Golden set v2 and eval baseline | **KEEP** | The baseline runs locally on the free tiers. This produces the numbers worth quoting. |
| C7 | Thresholds wiring | **KEEP** | |
| C-T2 | CBUAE Tier 2 sources | **KEEP** | |
| PR-08 | Input validation | **KEEP** | |
| PR-09 | Safe markdown and citation chips | **KEEP** | |
| PR-10 | Streaming Regulatory Q&A | **KEEP** | |
| PR-11 | Mobile header | **KEEP** | |
| PR-12 | Library UX | **KEEP** | |
| PR-13 | Overlay accessibility | **KEEP** | |
| PR-14 | Auth hardening | **DEFER** | Keep only the cheap tenant-isolation regression test. |
| PR-15 | Document lifecycle | **KEEP** | |
| PR-16 | Docs drift, no demo account, runbooks | **CHANGE** | Absorbed by X-03, L-01 and L-02. What remains: remove the real bank names and credentials (QA-024) when `deployment_steps.md` is archived; the CorpusPlan runbook becomes local. |
| PR-17 | Self-hosted fonts; Docling warm-up | **CHANGE** | The **Docling pre-download and warm-up moves into L-01** (QA-026: the first upload took about 38 s, which is what an interviewer would see). Fonts stay P2. |
| X-01..X-03, L-01..L-03, V-01 | n/a | **NEW** | §5. |

### 4.3 Findings whose root cause or verification was AWS-specific

| Finding | Disposition |
|---|---|
| NEW-01 plain-HTTP hop | **Closed.** |
| NEW-06 shared task definition | **N/A.** |
| NEW-07 Pinecone namespace cap | **Deferred guard** (PR-18 row). |
| NEW-08 no rate limit on `/auth` | **Deferred** (§7). |
| QA-007 limiter not enforced in production | The production-config question is **void**. The code fixes continue as PR-06-lite. |
| QA-019 auth hardening | **Deferred.** |
| QA-020 public API docs | **Accepted** while local-only. |
| QA-022 documentation drift, QA-024 demo account | **PR-16 row.** |
| QA-026 first-upload latency | **L-01.** The "check CloudWatch" step becomes "time the first upload locally". |

### 4.4 CorpusPlan overrides

| CorpusPlan section | Override |
|---|---|
| §0 points 1 and 8, §4.1, §5 (step 16, `acquire`, `verify`), §21 | Sources and run artifacts live in a **local directory**, `CORPUS_LOCAL_DIR` (default `data/corpus/`, gitignored), in the same layout (`sources/{doc_key}/{version}/...`, `runs/{run_id}/...`). The manifest, sha256 checks and exit codes are unchanged (exit 2 now means a missing local file or a checksum mismatch). **Do not put it under `backend/regulatory_corpus/`**: the plan's own test fails if a `.pdf`, `.htm` or `.html` file appears there. `CORPUS_LOCAL_DIR` already exists in §13's config list. |
| §3 diagram, §13 (ECS one-off, deploy integration, manual workflow, environment check) | Delete the ECS one-off, the "Sync regulatory corpus" deploy step, `regulatory-corpus.yml` and the NEW-06 check. The commands run locally: `python -m scripts.regulatory <acquire\|verify\|ingest\|rollback\|gc>` or `docker compose run --rm backend python -m scripts.regulatory ...`. `boto3` is **not** added to `requirements.txt`. The PR CI fixture tests (§13) stay. |
| §14 | No CloudWatch metric filter. Logs stay JSON lines. `/regulatory/corpus/stats` and the `/health` field stay. |
| §15.1, §15.3, §18, §19 | "Staging first, then production" becomes **one local environment**: AC1-AC12 run once against the local stack. Runbook and rollback commands use the local CLI; the `gh workflow run regulatory-corpus.yml` rows are dropped. |
| §16, §20 | Drop `regulatory-corpus.yml`, the `deploy-*.yml` edits and `boto3`. C3 loses its S3 reader (`storage.py` keeps the local reader; an S3 one could be added later). C5 becomes C5L. |
| §22, README O5 | O5 void. O3 stays. |

Durability trade-off: S3 versioning protected the sources. Locally they are **public and re-acquirable** from the official URLs, and the manifest records each sha256, so `acquire` is verifiable. The IFRS 9 PDF (a manual download, O3) must be kept by the owner outside git. The Postgres ledger is re-creatable from the sources and the manifest (`scripts/demo.sh reset` in L-01).

### 4.5 Owner decisions affected

| Decision | Effect |
|---|---|
| **D12** (new) | AWS retired; backend local-only for demos; no paid cloud. |
| D6 (CloudFront) | **Superseded.** |
| D9 (environment isolation, PR-18 gate on C5) | **Superseded**: one local environment. |
| D5 (open self-registration with abuse controls) | Registration still creates a new tenant per sign-up. The **controls are deferred** until the backend is exposed. |
| D8 (rate-limit tiers) | Deferred with PR-06. |
| D1 (full-text Basel and IFRS 9) | Unchanged. Its heads-up about passages being readable by anyone who registers is moot while only the owner can reach the backend. |
| D7 (no shared demo account) | Unchanged for docs. Question Q4 proposes a local seed account whose random password is printed at seed time and never committed. |
| D11 (free of cost) | **Reinforced** and extended to hosting. |
| D1-D4, D10 | Otherwise unchanged. |

### 4.6 AGENTS.md amendments (proposed text; not applied until Q3 is answered)

- Tech stack, database: "PostgreSQL 16 (Docker locally; no managed cloud database)".
- Tech stack, deployment: "Docker Compose (local; the supported way to run the backend for demos), Vercel (static front door only). AWS ECS Fargate was used in September 2026 and retired (history in `docs/archive/aws/`)."
- Tech stack, CI/CD: "GitHub Actions (CI, nightly privacy stress, provider canary). Vercel's Git integration deploys the frontend."
- Rule 9: replace "optional runtime override: SSM `/modelaudit/<env>/llm/models`" with "optional runtime override: the YAML file named by `LLM_MODELS_OVERRIDE_FILE`, same schema, polled".
- Regulatory Corpus Rules, first bullet: "sources live in a private local directory outside git (`CORPUS_LOCAL_DIR`), are re-acquirable from the official URLs and listed with their sha256 in the git manifest".

---

## 5. New work items

| ID | Title | Size | Depends on |
|---|---|---|---|
| X-01 | Archive the AWS deploy workflows (§3, W1) | S | Q2 |
| X-02 | Trim PR #5 | S | none |
| X-03 | Docs and AGENTS.md for the local-only world | S | Q3 |
| V-01 | Vercel front door | S | X-01 |
| L-01 | Local demo kit | M | PR-00L |
| L-02 | Portfolio README, screenshots, video, repo tidy | S/M | M1 done (the video last) |
| L-03 | Optional: CI smoke test of the demo kit | S | L-01 |

Status on 2026-10-04: **X-01, X-02 and X-03 are merged (PR #5; W4 confirmed).** **V-01 is done, and the code of L-01 is done,** on branch `ccr-69721f6f-73mabp` (PR pending). L-01's acceptance needs one run on the owner's machine (README O12).

### X-02: trim PR #5

PR #5 holds the PR-00 tooling. New commits for this plan land on the same branch, so its scope grows to "PR-00L and the AWS exit plan".
- **Keep** `backend/scripts/diag/pr00_probe.py` and `backend/tests/test_pr00_probe.py`. Reword the docstring: it now runs locally, not "as a one-off ECS task".
- **Drop** `backend/scripts/diag/pr00_aws.py` and `backend/tests/test_pr00_aws.py` (AWS-only).
- **Rewrite** `docs/qa/pr-00-runbook.md` for local use: copy `backend/.env.example` to `backend/.env`; run the probe from `backend/`; paste the printed lines (names, codes and booleans only) into README §5; keep the "what each result decides" table.
- Keep the README §5 rows already recorded; they are history. Update the PR #5 title and description.
- **Acceptance:** `pytest` and `ruff` stay green, and `git grep -n boto3` finds nothing.

### V-01: Vercel front door

- `frontend/vercel.json`: remove the `/api/:path*` rewrite (its target no longer exists). Keep the headers and the SPA fallback. Without the rewrite, `/api/health` is answered by the SPA fallback with HTML and status 200, so **the gate must check the JSON body, not just the status**.
- New `BackendGate` (wrapped in `main.tsx` above `AuthProvider`): `GET /api/health` with a 4 s timeout. "Online" means status 200 **and** a JSON body with `status: "ok"`. Otherwise render `DemoOfflineView` instead of the login and register views. Retry on a button and every 30 s.
- `DemoOfflineView`: what the project is in two sentences; a plain statement that **the backend is offline by design and runs locally for demos**; the demo video, the GitHub repo and the "run it locally in 5 minutes" page; three screenshots (from L-02); a contact line. Build-time `VITE_DEMO_VIDEO_URL`, `VITE_REPO_URL`, `VITE_CONTACT_URL` set in the Vercel project (no secrets). No mock data and no pretence that the app is live.
- The frontend has no test runner, so acceptance is `npm run lint && npm run build` plus two manual checks: with the backend down, `npm run dev` shows the offline view; with the local backend up, the login page appears exactly as today. Adding Vitest is out of scope.
- Share only `https://creditaudit.vercel.app` (F2).

**Outcome (2026-10-04).** Built as specified, with these details:
- `vercel.json` no longer rewrites `/api`. `BackendGate` (above `AuthProvider`) calls `GET /api/health` with a 4 s timeout and accepts only status 200 with a JSON body `status: "ok"`. It shows a spinner while it checks, `DemoOfflineView` when the check fails, and the app when it passes. While offline it retries every 30 s (not while the tab is hidden) and on **Check now**. Once the backend has answered it never polls again, so a later outage cannot unmount a session in progress.
- The links come from `VITE_DEMO_VIDEO_URL`, `VITE_REPO_URL` (default: this repository) and `VITE_CONTACT_URL`; only http(s) URLs (and `mailto:` for the contact) are used. The video and contact buttons appear only when set.
- **Not built:** the three screenshots wait for L-02, so the page has none yet.
- **Checked** (README §5): `npm run lint`, `npm run build`, and headless Chromium against a static server with a Vercel-style SPA fallback (HTML with status 200 on `/api/health`, the case a status-only check gets wrong) and against the dev proxy with a stub backend that comes up while the page is open.
- The page goes live when the branch is merged and Vercel deploys it. Until then the site still shows the old sign-in.

### L-01: local demo kit

Fixes F8 and makes the demo repeatable. From a fresh clone on a laptop with Docker and Node:
1. **One env file.** Merge the two examples into `backend/.env.example` (the root file lacks `JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`, `RATE_LIMIT_ENABLED` and `RAG_TELEMETRY_ENABLED`) and point `docker-compose.yml` at `./backend/.env`. Local defaults: `RATE_LIMIT_ENABLED=false` and empty JWT keys (ephemeral dev keys; tokens reset on restart). `ENVIRONMENT` and `REGULATORY_FALLBACK=off` do not exist in `app/config.py` yet; C3 and C4 add them (CorpusPlan §13), and once they exist the demo profile must set `REGULATORY_FALLBACK=off` so it never serves the fabricated corpus (NEW-02, D3). Until then the NEW-02 interim label covers the demo.
2. **Compose.** Remove the `redis` service (the app talks to Upstash over REST; a local Redis is unusable). Keep `db`. Run the frontend with `npm run dev` (its Vite proxy already targets `localhost:8001`); `scripts/demo.sh up` starts both. Fix the Dockerfile's `python3.13` `PYTHONPATH`.
3. **Cold start.** Pre-download Docling's models into the image and warm the extractor in `lifespan` (QA-026). **Target: the first upload takes under 10 s.**
4. **Seed.** `scripts/demo.sh seed` registers `demo.<date>@example.com` through the API with a random password it prints once, then creates one synthetic model with two versions and the two synthetic PD validation documents the audit used (their generation is described in audit §2; they are not in the repo yet, so this step adds the generator).
5. **Preflight.** `scripts/demo.sh preflight` runs the probe (`--only nvidia,gemini,pinecone`) and prints green or red per capability: generate, rerank, embed, Pinecone dimension match, Gemini backup. Run it 10 minutes before an interview. Model IDs change often (PR-01b), so this is the guard.
6. **Reset.** `scripts/demo.sh reset` drops the Postgres volume and the local corpus runs.
7. **Docs.** `docs/LOCAL_DEMO.md`: prerequisites, the 5-minute path, a 10-minute interview script (register, upload, gap analysis, AI Analyst, Regulatory Q&A, Privacy Inspector, RAG Performance), troubleshooting, and the D11 caution: **no real confidential documents while Gemini is on its free tier.**
- **Unverified, to measure (owner, README O12):** the RAM Docker needs (Docling plus spaCy `en_core_web_lg` is documented as 4 GB per task; check `docker stats` during the first upload) and the image size (consider the CPU-only PyTorch wheels).
- **Acceptance:** a fresh clone reaches a working seeded demo in under 15 minutes; `GET /health` shows `db: connected`; preflight is green; the first upload is under 10 s.

**Outcome (2026-10-04): code done, acceptance pending.** What was built, and where it differs from the list above:
1. **One env file.** `backend/.env.example` is the only example; the root one is removed, and `JWT_SECRET_KEY` is dropped because nothing reads it. Defaults: `RATE_LIMIT_ENABLED=false`, empty JWT keys (confirmed: the backend generates an ephemeral RS256 pair), `WARM_MODELS_ON_STARTUP=true`.
2. **Compose.** No Redis service. The backend runs `alembic upgrade head` before `uvicorn` (nothing created the schema before, so a fresh `docker compose up` gave an empty database); `db` has a health check; both ports bind to `127.0.0.1`; the source bind mount is gone so the image is self-contained. The frontend runs on the host through Vite, started by `scripts/demo.sh up`. The Dockerfile's `python3.13` path is fixed to 3.12 and `backend/.dockerignore` keeps `backend/.env` out of the image.
3. **Cold start.** The Dockerfile pre-downloads Docling's PDF models into `/opt/docling-models` and sets `DOCLING_ARTIFACTS_PATH`, which makes Docling run offline from there. `WARM_MODELS_ON_STARTUP` loads Docling and the spaCy/Presidio masker before serving, so `/health` answers only once they are loaded. A failed step is logged and skipped; the model then loads on first use as before. **The measured gap:** the first upload took 8.8 s with the masker loading lazily and the second 1.1 s; at start-up the masker loaded in 10.1 s.
4. **Seed.** `backend/scripts/demo/seed.py` registers `demo.<date>@example.com` (a numbered address if taken) with a random password printed once before any upload, creates the model with versions 1.0 and 2.0, and uploads the two synthetic reports. The reports are **DOCX, not PDF** (python-docx is already installed, and the DOCX path needs no model download, so a test can run them through the real extractor and policy checker: version 1.0 scores 6 of 6 PASS, version 2.0 6 of 6 BREACH). The sign-off block holds a fictional institution, two people and an e-mail address for the masking demo.
5. **Preflight.** `backend/scripts/demo/preflight.py` runs the PR-00 probe quietly and prints OK, WARN or FAIL per capability; it exits 1 only if a required check fails (primary LLM, embeddings, Pinecone index, embedding size equal to the index size).
6. **Reset, fixtures, status.** `scripts/demo.sh reset`, `fixtures` and `status`. A `DEMO_NATIVE=1` mode serves a backend run without Docker.
7. **Docs.** [docs/LOCAL_DEMO.md](../LOCAL_DEMO.md): prerequisites, the short path, a 10-minute script, a list of what does not work yet, a no-Docker path and troubleshooting.

**Checked in a sandbox without Docker** (README §5): migrations on an empty Postgres 16, the real backend starting without keys, the seed end to end with only the embedding and Pinecone calls stubbed, the demo commands, and a real browser sign-in showing the BREACH card. **Not checked:** `docker build` and `docker compose up`, the Docling PDF model download (blocked in the sandbox), real provider calls, the first PDF upload time and Docker's memory. Tests added: warm-up, fixtures, seed and preflight.


### L-02: portfolio README, screenshots, video, repo tidy

- The repo has **no root `README.md`**. Add: a one-paragraph pitch; screenshots; an architecture diagram (Mermaid); how privacy works (masking, egress validator); the stack; "run it locally in 5 minutes"; the engineering story (live QA audit, 26 findings, remediation plan, the cost lesson); and an honest status line: **not publicly hosted; a live walkthrough on request**.
- Record a 2-3 minute demo video **after M1 and M2**, so it shows the fixed behaviour. The owner records it; L-01's script is the outline.
- Tidy: remove the two tracked logs `frontend/dev.err` and `frontend/dev.out`; move the seven root planning documents into `docs/history/` with a short `docs/README.md` index. Leave `.agents/` alone (the harness reads `.agents/AGENTS.md`).
- Keep claims true: say "deployed on AWS ECS Fargate in September 2026, since retired" and never present the app as live while it is not.

### L-03 (optional): CI smoke test

A manual (`workflow_dispatch`) job that builds the backend image, starts `db` and `backend`, and checks `/health`. Do it only if the image fits the runner's disk and build time (unmeasured); otherwise skip.

---

## 6. Order of work

| Milestone | Items | Exit criteria | Rough size |
|---|---|---|---|
| **Now** | Merge PR #5 (workflows archived); W2 and the AWS follow-up (owner, O10) | Nothing red on `main`; AWS secrets removed. | 15 minutes |
| **M1 interview-safe demo** | ~~X-01, X-02, X-03~~ (done in PR #5), V-01, PR-00L, L-01, PR-01, PR-02, PR-04, NEW-02 interim, PR-03 | Fresh clone to seeded demo in under 15 minutes. A second chat turn works (QA-004). Gap analysis and compare return 200 five out of five (QA-005). The reranker works or degrades cleanly (QA-006). The front door shows the offline view. | about 8-11 dev-days |
| **M2 real regulatory corpus** | PR-05, C1, C2, C2b, C3, C4, C5L, PR-01b, PR-06-lite | CorpusPlan AC1-AC4 and AC6-AC12 pass once on the local stack. Basel III and IFRS 9 appear with attribution. | about 15-20 dev-days |
| **M3 proof and polish** | C6 (the baseline numbers), C7, C-T2, PR-08, PR-09, PR-10, PR-11, PR-12, PR-13, PR-15, PR-16 remainder, PR-17 fonts, L-02 | A recorded eval baseline. The README, screenshots and video are final. | about 14-18 dev-days |

**Progress (2026-10-04):** merged: X-01, X-02, X-03. On branch `ccr-69721f6f-73mabp`: V-01 and L-01 (code). Next in M1: PR-01, PR-02, PR-04, NEW-02 interim, PR-03; PR-00L (the numbers) needs the owner's keys.

Sizes follow the master plan's scale (S up to 0.5 day, M 1-3, L 3-6). They are estimates, not commitments. If an interview is near, **ship M1 and stop**; M2 and M3 follow.

---

## 7. Deferred, with triggers

| Item | Revisit when |
|---|---|
| PR-06 remainder: `/auth` IP limiter, register caps, daily AI quota, Turnstile, alarms; NEW-08; D8 tiers | The backend is reachable by anyone but the owner (a tunnel or a host). |
| PR-14 / QA-019 auth hardening | Same. |
| QA-020 `/docs` off | Same. |
| SSE heartbeat | Any reverse proxy or tunnel with an idle timeout. |
| NEW-07 namespace guard | Pinecone namespace count above 60 (use `describe_index_stats`). |
| An S3 reader for `storage.py` | Never planned. |
| CorpusPlan C2c | The app goes commercial. |
| **Public backend hosting** | The owner finds a host that fits about 4 GB of RAM at $0, or a sponsor. **Checked 2026-10-02:** Hugging Face Spaces now requires a paid plan for Docker Spaces; Render's free tier spins down after 15 minutes (about a minute to restart) and its free Postgres expires after 30 days; Oracle's Always Free Ampere allowance was cut to 2 OCPU and 12 GB in June 2026 and idle instances are reclaimed; Cloud Run has a free tier but needs a billing account with a card. None is a clean fit. |
| A tunnel for a live interviewer session | Optional later: a Cloudflare quick tunnel plus a runtime API-base setting in the frontend, with the Vercel origin added to `ALLOWED_ORIGINS`. It exposes the owner's free-tier API quota, so keep it short-lived. |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| The demo depends on a laptop and on free-tier APIs (Gemini about 10-15 requests per minute, the NVIDIA developer API's rate limits). | Preflight before each interview; the recorded video is the fallback; keep eval runs modest. |
| Model churn breaks a model ID between rehearsal and interview. | Preflight, then PR-01b. |
| Docker needs more RAM than the laptop has. | Measure first (L-01). Fall back to a Python virtualenv for the backend. |
| Local data or the IFRS 9 PDF is lost. | The corpus is re-acquirable and the ledger is rebuildable; keep the PDF outside git. |
| Visitors read the offline front door as "dead". | V-01 states plainly that this is by design and links the video and the repo. |
| Free-tier Gemini may use prompts for training (D11). | Synthetic or public documents only. |
| PR #5 mixes PR-00 tooling and this plan. | X-02 retitles it and rewrites its description. |

---

## 9. Questions for the owner (one line each is enough)

1. **Q1.** Is the D12 wording right? "AWS retired; the backend runs locally only for demos; no paid cloud anywhere (extends D11)."
2. **Q2.** Vercel: keep it as a static front door (recommended) **and** archive the Actions Vercel job because the Git integration already deploys (Option A)?
3. **Q3.** May AGENTS.md be amended as in §4.6?
4. **Q4.** May the local seed create `demo.<date>@example.com` with a random password printed once (D7 stays intact for docs)?
5. **Q5.** Is there an interview date? If it is within about two weeks, ship M1 only.
6. **Q6.** What plan was the AWS account on (Free plan or legacy/Paid), and is any balance shown (O10)?

### Answers (2026-10-04)

The owner replied: "Choose what is best for the interviews, there is not interview scheduled yet." That delegates Q1-Q5, decided as recommended:

| Q | Decision |
|---|---|
| Q1 | D12 stands as written. |
| Q2 | **Option A.** Vercel stays as a static front door. Both AWS workflows are archived. No replacement Actions deploy; Vercel's Git integration deploys (verify with W4 after the merge). |
| Q3 | **Yes.** `.agents/AGENTS.md` is amended as in §4.6 (done in PR #5). |
| Q4 | **Yes.** The local seed account is `demo.<date>@example.com` with a random password printed once and never committed (D7 stays intact for docs). |
| Q5 | **No deadline.** Work M1, then M2, then M3 in order. M1 still ships first, so the portfolio is presentable if an interview appears early. The video is recorded last, after the fixes. |
| Q6 | **Open, and blocks nothing.** Only the owner can read the AWS plan type (O10). |
