# Local test guide: the M1 code items

For the owner, on a laptop with real API keys. Nothing here has been run against a live provider: the agents that built these items had no keys and no access to NVIDIA, Pinecone or Gemini. This guide is how you confirm them in one pass (tracker item **O13**) and what to send back.

**Branch to test:** `ccr-69721f6f-73mabp`. It holds the local-demo kit and the items below merged into one tree; 589 backend tests pass on that tree, and `npm run lint` and `npm run build` pass. Each item also has its own branch (`fix/pr-01-providers`, `fix/pr-02-structured-output` on top of PR-01, `fix/pr-04-chat-privacy`, `fix/new-02-interim-citation-label`, `fix/pr-03-ui-failures`) if you would rather review them one at a time. Those branches have three small textual conflicts between them (all "keep both sides"), so the integrated branch is the easier one to merge.

| Item | What it changes | Built in |
|---|---|---|
| PR-01 | Model IDs are settings; a dead reranker degrades cleanly; embeddings pinned; Gemini backup; optional start-up probe | `fix/pr-01-providers` |
| PR-02 | Structured output for gap analysis and compare: right request form, thinking off, budget, one repair, typed errors | `fix/pr-02-structured-output` |
| PR-04 | Chat privacy: `DOC-n` aliases, the same masking every turn, no filenames in Pinecone | `fix/pr-04-chat-privacy` |
| NEW-02 interim | "Illustrative sample, not official text" label on sample citations | `fix/new-02-interim-citation-label` |
| PR-03 | UI states for failed gap analysis and compare, truncation indicator | `fix/pr-03-ui-failures` |

## 0. Set up (about 15 minutes the first time)

```bash
git fetch origin
git checkout ccr-69721f6f-73mabp && git pull
cp backend/.env.example backend/.env      # fill in NVIDIA_API_KEY, PINECONE_API_KEY, PINECONE_INDEX_NAME, GEMINI_API_KEY
scripts/demo.sh up                         # see docs/LOCAL_DEMO.md for details and troubleshooting
scripts/demo.sh seed                       # note the email and password it prints
```

Never paste a key or a password into a chat or a file in the repository. After you edit `backend/.env`, run `docker compose up -d --force-recreate backend` so the container reads it.

## 1. Preflight and the probe (the numbers PR-01 and PR-02 depend on)

```bash
scripts/demo.sh preflight
docker compose exec backend python -m scripts.diag.pr00_probe | tee pr00.txt     # without Docker: cd backend && python -m scripts.diag.pr00_probe
```

Neither prints a secret. Read the preflight lines like this:

| Line | OK means | If it is not OK |
|---|---|---|
| Primary LLM answers | The NVIDIA key and the chat model work | Check `NVIDIA_API_KEY`; if the model is gone, set `NVIDIA_GENERATION_MODEL` |
| Embeddings | The embedding model answers (the line prints its size) | Check the key and `NVIDIA_EMBEDDING_MODEL` |
| Pinecone index ready | The index exists and is ready | Check `PINECONE_API_KEY` and `PINECONE_INDEX_NAME` |
| Embedding size matches the index | Uploads will store vectors (the app slices longer vectors to the pinned size) | The line says to set `EMBEDDING_DIMENSIONS` to the index size. If the model returns fewer dimensions than the index holds, create a new index of the right size |
| Reranker | The configured reranker answers (confirmed on 2026-10-04: `nvidia/llama-nemotron-rerank-vl-1b-v2` answers; the older text rerankers are retired) | A WARN names a candidate that works; set `NVIDIA_RERANK_MODEL` to it. The app keeps working without a reranker, only ranking quality drops |
| Structured output (gap analysis, compare) | The configured request returns valid JSON | A WARN names a working variant and the setting to change: `NVIDIA_STRUCTURED_MODE`, `NVIDIA_STRUCTURED_DISABLE_THINKING`, `STRUCTURED_MAX_TOKENS` or `GEMINI_STRUCTURED_SCHEMA_MODE` |
| Gemini backup (free tier) | The backup model answers | A WARN names the candidate that works; set `GEMINI_GENERATION_MODEL` |

Change the one setting a WARN names, recreate the backend, and run preflight again. The first live run (2026-10-04) confirmed the defaults for the chat, embedding and reranker models, structured output and the Gemini backup, so on a fresh setup every line should be OK. A WARN later usually means NVIDIA retired a model, and the line names the replacement.

## 2. Per item

### PR-04: the second chat question works

1. Sign in with the seeded account, open the model, go to the **AI Analyst** tab.
2. Click **Extract Metrics**. Then, in the **same chat**, ask: `Summarise the calibration results.` Both answers must arrive. Before the fix, the second one failed with "Request blocked by the privacy egress check".
3. The answer text shows the file name; the model itself only saw `DOC-1`. In **RAG Performance**, the latest trace must not be marked blocked (the failing case in the audit was recorded as blocked by `egress_violation`).
4. Ask `Does Example National Bank meet the minimum Gini?`, then open the **Privacy Inspector** (top bar, "Zero-Trust Protected") and close and reopen it a few times. The list of masked entities must be the same each time.
5. Optional, in the Pinecone console, namespace `user-docs:<tenant>:<document>`: new vectors carry `source` = `doc-<id>` and `document_id`, and no file name. Vectors from earlier uploads still hold the old name; delete and re-upload the document to replace them. `scripts/demo.sh reset` clears Postgres, not Pinecone.
6. A chat is capped at 50 messages: the 51st question returns HTTP 409 "Start a new conversation" (decision O14a).

### NEW-02: the sample label

