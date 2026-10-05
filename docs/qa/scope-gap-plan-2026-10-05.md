# Scope gap plan: what the documents promise versus what the code does

Date: 2026-10-05. Status: **plan only; nothing in it is implemented.** Base: `main` at `e97d231` (PR #6 merged).
Reads with: [README.md](README.md) (owner decisions, tracker, protocol), [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md) ("master plan"), [regulatory-corpus-ingestion-plan.md](regulatory-corpus-ingestion-plan.md) ("CorpusPlan"), [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) ("exit plan"), [local-test-guide.md](local-test-guide.md) and [../LOCAL_DEMO.md](../LOCAL_DEMO.md).

The scope documents (`modelaudit_ai_finalized_scope.md`, the stack list in `.agents/AGENTS.md`, the Settings and Help copy) describe more than the code does today. This plan lists every gap that a reader of the repository, a visitor to the front door or an interviewer watching a demo would notice. For each one it says what the code does instead, with `file:line` evidence, and gives the steps that close it. It reuses the tracker's items wherever they exist, and adds one finding (**NEW-12**, guardrails) and one optional item (**C6-pre**, an early retrieval benchmark).

---

## 0. In short

- **Eight gaps, G1-G8.** Six are already covered by tracker items; this plan puts them in order and defines "done" for each. G5 is new (NEW-12). G4 gains an optional fast path (C6-pre).
- **The rule:** a capability goes into the README, the front door, the demo video or a description of the project only after its **Done when** check has passed and a row in [README §5](README.md#5-verification-log) records it.
- **Best value first:**
  - G1 takes about two hours of the owner's time with real keys, and turns four "code done" items into verified ones.
  - G2 takes half a day to a day and gives the repository a front page. Today it has none.
  - G4's fast path takes one to two days and produces the first retrieval number worth quoting, without waiting for the corpus.
- **Biggest single piece:** G3, the regulatory corpus (M2, about 15-20 dev-days).
- **Constraints that still bind:**
  - free of cost (D11) and local only (D12);
  - the privacy rules in `.agents/AGENTS.md`;
  - synthetic or public documents only while Gemini runs on its free tier.

---

## 1. The gaps at a glance

| ID | Gap | What the documents say | What the code does (evidence) | Bridge | Size |
|---|---|---|---|---|---|
| G1 | The M1 fixes are not verified against live providers | The tracker marks PR-01, PR-02, PR-03 and PR-04 "CODE DONE, owner check pending". [LOCAL_DEMO.md](../LOCAL_DEMO.md) says "done; confirm with preflight". | The code is done and tested offline (589 tests pass, README §5, 2026-10-04). It has never run with a real key: O12 and O13 are open. | O12, O13; then PR-01, PR-02, PR-03 and PR-04 close | S (owner) |
| G2 | No front page: no root README, screenshots or video | Exit plan L-02 | The repository root has no `README.md`. `frontend/dev.err` and `frontend/dev.out` are tracked, and seven planning documents sit at the root. The front door (V-01) has no video link (`VITE_DEMO_VIDEO_URL` unset). | L-02 (README part brought forward), V-01 settings | S/M |
| G3 | The regulatory knowledge base is empty | "Knowledge base: CBUAE MMG Parts 1-3, Capital Adequacy Regulations", and a "Pre-indexed in Pinecone" list including Basel III and IFRS 9 (`modelaudit_ai_finalized_scope.md:55,156-161`) | The regulatory Pinecone namespace holds 0 vectors and `regulatory_standards` 0 rows (README §1). The only regulatory text is 10 illustrative paragraphs (`backend/app/services/retrieval/hybrid_retriever.py:39-140`, NEW-02). | M2: PR-05, C1, C2, C2b, C3, C4, C5L | L |
| G4 | No retrieval-quality numbers | HANDOFF §3: offline evaluation with Hit@k, Recall@k, MRR, nDCG@k and faithfulness | The evaluation runs, but no baseline is recorded. The 22 default cases are built from the illustrative paragraphs (`backend/app/services/evaluation/default_dataset.py:1,20,207`), so a score on them measures sample text. | C6-pre (optional, new), C6 | S/M, then M |
| G5 | Guardrails are keyword rules; the NeMo runtime is not wired | "NeMo Guardrails 2.0", "Colang 2.0 dialog flows", "Jailbreak/prompt injection detection via Nemotron Guard 8B", "SelfCheckGPT hallucination checking" (`modelaudit_ai_finalized_scope.md:65-70,120,175`); stack "NeMo Guardrails 0.11+ (Colang 2.0)" (`.agents/AGENTS.md:21`) | See the evidence list below this table. | NEW-12 (new) | S (A) or M (B) |
| G6 | Rate limiting is not enforced | "Distributed Rate Limiting: atomic Redis Lua scripts implementing Token Bucket and GCRA" (`modelaudit_ai_finalized_scope.md:116,172`) | The limiter allows everything when it is off or has no Redis client (`backend/app/middleware/rate_limiter.py:60-61`). It fails open on any error (`:136`). In production, 40 parallel requests all passed (QA-007). The local demo runs with `RATE_LIMIT_ENABLED=false` and no Redis. | PR-06-lite | S |
| G7 | Phone numbers are never masked, and regulator names are | Settings and Help: phone numbers become `[PHONE_1]` (QA-010) | `_is_protected` drops every span made only of digits and punctuation, and that includes Presidio's phone hits, so **no phone number is ever masked** (`backend/app/services/privacy/ner_masker.py:167-171,238-245`, QA-010). "Basel III IRB" becomes `[ORG_1]` (QA-009). | PR-05 | S/M |
| G8 | Policy thresholds are presented as CBUAE requirements | "Benchmark extracted metrics against CBUAE MMG thresholds: Gini ≥ 40%, AUC ≥ 0.70, KS ≥ 30%, PSI ≤ 0.25" (`modelaudit_ai_finalized_scope.md:40-42`) | CBUAE never published these numbers (NEW-02). They are hardcoded with `rule_basis="CBUAE MMG"` (`backend/app/services/analytics/policy_checker.py:139,158,177`), and the UI labels them "illustrative sample" (NEW-02 interim). | C7, after C6 | M |

**G5 evidence:**
- **Input rails.** They are substring lists of seven or eight phrases each (`backend/app/services/guardrails/actions.py:197,231,268`). `checks.py:41-43` calls them directly, not through Colang.
- **Hallucination check.** It is a word-overlap score with a 0.6 threshold (`actions.py:90`, `checks.py:19`).
- **NeMo runtime.** No route calls `GuardrailsService`, the NeMo `LLMRails` wrapper with `rails.co` (`guardrails_service.py:23`).
- **Output rails on `/query`.** They only log (`backend/app/api/query.py:401`).

The scope document also states things the project deliberately dropped: cost- and latency-based routing, a staging pipeline, AWS hosting. Those are decisions, not gaps to close. §4 gives the wording to use instead.

---

## 2. How to work an item

- Follow [README §4](README.md#4-protocol-for-an-agent-taking-an-item):
  - claim the tracker row in your first commit, one item per PR;
  - run the local checks (`pytest`, `ruff`, `npm run lint`, `npm run build`);
  - add a §5 row and a §8 change-log line.
- Every step that calls a provider spends free-tier quota:
  - run `scripts/demo.sh preflight` first;
  - keep evaluation runs small;
  - record the model IDs that actually served.
- **Done when** is literal. If a check cannot be run, the gap stays open. Say so in §5 rather than claiming it.

---

## 3. Bridging instructions

### G1. Verify the M1 fixes with live keys (O12, O13)

**Why:** PR-01, PR-02, PR-03 and PR-04 are "code done, owner check pending". Until a live run passes, the demo may still fail the way the audit saw it fail: compare and gap analysis at 0 of 5 (QA-005), and the reranker down (QA-006).

1. **Set up once** ([LOCAL_DEMO.md](../LOCAL_DEMO.md), "The short path"):
   - run `cp backend/.env.example backend/.env`;
   - fill in `NVIDIA_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` and `GEMINI_API_KEY`;
   - the Pinecone index is Serverless, metric `cosine`, dimension 1024.
2. **Start the stack:** `scripts/demo.sh up`. Note the time from clone to healthy, and watch `docker stats` during the first upload (O12 asks for both).
3. **Run `scripts/demo.sh preflight`.** Every required row must read OK.
   - If the structured-output row fails, set `NVIDIA_STRUCTURED_MODE` to the value preflight names.
   - If the reranker row fails, set `NVIDIA_RERANK_MODEL` to the candidate it names.
   - Run it again until it passes.
4. **Run the probe:** `cd backend && python -m scripts.diag.pr00_probe`. Keep the `PR00 {...}` lines; they hold no secrets.
5. **Seed and check:** `scripts/demo.sh seed`, then `scripts/demo.sh check-ai --email <the seeded email> --runs 5`.
6. **Run the drills** in [local-test-guide.md](local-test-guide.md) §2:
   - PR-04: the second chat turn;
   - PR-01: the backup drill (with an invalid `NVIDIA_API_KEY`, answers still arrive through Gemini, and the log shows `llm_failover from=nvidia to=gemini`);
   - PR-01: the dead-reranker drill;
   - PR-03: the failure states.
7. **Record:** one §5 row per item with the numbers. Close O12 and O13, and set the PR-01, PR-02, PR-03 and PR-04 rows to DONE.

**Done when:**
- preflight exits 0;
- `check-ai` exits 0 (all 10 calls return 200);
- both PR-01 drills pass;
- the §5 rows exist.

**Size:** S. Owner work: about two hours, plus the first image build.

### G2. Give the repository a front page (L-02, V-01)

**Why:** a visitor to the repository finds no README. They see seven planning files at the root, two tracked dev-server logs and a large `.agents/` folder. The Vercel front door says the backend is offline by design, but has no video to show instead.

1. **Owner decision:** bring L-02's README and tidy forward to straight after G1. Today L-02 sits in M3, and Q5 set the order M1, M2, M3. The video stays last.
2. **Write `README.md` at the root**, following the exit plan's L-02:
   - a one-paragraph pitch, and an honest status line: "Not publicly hosted. Deployed on AWS ECS Fargate in September 2026, since retired. A live walkthrough on request.";
   - five screenshots from the seeded local demo, synthetic data only: Overview with the BREACH card, Gap Analysis, AI Analyst with citations, the Privacy Inspector, RAG Performance;
   - a Mermaid diagram of the request path: upload → Docling → masking (Aho-Corasick, spaCy, Presidio) → chunking → NVIDIA embeddings → Pinecone and BM25 → reciprocal rank fusion → rerank → LLM router (NVIDIA, Gemini on failover) → egress validator → SSE stream;
   - how privacy works, the stack, and "Run it locally" (link `docs/LOCAL_DEMO.md`);
   - the engineering story: the live QA audit and its 26 findings, the remediation plan, the cost lesson;
   - only claims that pass the rule in §0, worded as in §4.
3. **Tidy:**
   - stop tracking the logs with `git rm --cached frontend/dev.err frontend/dev.out`, and add both to `frontend/.gitignore`;
   - move the seven root planning documents into `docs/history/`, with a short `docs/README.md` index. They are `backend_bug_report.md`, `backend_code_audit_report.md`, `backend_gap_plan.md`, `frontend_implementation_plan.md`, `implementation_plan.md`, `modelaudit_ai_finalized_scope.md` and `pending_backend_changes_tier2_tier3.md`;
   - fix the links that point to them (`git grep -n <name>` for each);
   - leave `.agents/` and `HANDOFF.md` where they are.
4. **Video, last** (after M1, ideally after M2):
   - two to three minutes, following the 10-minute script in `LOCAL_DEMO.md`;
   - upload it unlisted, then set `VITE_DEMO_VIDEO_URL`, `VITE_REPO_URL` and `VITE_CONTACT_URL` in the Vercel project;
   - redeploy, and check that the front door shows the buttons.
5. **Optional, for one interview:** the short-lived tunnel in exit plan §7. Do G6 first, and stop the tunnel straight after.

**Done when:**
- GitHub renders the README with its screenshots and diagram;
- no logs are tracked;
- the front door links the video.

**Size:** S/M.

### G3. Load the real regulatory corpus (M2)

**Why:** regulatory Q&A and retrieval over two corpora at once are the product's main promise. Today the regulatory side answers from 10 sample paragraphs.

1. **Do PR-05 first (G7).** Without it, regulation text and questions lose terms such as "Basel III IRB" to `[ORG_n]` (CorpusPlan AC8).
2. **Build the corpus items** as CorpusPlan §20 and exit plan §4.4 describe (a local source directory instead of S3):
   - C1 first;
   - then C2 and C2b in parallel;
   - then C3, C4 and C5L.
   - C3 needs PR-01 verified (G1). C4 needs PR-04.
3. **Owner action O3:** download the IFRS 9 issued standard from ifrs.org (a free "Basic" account). Keep it in `CORPUS_LOCAL_DIR`, never in git.
4. **Run the ingest locally** with the CLI that C1-C3 build:
   - `python -m scripts.regulatory acquire`;
   - then `verify`, a dry run (record the article and chunk counts);
   - then `ingest`.
   - **Never** run `scripts/seed_regulatory_standards.py` or `scripts/index_regulatory_corpus.py`.
5. **Check acceptance:** CorpusPlan AC1-AC4 and AC6-AC12 on the local stack. Record each in §5.

**Done when:**
- those acceptance criteria pass once locally (the M2 exit criterion);
- `/health` shows `regulatory_corpus: ready`.

**Size:** about 15-20 dev-days (exit plan §6).

### G4. Produce retrieval-quality numbers (C6-pre, C6)

**Why:** the evaluation code exists but nothing has been measured. It covers four retrieval modes, scores Hit@k, Recall@k, Precision@k, MRR and nDCG@k, and judges faithfulness with an LLM.

**Never quote a number from the 22 default cases.** They score retrieval over the 10 sample paragraphs, and the regulatory dense namespace is empty.

**Fast path: C6-pre** (optional; after G1 and PR-05; one to two days). This is a document-scoped benchmark on public documents. It needs no corpus work, because uploaded documents already go through the whole pipeline.

1. **Choose two or three long public documents** that resemble model documentation. Examples: a supervisor's published guide to model risk management or to IRB model validation, or a bank's public Pillar 3 report. Public or synthetic only (D11).
2. **Upload them as tenant documents** and note their `document_id`s.
3. **Write 30 cases** with `POST /rag/eval/cases` or the RAG Performance page:
   - about 15 factual look-ups, 10 conceptual questions, and 5 questions the documents do not answer;
   - each case sets `document_id`, and `expected_refs` with a `section`, `keywords` with `min_keyword_hits`, or a `chunk_index` (`backend/app/schemas/rag_eval.py:322-400`);
   - export the set with `GET /rag/eval/cases` into `backend/eval_sets/public-docs-v1.json`, so it is versioned and can be re-created.
4. **Run retrieval only first:**
   ```json
   POST /rag/eval/runs
   {"modes": ["dense", "bm25", "hybrid", "hybrid_rerank"], "top_k": 5,
    "include_generation": false, "label": "public-docs-v1 retrieval"}
   ```
   Then run `hybrid_rerank` alone with `"include_generation": true, "judge": "auto"`. Generating and judging in all four modes would cost four times the free-tier quota. Only one run per tenant can be active at a time.
5. **Record in §5:**
   - Hit@5, MRR and nDCG@5 per mode;
   - faithfulness, and p50 and p95 latency;
   - the document titles and page counts, the date, and the model IDs that served.
6. **Quote it with its scope.** For example: "document-scoped retrieval over N public documents (M pages), 30 hand-written questions".

**Main path: C6** (after G3).
1. **Build golden set v2** per CorpusPlan §15.2: at least 30 cases including Basel and IFRS 9 ones, `article_ids` matching, and the v1-to-v2 upgrade.
2. **Run it:** RAG Performance → Evaluation, golden v2, all four modes, k=5, generation on.
3. **Check the AC5 gates:**
   - `hybrid_rerank` Hit@5 ≥ 0.85 and MRR ≥ 0.65;
   - `dense` Hit@5 ≥ 0.70;
   - `bm25` Hit@5 ≥ 0.60;
   - faithfulness ≥ 0.8.

   Below a gate, tune the chunker or the headers, run again, and record both runs.

**Done when:**
- the run you quote has a §5 row with per-mode numbers;
- the README quotes it with its scope.

**Size:** C6-pre S/M; C6 M.

### G5. Make the guardrails real and measured (NEW-12)

**Why:** substring lists miss paraphrases, other languages and instructions hidden in pasted document text. They can also block a harmless question that happens to contain a listed phrase. The documents promise a model-based detector. For a tool pitched at regulated banks, anyone who reads `actions.py` will see the difference.

**Step 0, for either option: measure first** (S, no keys needed).
1. **Add a labelled set**, `backend/tests/data/guardrails/labelled_prompts.jsonl`, of at least 100 prompts. Synthetic text only.
   - **At least 40 attacks:** direct, paraphrased, role-play, an instruction hidden inside a pasted report excerpt, non-English, obfuscated.
   - **At least 40 harmless domain questions**, including hard negatives such as "ignore the previous version's PSI" and "what should the system prompt of a model-governance chatbot say?".
   - **At least 20 off-topic questions.**
2. **Add `backend/scripts/eval_guardrails.py`.** It runs `run_input_guardrails` over the set and prints precision, recall and F1 per label, plus every misclassified prompt.
3. **Record the keyword baseline** in §5.

**Option A: describe it honestly** (S).
1. Describe what runs, in the scope document and in the README (G2): "rule-based input and output rails (NeMo `@action` functions called directly)".
2. **Owner decision:** delete the unused runtime (`guardrails_service.py`, `config.yml`, `rails.co`).
   - `nemoguardrails` would then remain only for the `@action` decorator (`actions.py:7`).
   - Replace that with a local no-op decorator and drop the dependency, which also shrinks the image.
   - Changing the AGENTS.md stack line needs owner approval.

**Option B: a measured, model-based detector** (M; recommended).
1. **Add two settings** in `app/config.py`:
   - `GUARDRAIL_DETECTOR`: `keywords` or `classifier`, default `keywords`;
   - `GUARDRAIL_MODEL`: an exact ID, per AGENTS.md rule 9.
2. **Choose the detector** (owner):
   - **B1, in process.** A small open-weights prompt-injection classifier run on CPU, for example one of Meta's Prompt Guard models on Hugging Face.
     - No text leaves the server and no quota is spent.
     - It adds a model to the image, as Docling's models do. Check its licence, size and memory use before choosing it.
   - **B2, through the router.** NVIDIA's NemoGuard jailbreak-detection endpoint on build.nvidia.com (or its current successor), added as a new router method with its own circuit breaker.
     - Confirm the model ID with a probe first; model IDs change often.
     - It sends text to a provider, so it must run **after** masking and the egress validator. Today the input rails run on the raw question before masking (`query.py:277`, before the masking at `:305-317`), so this path changes that order.
3. **Keep the keyword rules** as a free first pass, and call the detector only when they pass.
4. **Handle detector failure.** If the detector errors or times out, use the keyword verdict and record `guardrail_degraded=true` on the trace. Never let a request through without that record.
5. **Compare on the same set.** Run Step 0's set against the keywords and the detector, and record precision, recall, F1 and p50 latency in §5. Switch the default only if the detector has higher recall on attacks and a false-positive rate on the hard negatives no worse than the keywords'.
6. **Optional, grounding:** on the endpoints that do not stream (gap analysis, compare, regulatory search), replace the word-overlap grounding check with the existing judge (`backend/app/services/evaluation/judge.py`). On the streamed `/query`, keep it log-only and show a "low grounding" flag in the trace.
7. **Tests:**
   - the setting switch;
   - for B2, a test that the detector never receives text the egress validator has not passed;
   - the fallback when the detector fails;
   - the evaluation script on a small fixture.

**Done when:**
- a §5 row shows the baseline and the chosen option's numbers on the same set;
- the documents describe what actually runs;
- NEW-12 is DONE.

**Size:** Step 0 S; option A S; option B M.

### G6. Enforce rate limiting and prove it (PR-06-lite)

1. **Build PR-06-lite** from the master plan's QA-007 fix items 2-4:
   - validate the configuration at startup: an `https://` Upstash REST URL, and a token;
   - log `rate_limiter state=enabled|disabled|degraded`, and show the state in `/health`;
   - use `EVAL` with the script body when the script SHA is missing;
   - replace the fail-open at `rate_limiter.py:136` with an in-process fallback token bucket.
2. **Add the master plan's tests:**
   - a `redis://` URL is rejected;
   - the fallback bucket limits requests when the Redis mock raises;
   - a 429 carries `Retry-After`.
3. **Prove it locally, for free.**
   - Create an Upstash free-tier Redis database.
   - In `backend/.env`, set `REDIS_URL` (the database's `https://…upstash.io` REST URL), `REDIS_TOKEN` and `RATE_LIMIT_ENABLED=true`, then recreate the backend.
   - Sign in as the seeded account (FREE tier) and fire 80 requests, 20 at a time. `read -s` keeps the password out of the shell history:
     ```bash
     read -rsp "Password: " PW; echo
     TOKEN=$(curl -s -X POST http://127.0.0.1:8001/auth/login -H 'content-type: application/json' \
       -d "{\"email\": \"<the seeded email>\", \"password\": \"$PW\"}" \
       | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])')
     seq 1 80 | xargs -P 20 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
       -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8001/regulatory/standards | sort | uniq -c
     ```
   - Expect at least 40 responses with status `429`.
4. **Prove the degraded state.** Set a wrong `REDIS_TOKEN`, recreate the backend and run the same command. `/health` must show `degraded`, and the fallback bucket must still return `429`s.
5. **Record** both runs in §5. The rest of PR-06 stays deferred under D12 (exit plan §7).
6. **Keep the demo default.** The local demo keeps `RATE_LIMIT_ENABLED=false` (LOCAL_DEMO.md). Turn it on only for this proof or for a tunnel session.

**Done when:**
- the §5 row shows the 429 counts in both states;
- `/health` shows the limiter state.

**Size:** S.

### G7. Close the gaps in what gets masked (PR-05)

1. **Implement PR-05** as the master plan's QA-009 and QA-010 sections specify:
   - a public regulatory vocabulary, plus citation tokens, for the composite-name rule;
   - `_is_protected` applied to spaCy ORG, PERSON and GPE spans only;
   - a `PhoneRecognizer` with the GCC regions and a UAE regex recogniser, while financial numbers stay protected.
2. **Add the tests** listed there (`test_privacy_regulatory_vocab.py`, `test_privacy_phone_masking.py`), and run the nightly stress harness (`nightly-eval.yml`).
3. **Re-run both audit repros locally:**
   - in the Privacy Inspector simulator, the QA sentence shows `[PHONE_1]` for `+971 50 123 4567`;
   - the question "What is the minimum historical data period for PD estimation under Basel III IRB?" keeps "Basel III IRB" in its `query_masked` trace.

**Done when:**
- both repros pass;
- the nightly run is green;
- §5 records them.

**Size:** S/M. It can run in parallel with other items.

### G8. Present the thresholds as what they are (C7)

1. **Until C7 lands,** describe them as "configurable tenant policy thresholds (illustrative defaults)". The UI already labels them (NEW-02 interim).
2. **After C6, build C7:**
   - relabel the rule basis "Tenant policy (MMS 9.4.1)" (D3);
   - add `regulatory_refs` to real thresholds where a source has one;
   - drive gap analysis from the catalog (QA-008).
3. **Remove the NEW-02 interim registry** as the master plan's NEW-02 section describes. `test_illustrative_sample_registry.py` fails on purpose as the reminder.

**Done when:**
- C7 is DONE;
- no number that CBUAE does not publish carries the rule basis "CBUAE MMG".

**Size:** M.

---

## 4. Wording to use until a gap closes

| The scope document says | Say instead | Until |
|---|---|---|
| "NeMo Guardrails 2.0 … jailbreak detection via Nemotron Guard 8B … SelfCheckGPT" | "Rule-based input and output guardrails: jailbreak and prompt-injection screening, a grounding check, arithmetic checks on the metrics" | G5 option B is measured |
| "Knowledge base: CBUAE MMG, CAR, Basel III and IFRS 9, pre-indexed in Pinecone" | "Retrieval over the uploaded documents. The regulatory corpus pipeline is designed and planned." | G3 |
| Any retrieval-quality figure | Nothing | G4 |
| "Distributed rate limiting (Token Bucket and GCRA in Redis Lua)" | "Token-bucket and GCRA limiter scripts; enforcement is being fixed" | G6 |
| "Phone numbers are masked" | Do not mention phone numbers | G7 |
| "Benchmarked against CBUAE MMG thresholds" | "Benchmarked against configurable policy thresholds" | G8 |
| "Automatic cost/latency-optimized routing between providers" (`modelaudit_ai_finalized_scope.md:110-111,170`) | "NVIDIA NIM primary, Gemini on failover, with per-method circuit breakers" (D4) | Not planned |
| "GitHub Actions (3-stage pipeline): PR gates, staging, production deploy with manual approval" (`:122`) | "CI on every pull request (tests, lint, type check, build) and a nightly privacy stress run" | Not planned: the staging workflow never ran, and both deploy workflows are archived (X-01) |
| "Docker Compose (local) + AWS ECS Fargate (prod) + Vercel" (`:117`) | "Deployed on AWS ECS Fargate in September 2026, since retired; runs locally with Docker Compose" | Not planned (D12) |

---

## 5. Recommended order

| Step | Gaps | Why this order |
|---|---|---|
| 1 | G1 | Everything else assumes a working demo, and it takes about two hours. |
| 2 | G2: README and tidy | The first thing every visitor sees. Needs the owner's agreement to move it ahead of M2. |
| 3 | G7, G6 | Small, and they can run in parallel. G7 is a prerequisite for G3 and for a clean C6-pre. |
| 4 | G5: Step 0, then option A or B | Step 0 needs no keys and gives a number either way. |
| 5 | G4: fast path (C6-pre) | The first retrieval number worth quoting. |
| 6 | G3 (M2) | The largest piece. |
| 7 | G4: main path (C6), then G8 (C7) | Both need the corpus. |
| 8 | G2: the video | Last, so it shows the fixed behaviour (Q5). |

If an interview is close, do G1, then G2's README, and stop. This matches the exit plan's "ship M1 and stop".

---

## 6. Tracker changes made with this plan

- [README.md](README.md):
  - a link to this plan;
  - tracker rows **NEW-12** (G5) and **C6-pre** (G4's fast path), and a new lane I (guardrails);
  - a §8 change-log line.
- [remediation-plan-2026-09-30.md](remediation-plan-2026-09-30.md): NEW-12 in §1, §4 and §6.
- `modelaudit_ai_finalized_scope.md`: a banner that points here.
