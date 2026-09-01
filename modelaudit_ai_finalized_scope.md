# ModelAudit AI — Finalized Project Scope & Key Functionalities

> **Project Type**: Portfolio/demo project targeting FDE (Forward Deployed Engineer) roles  
> **Domain**: Model Risk Management (MRM) / Model Validation for UAE commercial banking  
> **Target Users**: Credit risk model validators at banks analyzing model development/validation documents against CBUAE MMG regulatory standards

---

## Elevator Pitch

**ModelAudit AI** is a privacy-preserving virtual analyst that helps credit risk model validators at banks analyze their model development and validation documents against CBUAE Model Management Guidelines (MMG) and Basel III regulatory standards. It features zero-trust privacy masking, hybrid RAG retrieval, automated gap analysis, and multi-provider LLM routing.

---

## Finalized Core Functionalities

### 1. Document Upload & Extraction
- Upload PDF model development/validation documents
- IBM Docling with Granite Table Structure Recognition for high-fidelity extraction
- Converts PDFs to structured markdown preserving tables, headers, and financial data
- In-memory stream processing (no unencrypted intermediate files on disk)

### 2. Zero-Trust Privacy Pipeline (Core Differentiator)
- **Aho-Corasick automaton** for GCC/global bank name matching → `[BANK_1]`, `[BANK_2]`
- **spaCy NER + Presidio** for borrower/person entity masking → `[ORG_1]`, `[PERSON_1]`
- **Financial number preservation** (currencies, ratios, percentages, dates are NOT masked)
- **Egress firewall** validates no unmasked entities leak to LLM providers
- **Entity registry** stays in server-side session memory only (never persisted)
- **Zero-trust boundary**: Your backend ↔ LLM provider (NOT analyst machine ↔ cloud)

