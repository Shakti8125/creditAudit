# Run ModelAudit AI locally

ModelAudit AI reviews credit-risk model validation documents against regulatory standards. **It is not hosted anywhere.** The AWS deployment of September 2026 was retired to keep the project free of cost (decision D12), so the backend runs on your own machine, and a live walkthrough is shown from there. The Vercel site is only a front door that says so.

This page takes you from a fresh clone to a seeded demo and gives a 10-minute script for showing it.

## What you need

| Need | Why |
|---|---|
| Docker Desktop, or Docker Engine with Compose v2 | Runs Postgres and the backend. On Windows, use WSL 2. |
| Node.js 20 or newer | Runs the frontend dev server. |
| About 6 GB of memory given to Docker | The backend loads Docling and spaCy `en_core_web_lg`. The AWS task used 4 GB; the local figure is not measured yet. |
| An NVIDIA API key | The primary LLM, embeddings and reranker. Free from build.nvidia.com. |
| A Pinecone key and a Serverless index | The vector store. The free Starter plan is enough. |
| A Gemini key (optional) | The backup LLM, on the free tier. |

**Free-tier caution (D11).** Gemini's free tier may use prompts to improve Google's products. Use only the synthetic documents that come with the demo, or documents that are public. Never upload a real confidential document.

## The short path

```bash
git clone https://github.com/Shakti8125/creditAudit.git
cd creditAudit

cp backend/.env.example backend/.env      # then fill in the keys, see below
scripts/demo.sh up                        # builds and starts everything, waits until healthy
scripts/demo.sh preflight                 # checks the providers work right now
scripts/demo.sh seed                      # first time only: demo account and synthetic models
```

Open <http://localhost:5173> and sign in with the email and password that `seed` printed. **The password is shown once and is stored nowhere.** If you lose it, run `scripts/demo.sh reset` and seed again.

The first `up` builds the image, which downloads the Python packages and the Docling models, so it takes several minutes. Later starts take under a minute plus the model load. (Targets, not yet measured: a fresh clone to a seeded demo in under 15 minutes, and a first upload under 10 seconds.)

### Fill in `backend/.env`

