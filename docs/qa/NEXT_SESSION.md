# Next session: start here

Written 2026-10-04, at the end of the session that finished the M1 code items. Read this, then [README.md](README.md) (the tracker: decisions, queue, protocol), then `.agents/AGENTS.md` (the code rules). This page is a summary; the tracker is the source of truth.

## 1. Where things stand

ModelAudit AI (FastAPI backend, React/Vite frontend) runs **locally only**, to demo to interviewers (decision D12: AWS is retired). It must stay **free of cost** (D11): free tiers only, and no real confidential document may be uploaded because Gemini's free tier may train on prompts. The Vercel site is a static front door that says the backend is offline.

| Area | State |
|---|---|
| M1 code items (PR-01 providers, PR-02 structured output, PR-03 UI failure states, PR-04 chat privacy, NEW-02 sample label) | Merged to `main` in PR #6. 589 backend tests pass; frontend lint and build pass |
| Local demo kit (L-01) and Vercel front door (V-01) | Merged. The owner built it on Windows with Docker Desktop and seeded a demo account |
| Live providers | **Confirmed by the owner:** `preflight` all eight lines OK; `check-ai` passes 5 of 5 on gap analysis and 5 of 5 on compare |
| Decisions | O14 closed: the 50-message chat cap stays; NEW-11 (chunk and chat masking use different registries) is accepted as an unscheduled follow-up. The owner is deleting the AWS secrets in GitHub |
| **Not done** | The regulatory corpus is empty (QA-001), so Regulatory Library answers are thin; chat answers are capped at 1,024 tokens; the owner's UI pass (below); the portfolio polish |

## 2. Git state: act on this first