> [!IMPORTANT]
> The privacy pipeline runs **server-side** (not on the analyst's machine) since the application is browser-only via a deployed URL. The zero-trust guarantee is with respect to the LLM provider — no real entity names are ever sent to Gemini or NVIDIA.

### 3. On-Device Model Validation Analytics (Re-scoped)
**ModelMetricsExtractor** (replaces FinancialExtractor):
- Extract model validation metrics: **Gini Coefficient, AUC, KS Statistic, PSI**
- Extract backtesting results, discrimination testing outcomes
- Multi-currency/scale normalization preserved from original design

**PolicyChecker** (re-scoped to CBUAE MMG):
- Benchmark extracted metrics against CBUAE MMG thresholds:
  - Gini ≥ 40%, AUC ≥ 0.70, KS ≥ 30%, PSI ≤ 0.25
- Produce compliance verdicts: **PASS / WARNING / BREACH**

**EarlyWarningDetector** (re-scoped to model risk):
- Scan for model risk signals: model drift, poor discrimination, inadequate documentation
- Qualitative signal detection in validation report narratives

### 4. Hybrid RAG Retrieval
- **Dense retrieval**: NVIDIA NV-EmbedQA-E5-v5 (1024-dim) or Gemini embeddings
- **Lexical retrieval**: BM25Okapi (k1=1.5, b=0.75)
- **Fusion**: Reciprocal Rank Fusion (RRF, k=60)
- **Reranking**: NVIDIA NV-RerankQA-Mistral-4B neural cross-encoder
- **Vector store**: Pinecone Serverless (free tier)
- **Knowledge base**: CBUAE MMG Parts 1-3, Capital Adequacy Regulations

> [!IMPORTANT]
> The LLM prompt payload is a **combination of CBUAE MMG regulatory chunks AND relevant chunks from the uploaded document**. Both corpora are retrieved and fused.

### 5. Document Comparison (`/compare`)
- Side-by-side comparison of two model documents
- Highlight differences in methodology, assumptions, or validation results
- Delta analysis (v1 vs v2, or ModelA vs ModelB)

### 6. NeMo Guardrails 2.0
- **Colang 2.0 dialog flows** for domain boundary enforcement
- **Jailbreak/prompt injection detection** via Nemotron Guard 8B
- **SelfCheckGPT hallucination checking** against retrieved contexts
- **Arithmetic verification** custom Python action for model metrics
- **Topic restriction** to model validation, credit risk, and CBUAE policy only

---

## Five Core User Workflows

| # | Workflow | Description |
|---|---------|-------------|
| 1 | **Conversational Q&A** | Upload a model document, ask questions like "Does this PD model meet CBUAE MMG backtesting standards?" — RAG-powered answers citing both the doc and CBUAE regulations |
| 2 | **Automated Gap Analysis** | System scans the uploaded document and produces a checklist of MMG compliance gaps (e.g., "Missing: discrimination testing via Gini coefficient") |
| 3 | **Metric Extraction & Benchmarking** | Extract Gini, AUC, KS, PSI from the document and auto-benchmark against CBUAE MMG thresholds with PASS/WARNING/BREACH status |
| 4 | **Document Comparison** | Compare two model documents side-by-side, highlighting differences in methodology, assumptions, or validation results |
| 5 | **Regulatory Citation Lookup** | Query CBUAE MMG sections directly (e.g., "What are the CBUAE requirements for LGD model validation?") even without uploading a document |

---

## UI Components (React Frontend)

All seven panels included in the initial build:

| Panel | Description |
|-------|-------------|
| **Chat Interface** | Persistent conversation thread with follow-up questions. **Streaming responses** via SSE. |
| **Document Viewer** | Show uploaded document's extracted content or original PDF preview alongside chat |
| **Metrics Dashboard** | Visual cards/badges for Gini, AUC, KS, PSI with color-coded CBUAE compliance (PASS/WARNING/BREACH) |
| **Gap Analysis Report** | Structured checklist showing MMG compliance gaps found in the document |
| **Masking Inspector** | Panel showing masked entities and token mappings (demonstrates privacy pipeline) |
| **Document Comparison View** | Side-by-side view for `/compare` with highlighted differences |
| **Citations Panel** | Expandable source citations showing CBUAE regulation sections and document excerpts |

> Design will be provided by the user from **Figma**.

---

## Architecture Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Frontend** | React (single UI) | Design from Figma, modern portfolio impression |
| **Backend** | FastAPI (Python) | Async, high-performance, OpenAPI docs |
| **LLM Provider** | **Pluggable: Gemini + NVIDIA NIM** | Auto cost/latency-optimized routing between providers |
| **Model Routing** | Automatic cost/latency/availability-based | Impressive systems-engineering talking point |
| **Vector Store** | Pinecone Serverless (free tier) | Managed, zero-ops, 100K vectors free |
| **Database** | AWS RDS PostgreSQL (db.t4g.micro) | Real multi-tenancy, ~\$13/month |
| **Auth** | Custom JWT (RS256) with FastAPI | Self-built registration/login, demonstrates auth knowledge |
| **Multi-tenancy** | Functional (real login, tenant isolation) | Two analysts can use simultaneously with separate data |
| **Rate Limiting** | Upstash Redis (free tier) + Lua scripts | Token Bucket + GCRA, impressive systems engineering |
| **Deployment** | Docker Compose (local) + AWS ECS Fargate (prod) + Vercel (frontend) | FDE-grade: containerization + live demo URL |
| **Response Streaming** | SSE (Server-Sent Events) | Real-time token streaming from LLM → backend → frontend |
| **Privacy Pipeline** | Server-side masking | Zero-trust boundary = your backend ↔ LLM provider |
| **Guardrails** | Full NeMo Guardrails 2.0 | Colang flows, jailbreak detection, arithmetic verification |
| **Document Formats** | PDF + Word (.docx) | Both extracted via IBM Docling with table structure recognition |
| **CI/CD** | GitHub Actions (3-stage pipeline) | PR gates → Staging → Production deploy with manual approval |
| **Gemini Model** | Pinned to `gemini-2.0-flash` | Avoids breakage from Google's model version rotation |

---

## Excluded from Initial Build

| Feature | Reason |
|---------|--------|
| ~~Credit Memo Generation~~ | Project pivoted to model validation Q&A tool, not memo synthesis |
| ~~Streamlit Terminal UI~~ | Single React frontend only |
| ~~Portfolio EWS Scan (`/ews`)~~ | Not selected in feature scope |
| ~~Tamper-Evident Audit Trail~~ | Not selected in feature scope |
| ~~On-premises client controller~~ | Browser-only deployment, no local Python runtime |

---

## Deployment & Cost Estimate

| Service | Provider | Monthly Cost |
|---------|----------|-------------|
| React Frontend | Vercel (free tier) | \$0 |
| FastAPI Backend | AWS ECS Fargate (scale-to-zero) | ~\$5-10 |
| PostgreSQL | AWS RDS db.t4g.micro | ~\$13 |
| Load Balancer | AWS ALB | ~\$16 |
| Vector Store | Pinecone Serverless (free tier) | \$0 |
| Rate Limiting | Upstash Redis (free tier) | \$0 |
| Container Registry | Amazon ECR (free tier: 500MB) | \$0 |
| CI/CD | GitHub Actions (free: 2000 min/month) | \$0 |
| **Total** | | **~\$35-40/month** |
| **\$140 credit duration** | | **~3.5 months** |

---

## Regulatory Knowledge Base

Pre-indexed in Pinecone:
- ✅ CBUAE Model Management Guidelines (MMG) Parts 1-3
- ✅ CBUAE Capital Adequacy Regulations (CAR) Parts 1-11
- ✅ Basel III Framework & IFRS 9 Guidelines

Documents provided by the user as PDFs.

---

## Key Interview Talking Points (FDE Angle)

1. **Zero-Trust Privacy Architecture** — Entity masking ensures no real names reach the LLM. Demonstrates understanding of banking secrecy laws and data residency requirements.
2. **Multi-Provider LLM Routing** — Automatic cost/latency-optimized routing between Gemini and NVIDIA NIM. Shows systems-engineering depth.
3. **Hybrid RAG with Dual Corpus** — Combines uploaded document chunks with regulatory knowledge base chunks. Not just a simple RAG.
4. **Distributed Rate Limiting** — Atomic Redis Lua scripts implementing Token Bucket and GCRA algorithms. Enterprise-grade API protection.
5. **Deterministic Analytics** — Model validation metrics extracted via regex/pattern matching, not LLM guessing. Financial accuracy guaranteed.
6. **Docker Containerization** — `docker-compose.yml` for local dev, same containers deploy to AWS ECS Fargate. Exactly what FDEs do.
7. **NeMo Guardrails** — Production AI safety for regulated industries. Jailbreak detection, hallucination checking, arithmetic verification.
