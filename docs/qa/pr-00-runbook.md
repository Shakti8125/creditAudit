# PR-00 verification runbook: how to run it

> **Superseded 2026-10-02 (D12).** The AWS account is gone, so **step A (AWS inspection) and step B (the one-off ECS probe task, O8) are void.** What remains of PR-00 is the keyed probe, run **locally**: copy `backend/.env.example` to `backend/.env`, fill in the provider keys, then from `backend/` run `python -m scripts.diag.pr00_probe --only nvidia,gemini,pinecone` and paste the printed lines (names, status codes and booleans only) into README §5. Task X-02 rewrites this page for local use and removes the AWS helper; the "what each result decides" table below still applies. See [aws-exit-and-rescope-plan.md](aws-exit-and-rescope-plan.md) §4.2 and §5.

This page is how to run [master plan §2](remediation-plan-2026-09-30.md#2-verification-first-step-pr-00-read-only-s). Record the results in [README §5](README.md#5-verification-log).
Rule for every step: print env and secret **names**, never values. Keyed calls run only inside the production container, never on a laptop or in the agent sandbox.

| Step | Plan §2 | Tool | Access | Status (2026-09-30) |
|---|---|---|---|---|
| A | 1, 2, 5 | `python -m scripts.diag.pr00_aws inspect` | AWS read-only | **Not run.** The AWS connector asked for sign-in again at the first call (O1). |
| B | 3, 4 and the QA-007 config shape | one-off ECS task running `scripts/diag/pr00_probe.py` | `ecs:RunTask` in prod, owner approval | **Proposed; awaiting owner approval** (O8, below). |
| — | extra | sandbox HTTP checks and web re-check | none | Done; see README §5. |

The sandbox cannot run step B itself: the egress policy blocks `integrate.api.nvidia.com`, `ai.api.nvidia.com` and `api.pinecone.io`, and the keys are not in the sandbox.

---

## Step A: read-only AWS inspection

From `backend/`, with AWS credentials for `us-east-1` (`pip install boto3`):

```bash
python -m scripts.diag.pr00_aws inspect > pr00_inspect.json
```

It prints, as JSON:
- **ECS**: per service, the task-definition revision, desired and running counts, and subnet and security-group IDs. Per task definition, the image repository and tag, **env names**, **secret names** and, for each secret, the *name* of the Secrets Manager secret or SSM parameter it reads from (no account ID, no value).
- **`staging_vs_prod`** (NEW-06, D9): whether staging and prod use the same task-definition revision and image, and which secrets they read from the same source.
- **Logs Insights, last 7 days**: per-day counts for every pattern in plan §2 step 2 (rate limiter, structured output, rerank, corpus scripts, egress), plus the 10 newest error lines for the rate-limiter, gap-analysis and rerank patterns, truncated, with URLs, keys and UUIDs removed.
- **CloudTrail `RunTask`** (last 90 days, up to 200 events): who ran which command. Any event whose command names `seed_regulatory_standards` or `index_regulatory_corpus` goes in `corpus_script_runs` (QA-001, QA-002).

An agent session with the AWS connector runs the same calls through the connector's `call_boto3`; the functions in `pr00_aws.py` are what it should print.

The plan's third CLI command (`environment[?name=='RATE_LIMIT_ENABLED']`) prints a value, so it is not used. Step B prints the parsed boolean instead.

---

## Step B: one-off probe task (awaiting owner approval)

### What would run

One Fargate task from the **production service's current task-definition revision**, in the service's own subnets and security groups (private, egress through the NAT gateway), with `startedBy=pr00-probe` (visible in CloudTrail). The only change is the container command:

```text
python -c "import hashlib,urllib.request as u;s=u.urlopen('https://raw.githubusercontent.com/Shakti8125/creditAudit/c6953eb78bd50e3ae271e58f522723786f88796c/backend/scripts/diag/pr00_probe.py',timeout=30).read();assert hashlib.sha256(s).hexdigest()=='d8c822e8e760711109a967070fa18cae3648fdc62657ba8db461c04ffa2cc570','pr00_probe.py sha256 mismatch';exec(compile(s,'pr00_probe.py','exec'),{'__name__':'__main__'})" --only nvidia,gemini,pinecone,redis
```

- The script is fetched from this public repo at commit `c6953eb` and runs **only** if its SHA-256 is `d8c822e8…2cc570`. Those are the exact bytes reviewed in this PR, so no image rebuild or deploy is needed.
- It reads the keys the way the app does (`app.config.settings`) and never prints them.

### What it calls (synthetic text only)

| Provider | Calls | Purpose |
|---|---|---|
| NVIDIA | `GET /v1/models` (1) | Are the IDs listed? A listing does not prove a model works. |
| NVIDIA | rerank, old and new model (2) | QA-006: the old endpoint is deprecated; the successor should return 200. |
| NVIDIA | chat, both generation models, `max_tokens=64` (2) | Liveness of the primary and the 404 fallback. |
| NVIDIA | chat, primary model, 7 structured-output variants (7) | QA-005: the request as deployed (top-level `guided_json`, no thinking flag, `temperature=0.7`, `max_tokens=1024`), then top-level `guided_json`, `nvext.guided_json` and `response_format` (json_schema), each with thinking on and off. |
| NVIDIA | embeddings, default and `dimensions=1024` (2) | Native dimension of `nemotron-3-embed-1b`, and whether a 1024 truncation is honoured. |
| Gemini | `GET models/<id>` (9) and the model list | Status of the retired, current and candidate IDs (2.0-flash, text-embedding-004, 2.5-flash, 3.5-flash, 3.6-flash, 3.8-flash, flash-latest, embedding-001, embedding-2). |
| Gemini | `generateContent`, D10 chain 3.6 → 3.5 → `flash-latest` (3) | Free-tier entitlement (D11) and the model that actually serves the alias. |
| Gemini | structured output on 3.6-flash (1-2) | `responseJsonSchema`, then `responseSchema` if the first is rejected (PR-02 input). |
| Pinecone | `list_indexes`, `describe_index`, `describe_index_stats` | Index dimension, metric, spec and state; namespaces grouped by prefix (tenant and document IDs are never printed); `cbuae-manuals` present or empty (QA-001, NEW-07). |
| Upstash | `PING`, `SCRIPT LOAD token_bucket.lua` | QA-007 hypothesis (d). `SCRIPT LOAD` is idempotent and the app does the same at startup. |

The Gemini key travels in the `x-goog-api-key` header, never in a URL, so no exception or log line can carry it.

### What it prints

One `PR00 {json}` line per check into the task's CloudWatch log stream. A line holds only names, HTTP status codes, `finish_reason`, lengths, token counts, dimensions and booleans. For config, that means *present or not*, the Redis URL **scheme** (`https`, `redis` or `rediss`), whether the host ends in `.upstash.io`, and the parsed `RATE_LIMIT_ENABLED` boolean. Provider error excerpts are truncated to 200 characters, and every configured secret, key pattern and URL is removed from them. Tests: `backend/tests/test_pr00_probe.py`.

### Cost and risk

- LLM usage is 14 NVIDIA calls, plus at most 5 Gemini generation calls and about 10 Gemini metadata reads, all on the free tiers (D11). The task runs for a few minutes on the existing task size, which costs about one US cent of Fargate time.
- Nothing is written to Postgres or Pinecone, and no service, task definition or setting changes.
- The task shares the production task role and network. It does not register with the load balancer, so it serves no traffic.

### How to run it (after approval)

The owner runs it, or a session with a working AWS connector does. From `backend/`:

```bash
# 1. Dry run: prints the exact RunTask request (subnet/SG IDs, command). Starts nothing.
python -m scripts.diag.pr00_aws probe-task --sha c6953eb78bd50e3ae271e58f522723786f88796c \
  --expect-sha256 d8c822e8e760711109a967070fa18cae3648fdc62657ba8db461c04ffa2cc570
# 2. Run it: starts the task, waits (typically 2-10 min) and prints the PR00 lines.
python -m scripts.diag.pr00_aws probe-task --sha c6953eb78bd50e3ae271e58f522723786f88796c \
  --expect-sha256 d8c822e8e760711109a967070fa18cae3648fdc62657ba8db461c04ffa2cc570 --run > pr00_probe.json
# If the wait times out: python -m scripts.diag.pr00_aws probe-logs --task-id <task id>
```

Paste `pr00_inspect.json` and `pr00_probe.json` into the PR, or let the next session read them.

---

## What each result decides

| Result | Decides |
|---|---|
| `nvidia_rerank`: new model 200, old 404/410 | PR-01 item 1 (reranker successor). |
| `nvidia_structured`: which variant gives `finish_reason=stop` and `schema_ok=true`, with and without thinking | PR-02 item 1 (`nvext.guided_json` vs `response_format`, thinking off). |
| `nvidia_embed.dimension` vs `pinecone_index.dimension` (`embed_vs_index.match`) | Whether the embedding call must pin `dimensions` (CorpusPlan §8) before any ingest. |
| `gemini_model` and `gemini_generate` statuses and `model_version` | PR-01 item 5 default model and the PR-01b chain; free-tier entitlement (D11). |
| `gemini_structured`: which schema field works | PR-02, Gemini side. |
| `config.redis_url_scheme`, `redis_host_is_upstash`, `rate_limit_enabled`; `redis.ping_ok` and `script_load_ok`; the Insights rate-limiter counts | Which QA-007 hypothesis (a)-(d) holds, so PR-06 item 1 fixes the right thing. |
| `staging_vs_prod` | NEW-06: whether PR-18's split is still needed (D9, a gate on C5). |
| `pinecone_stats.namespace_count` and `by_prefix` | NEW-07 (namespace cap). The plan tier is not exposed by the API; the owner reads it in the Pinecone console. |
| `cloudtrail_run_task.corpus_script_runs` | QA-001 and QA-002: whether a seed or index one-off ever ran. |