- Branch `ccr-69721f6f-73mabp`, head `ef0505f`. `main` is at `e97d231` (the merge of PR #6).
- The branch is **four commits ahead of `main`** and **no PR is open**: the Docker build fix (without it a fresh clone of `main` fails with `libGL.so.1`), the confirmed reranker and structured-output defaults, and docs. **Ask the owner whether to open the PR.** Do not open one unasked.
- PRs #5 and #6 are merged. Once the PR for these commits merges, restart the branch from the new `main` before more work: `git fetch origin main && git checkout -B ccr-69721f6f-73mabp origin/main`, then push with `--force-with-lease`.
- The five item branches (`fix/pr-01-providers`, `fix/pr-02-structured-output`, `fix/pr-03-ui-failures`, `fix/pr-04-chat-privacy`, `fix/new-02-interim-citation-label`) are already merged and can be ignored.

## 3. What the owner still has to do

1. **UI walkthrough** with the 10-minute script in [LOCAL_DEMO.md](../LOCAL_DEMO.md): sign in, Overview, Gap Analysis, lineage, upload `demo-data/synthetic_retail_pd_validation_v1.docx` (run `scripts/demo.sh fixtures`, or the PowerShell equivalent, to create it), AI Analyst, Privacy Inspector, RAG Performance. Includes the first PDF upload through Docling, which has never run live.
2. The checks in [local-test-guide.md](local-test-guide.md) §2 that remain: the PR-04 two-question chat, the NEW-02 amber labels, the PR-03 failure drills (invalid keys, `STRUCTURED_MAX_TOKENS=16`), and the PR-01 backup and dead-reranker drills.
3. **O12 timings:** clone to a seeded demo, the first upload, and Docker's memory during an upload.
4. **O3:** download the IFRS 9 issued-standard PDF from ifrs.org (free account). Needed by the corpus work (C2b, C5), not before.
5. **O10 rest:** AWS plan type; **do not upgrade the account**.

Ask for results as `preflight` output and log lines with every key and password removed.

## 4. The work queue

Full table: [README.md](README.md) §3. In short:

- **Parallel-safe, small:** PR-05 (masking vocabulary, phone masking), PR-08 (input validation), PR-09 (safe markdown), PR-11 (mobile header), PR-13, PR-15, PR-16, PR-17.
- **Corpus line, in order:** C1 (migration, manifest, catalog) then C2 (CBUAE HTML parser) and C2b (Basel and IFRS 9 parsers) in parallel, then C3 (ingest), C4 (retrieval, removes the hard-coded sample corpus), C5 (local ingest run), C6 (golden set), C7 (thresholds). Plan: [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md). This is the largest piece and the only thing that makes the Regulatory Library real.
- **PR-10** (streaming Regulatory Q&A and thinking-off for chat) removes the "Answer cut off" banner that long answers trigger today. It depends on C4.
- **L-02** (portfolio README, screenshots, demo video) goes last, after the owner's pass.
- **Deferred or superseded** (D12): PR-14, the PR-06 extras, PR-07, PR-18, PR-01b's SSM and canary parts. Do not start AWS-dependent items.

The owner's last open question to answer: stop at "demo-ready" and do L-02, or put agents on the corpus line and the small items first. The owner has said to build the PRs with separate agents and to test them locally at the end.

## 5. Confirmed live facts (2026-10-04)

- Chat model `nvidia/nemotron-3-super-120b-a12b`; embeddings `nvidia/nemotron-3-embed-1b` return 2048 dimensions, and the app slices to 1024 for the 1024-dimension cosine Pinecone index.
- Reranker `nvidia/llama-nemotron-rerank-vl-1b-v2` works. `llama-nemotron-rerank-1b-v2` answers 410 (retired 2026-08-25) and `llama-3.2-nv-rerankqa-1b-v2` answers 404. NVIDIA's `/v1/models` list contains no rerank models, so it is no guide; `preflight` is.
- The hosted NVIDIA API answers 400 to `nvext.guided_json`. `NVIDIA_STRUCTURED_MODE=top_guided_json` with thinking off works. Gemini `gemini-3.6-flash` and `responseJsonSchema` work.
- Model IDs change without notice. The owner runs `preflight` before every demo.
- Never run live: whether NIM accepts `dimensions`, Gemini thinking values, whether the real model copies `DOC-n`, real spaCy on real answers, multiple workers, Postgres at scale.
- Timing: rebuilding a chat's privacy registry costs 1.4 s cold at 50 messages and 0.07 s cached (sandbox, real spaCy).

## 6. How to work in this repo

**Verify before every push** (the sandbox has no Docker, no keys and blocks NVIDIA and Pinecone, so live checks are the owner's):

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
DATABASE_URL=sqlite+aiosqlite:///./ci_test.db RATE_LIMIT_ENABLED=true python -m pytest -q -p no:cacheprovider   # 589 passed
python -m ruff check app --select E9,F63,F7,F82
cd ../frontend && npm ci && npm run lint && npm run build
```

Without `DATABASE_URL` the suite fails at import with a SQLAlchemy URL error.

**Rules the owner set:**
- Never put a key or password in chat or in the repo.
- Never open a PR unless asked. Push only the designated branch.
- Do not write a model identifier into commits, PR text or code comments.
- Record decisions and verification in the tracker, in the same commit as the change.

**Lessons from this session:**
- Stage with explicit paths and print `git diff --cached --name-only` before every commit. A stale pathspec once aborted a `git add` chain and landed a commit without its code.
- Agent worktrees start at `main`, not at your branch. Tell each agent which branch to base on. Dry-run pairwise merges with `git merge-tree` before merging agent branches: three conflicts were found that way after a claim of "no conflicts".
- The Docling model download needs libGL, so it runs in the Dockerfile's runtime stage, not the builder.
- `vite preview` inherits the dev proxy, so it cannot show the Vercel offline case; use a static server with an SPA fallback.
- After editing `backend/.env`, run `docker compose up -d --force-recreate backend`. A restart does not re-read it.

## 7. Where things are

| Need | File |
|---|---|
| Run it locally (bash and PowerShell), troubleshooting | [docs/LOCAL_DEMO.md](../LOCAL_DEMO.md) |
| What to test and what to send back | [local-test-guide.md](local-test-guide.md) |
| Decisions, queue, owner items, verification log | [README.md](README.md) |
| Why AWS was retired, the re-scope | [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md), [aws-cost-report-2026-10-02.md](aws-cost-report-2026-10-02.md) |
| The 26 audit findings | [live-app-audit-2026-09-30.md](live-app-audit-2026-09-30.md) |
| Per-item plans (PR-nn) | [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md) |
| Corpus design and licence rules | [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md) |
| Probe tool | `backend/scripts/diag/pr00_probe.py`, [pr-00-runbook.md](pr-00-runbook.md) |
| Demo tooling | `scripts/demo.sh`, `backend/scripts/demo/` (`preflight`, `seed`, `check_ai`, `fixtures`) |
| Older PR #2 handoff (background only) | [HANDOFF.md](../../HANDOFF.md) |