All of these must show an amber "illustrative sample, not official text" notice or tag:
- **Regulatory Library**: a page notice; ask any question and the answer gets a notice and a tag on each `CBUAE-MMG-2022` citation; every row of the standards catalogue is tagged.
- **AI Analyst**: the source chips turn amber with a notice; reload the page and the saved chat is still labelled.
- **Citations** tab, and the **Gap Analysis** tab (every "CBUAE MMG" policy row and the checklist header).
- The top-bar search for a standard, **Settings** (the Gini text) and **RAG Performance** (a notice, and the golden dataset targets).
- **Export Report**: the JSON has a `notice` field.

Real sources (for example `CBUAE MMG` with a section number, or `Tenant policy`) must **not** be labelled.

### PR-01: provider resilience

1. Preflight above is the main check.
2. Backup drill: put an invalid value in `NVIDIA_API_KEY`, recreate the backend, ask one question in the AI Analyst. It should still answer through Gemini, and `docker compose logs backend` should contain `llm_failover from=nvidia to=gemini`. Restore the key afterwards.
3. Dead reranker drill: set `NVIDIA_RERANK_MODEL=nvidia/does-not-exist`, recreate, ask a question. It should still answer, and the log should show one `circuit_open breaker=nvidia/rerank` line and then silence. Restore the setting afterwards.
4. Optional: `LLM_STARTUP_PROBE=true` makes the backend check its models at start-up in the background; the log shows `model_ok` or `model_unavailable` per model.

### PR-02: gap analysis and compare, five out of five

```bash
scripts/demo.sh check-ai --email <the demo email>      # asks for the password
```

It calls gap analysis on version 2.0 five times and compare on both reports five times, and prints one line per call. **Pass: both endpoints show "5 of 5 succeeded".** A failed call shows its code, for example `structured_output_invalid`. Each call spends a little free-tier quota.

Force the failure messages (restore the settings afterwards): `STRUCTURED_MAX_TOKENS=16` should make the reply too short and fail with `structured_output_truncated` (expected, not yet seen); invalid values in both `NVIDIA_API_KEY` and `GEMINI_API_KEY` should fail with a provider error such as `provider_unavailable`.

### PR-03: failure states in the UI

PR-03 adds one database column (`chat_messages.truncated`). `scripts/demo.sh up` applies it (the backend container runs `alembic upgrade head` before it starts). If you run the backend without Docker, run `alembic upgrade head` yourself first.

1. **A failed call shows why.** Set invalid values in both `NVIDIA_API_KEY` and `GEMINI_API_KEY`, recreate the backend, open a model's **Gap Analysis** tab and click **Run analysis**. You should see a headline, a specific message, the error code (for example `provider_unavailable`) and a **Retry** button. The text "No AI gap analysis has been run" must **not** show while the failure is on screen; an earlier saved analysis stays visible below, labelled as not from this attempt. Restore the keys, click **Retry**, and it should succeed.
2. **A cut-off result is a failure, not a success.** Set `STRUCTURED_MAX_TOKENS=16`, recreate, then **Run analysis**, or **Documents > Compare**. Expect `structured_output_truncated` with a Retry button. In **Compare Models**, an error must not leave the previous pair's result on screen.
3. **The Library upload flow.** With the failing keys, **Regulatory Library > Upload & Analyze**: you should land on the Gap tab showing the failure with Retry, not on an empty tab.
4. **A cut-off chat answer is marked.** In the **AI Analyst**, ask for a very long answer, for example `Write 1,500 words on this document.` Expect an orange "Answer cut off" banner with a **Continue** button, and the banner must still be there after you reload the page. Regulatory Q&A answers get the same banner. The chat's output budget is still 1,024 tokens (QA-015 is not done), so this banner will appear often until PR-10.

## 3. What to send back

- The `scripts/demo.sh preflight` output, and `pr00.txt` (the lines that begin `PR00`). They hold no secrets.
- For any step that did not behave as described: the step, what you saw, and the relevant lines of `docker compose logs backend` with any key or password removed.
- The three timings L-01 asks for (O12): clone to a seeded demo, the first upload, and Docker's memory during an upload.
- Your answers to the decisions below.

## 4. Decisions (O14)

1. **Chat cap.** PR-04 limits a chat to 50 messages and answers the next one with HTTP 409. Keep it, or change the number (`MAX_SESSION_MESSAGES`)?
2. **NEW-11.** A document's chunks are masked when it is uploaded with their own registry, while a chat uses its session registry, so `[ORG_1]` in a chunk and in a question can be two different entities. Accept it as a follow-up item or drop it?
3. **`.agents/AGENTS.md`.** Two lines are stale since PR-01: CI/CD still mentions a "provider canary" (dropped, it needs your keys as GitHub secrets), and rule 9's tail still says the code has hard-coded model constants (they are settings now). May they be updated?

## 5. Known gaps, so nothing here surprises you

- **Confirmed live on 2026-10-04 (first owner run):** the NVIDIA chat and embedding models, the reranker `nvidia/llama-nemotron-rerank-vl-1b-v2`, `gemini-3.6-flash`, structured output on NVIDIA (`top_guided_json`, thinking off) and on Gemini (`responseJsonSchema`), and the 1024-dimension slice against a 1024 index.
- **Never run live:** whether the hosted NVIDIA API accepts `dimensions`, the Gemini thinking values on the free tier, the five-out-of-five check, whether the real model copies `DOC-1`, real spaCy on real answers, multiple workers, Postgres (the tests use SQLite), and the first PDF upload time.
- **Left for later:** thinking-off for plain chat and regulatory Q&A (QA-015, PR-10); a scrub of old filenames in Pinecone; `/regulatory/search` does not get PR-04's substitution (PR-05, C4); the raw API JSON and `/docs` are not labelled as sample text.
- **Dropped on purpose:** the weekly provider canary (needs your keys as GitHub secrets; `preflight` and the probe replace it).