| Variable | Value |
|---|---|
| `NVIDIA_API_KEY` | Your NVIDIA key. |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` | Your Pinecone key and the name of your index. |
| `GEMINI_API_KEY` | Optional backup. |

Leave the JWT keys empty: the backend makes a temporary key pair each time it starts, so after a restart you sign in again. Leave `RATE_LIMIT_ENABLED=false` and the Redis values empty. `backend/.env` is git-ignored; never commit it.

**The Pinecone index.** Create a Serverless index with metric `cosine` and dimension 1024. The app pins the embedding size with `EMBEDDING_DIMENSIONS` (default 1024): longer vectors from the model are sliced to it. If your index has another size, set `EMBEDDING_DIMENSIONS` to match. Run `scripts/demo.sh preflight` once: "Embedding size matches the index" turns green when they agree. Embeddings never use another model or provider, so changing the embedding model or size means a new index and re-embedding every document.

**Model IDs.** Every model the app calls is a setting with a default (commented in `backend/.env.example`, section "Provider models"). Change one only when `preflight` says it is gone.

### The commands

| Command | What it does |
|---|---|
| `scripts/demo.sh up` | Starts Postgres and the backend in Docker, applies the database migrations, starts the frontend, and waits until `/health` says `db: connected`. |
| `scripts/demo.sh down` | Stops everything and keeps the data. |
| `scripts/demo.sh status` | Shows whether the backend and frontend answer. |
| `scripts/demo.sh preflight` | One line per capability: OK, WARN or FAIL. **Run it ten minutes before an interview.** Model IDs change often. |
| `scripts/demo.sh seed` | Creates `demo.<date>@example.com` with a random password, one synthetic PD model with versions 1.0 (passes) and 2.0 (breaches), and uploads the two synthetic reports. |
| `scripts/demo.sh fixtures` | Writes the two synthetic reports to `demo-data/`, so you can upload one live in the UI. |
| `scripts/demo.sh reset` | Deletes the database after asking. |

The backend listens on `127.0.0.1:8001` and Postgres on `127.0.0.1:5432`, never on the network.

## A 10-minute walkthrough

Seed first, then run `scripts/demo.sh fixtures` so you have a file to upload.

| Minutes | Do | Say |
|---|---|---|
| 0-1 | Sign in. On **Overview**, point at the model card (`BREACH`, version 2.0) and the KPI tiles. | Which model is in trouble, at a glance. |
| 1-3 | Open the model. **Metrics** tab, then **Gap Analysis**. | Metrics are extracted from the document and benchmarked against the CBUAE thresholds. Version 2.0 breaches on all six metrics. |
| 3-4 | Top bar, the lineage button (**Model Lineage & Version History**). | Version 1.0 passed, version 2.0 failed: the history is kept per version. |
| 4-6 | **New Audit**, upload `demo-data/synthetic_retail_pd_validation_v1.docx`. | The pipeline: extract, mask personal data, chunk, embed, analyse. |
| 6-8 | **AI Analyst** tab: click **Extract Metrics** and point at the citations. | Answers cite the document passages they came from. |
| 8-9 | Top bar, **Zero-Trust Protected** (the Privacy Inspector). It lists what was masked in this chat before it reached the LLM. Then paste the sign-off line from the report into the masking simulator. | Names and the e-mail address become `[PERSON_1]`, `[PERSON_2]` and `[EMAIL_1]`, and the bank name becomes `[ORG_1]`; that is what the LLM receives instead of the originals. |
| 9-10 | **RAG Performance**. | Every answer is traced and can be evaluated against a golden dataset. |

### What does not work yet

These are real findings from the live audit, with fixes planned in the [remediation tracker](qa/README.md). Do not demo them until their item is done, or say so openly.

| Area | Today | Fix |
|---|---|---|
| A second AI Analyst question in the same chat | Can be blocked by the privacy egress check (QA-004). Ask one question per chat, or start a new chat. | PR-04 |
| **Compare Models** and the LLM gap analysis | Can fail or return unstructured output (QA-005). | PR-02 |
| **Regulatory Library** answers | The regulatory corpus is empty, so answers are thin (QA-001). | M2 |
| Reranker | The old model was deprecated (QA-006). The app now calls a successor chosen from public docs, not yet confirmed with a live key. If it is gone, answers still work (retrieval keeps its fused order) but quality may drop. `preflight` shows the state and, if another reranker works, names the `NVIDIA_RERANK_MODEL` to set. | PR-01 (done; confirm with `preflight`) |

## Without Docker

If Docker does not fit on your machine, run the backend directly:

```bash
# Postgres 16 must be running, with a database called modelaudit (user and password postgres).
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --port 8001          # leave it running

# In another terminal, from the repository root:
export DEMO_NATIVE=1 DEMO_PYTHON="$PWD/backend/.venv/bin/python"
scripts/demo.sh up          # checks the backend, starts the frontend
scripts/demo.sh preflight
scripts/demo.sh seed
```

`DEMO_NATIVE=1` tells the script that you run the backend yourself. `scripts/demo.sh reset` cannot drop your database in this mode; do that yourself.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `backend/.env is missing` | Run `cp backend/.env.example backend/.env` and fill in the keys. |
| The image build fails at the Docling model step | The build downloads models from huggingface.co. Check the connection and run `docker compose build` again. |
| `up` times out waiting for the backend | Read the log: `docker compose logs --tail 60 backend`. On the first start the models take a few minutes to load. If the container exits with code 137, Docker ran out of memory: raise it to 6 GB or more in Docker Desktop's settings, or run without Docker. |
| Port 5432, 8001 or 5173 is already in use | Stop the other program. Both published ports are bound to localhost on purpose. |
| `seed` fails at the first upload with HTTP 500 | The provider keys are missing or unreachable. Run `scripts/demo.sh preflight`. |
| `preflight` says the embedding size does not match the index | Create a Pinecone index whose dimension equals the embedding size that `preflight` prints. |
| You are signed out after a restart | Expected: the demo uses temporary signing keys. Sign in again. |
| The Vercel site says the backend is offline | Expected. It is a front door and the backend is not hosted. Open <http://localhost:5173> instead. |
| `Request blocked by the privacy egress check` in the AI Analyst | Known issue QA-004; start a new chat. |

## Costs

The demo costs nothing: Postgres and the backend run in Docker on your machine, and NVIDIA, Pinecone and Gemini are used on their free tiers. If a free tier runs out, the demo stops; it does not start charging. Keep evaluation runs small.
