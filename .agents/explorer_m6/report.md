# Dependency Compatibility & Cross-Cutting Package Audit (R2) — ModelAudit AI Backend

**Audit Scope**: Explorer M6 (`backend/requirements.txt`, all imports across `backend/app/`, `backend/Dockerfile`, `backend/alembic.ini`)  
**Target Environment**: Python 3.12, FastAPI 0.112+, PostgreSQL 16, SQLAlchemy 2.0 (async), Docker Multi-Stage Build  
**Audit Date**: 2026-08-28  

---

## 1. Executive Summary

A comprehensive dependency and cross-cutting package audit of the ModelAudit AI backend was performed. The audit analyzed all 61 Python files across `backend/app/`, `backend/requirements.txt`, `backend/Dockerfile`, and `backend/alembic.ini`.

### Summary of Findings by Severity
| Severity | Count | Primary Impact Areas |
| :--- | :---: | :--- |
| **Critical** | 2 | Security vulnerability (CVEs in `python-jose`) & severe Python 3.12 build/runtime failure (`passlib[bcrypt]` + `bcrypt==3.2.2`) |
| **High** | 3 | Alembic model discovery failure in `env.py`, spaCy runtime model download blocking, and Dockerfile runtime missing shared libraries for Docling |
| **Medium** | 3 | SDK name mismatch (`pinecone-client` vs `pinecone`), Google SDK duplication (`google-genai` vs `langchain-google-genai`), and redundant LangChain packages vs direct `openai`/`google-genai` |
| **Low** | 3 | Unused dependencies (`tiktoken`, `presidio-anonymizer`), obsolete Pydantic v1 extra (`pydantic[dotenv]`), and Python 3.12 `datetime.utcnow()` deprecation |
| **Total** | **11** | |

---

## 2. Detailed Dependency Findings

### Finding 1: Critical Security Vulnerability and Architecture Violation in JWT Package (`python-jose` vs `PyJWT`)
- **Dependency / Package**: `python-jose[cryptography]` vs `PyJWT`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 19: `python-jose[cryptography]`)
  - `backend/app/utils/security.py` (Line 7: `from jose import jwt, JWTError`, Lines 32, 42, 47, 49)
- **Severity**: **Critical**
- **Category**: Deprecated Package / Security Vulnerability
- **Description**:
  1. `python-jose` is unmaintained (last released in 2021, v3.3.0) and contains known vulnerabilities, including **CVE-2024-33663** (algorithm confusion / key confusion) and **CVE-2024-33664** (vulnerability to denial of service via exponential decompression / token parsing).
  2. `python-jose` has broken compatibility with modern `cryptography>=42.0.0` due to deprecated internal OpenSSL backend references removed in newer `cryptography` releases.
  3. The project's strict architecture rule in `AGENTS.md` explicitly mandates: `Auth: Custom RS256 JWT (PyJWT, bcrypt)`. Using `python-jose` directly violates the project's non-negotiable tech stack requirements.
- **Correct Specification / Fix**:
  - In `backend/requirements.txt`: Remove `python-jose[cryptography]` and add `PyJWT[crypto]>=2.8.0` (or `PyJWT>=2.8.0` with `cryptography>=42.0.0`).
  - In `backend/app/utils/security.py`: Replace `from jose import jwt, JWTError` with `import jwt` and catch `jwt.PyJWTError` (or `jwt.InvalidTokenError`).
  ```python
  # Proposed fix for backend/app/utils/security.py
  import jwt
  from jwt.exceptions import PyJWTError

  def decode_token(token: str) -> dict[str, Any]:
      try:
          return jwt.decode(token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm])
      except PyJWTError as e:
          raise ValueError("Invalid token") from e
  ```

---

### Finding 2: Python 3.12 Build Failure & Compatibility Conflict in `passlib` and Pinned `bcrypt==3.2.2`
- **Dependency / Package**: `passlib[bcrypt]` and `bcrypt==3.2.2`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 20: `passlib[bcrypt]`, Line 21: `bcrypt==3.2.2`)
  - `backend/app/utils/security.py` (Line 8: `from passlib.context import CryptContext`, Line 12: `pwd_context = CryptContext(...)`)
- **Severity**: **Critical**
- **Category**: Dependency Compatibility / Build Failure
- **Description**:
  1. `passlib` 1.7.4 (released 2020, unmaintained) attempts to detect bcrypt version via `bcrypt.__about__.__version__`. In `bcrypt>=4.0.0`, `__about__` was removed, causing `passlib` to crash at runtime with `ValueError: password cannot be hashed with bcrypt`.
  2. The pin `bcrypt==3.2.2` was added as a legacy workaround. However, `bcrypt 3.2.2` **does not have pre-built binary wheels for Python 3.12**.
  3. When building on Python 3.12 (especially in `python:3.12-slim`), `pip install bcrypt==3.2.2` attempts to build from source via CFFI, which fails without `python3-dev`, `gcc`, and `libffi-dev`.
  4. Furthermore, `passlib` uses the standard library `crypt` module which is deprecated in Python 3.12 and removed in Python 3.13.
- **Correct Specification / Fix**:
  - Remove `passlib[bcrypt]` and unpin `bcrypt==3.2.2` from `requirements.txt`.
  - Pin modern `bcrypt>=4.1.0` (which has pre-built wheels for Python 3.12).
  - Use `bcrypt` directly in `backend/app/utils/security.py`:
  ```python
  # Proposed fix for backend/app/utils/security.py
  import bcrypt

  def hash_password(plain: str) -> str:
      """Hash a plain text password using bcrypt."""
      salt = bcrypt.gensalt(rounds=12)
      return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")

  def verify_password(plain: str, hashed: str) -> bool:
      """Verify a plain text password against a bcrypt hash."""
      return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
  ```
  - In `backend/requirements.txt`:
  ```text
  bcrypt>=4.1.0
  ```

---

### Finding 3: Missing Document Models in Alembic Discovery (`env.py` and `app/models/__init__.py`)
- **Dependency / Package**: `alembic` & `sqlalchemy` (Model Metadata Registration)
- **Affected Files / Imports**:
  - `backend/alembic/env.py` (Line 12: `from app.models.user import Tenant, User`)
  - `backend/app/models/__init__.py` (Empty file, 0 bytes)
  - `backend/app/models/document.py` (`Document`, `DocumentChunk`)
- **Severity**: **High**
- **Category**: Cross-Cutting Package / Model Discovery
- **Description**:
  1. In `backend/alembic/env.py`, `target_metadata = Base.metadata` is used for autogenerating database migrations.
  2. Line 12 only imports `from app.models.user import Tenant, User`. The models `Document` and `DocumentChunk` from `backend/app/models/document.py` are never imported.
  3. `backend/app/models/__init__.py` is completely empty.
  4. Consequently, when running `alembic revision --autogenerate`, Alembic will fail to discover `documents` and `document_chunks` tables, generating incomplete migrations or dropping existing document tables.
- **Correct Specification / Fix**:
  - In `backend/app/models/__init__.py`, re-export all models:
  ```python
  from app.models.user import Tenant, User, RoleEnum, TierEnum
  from app.models.document import Document, DocumentChunk, DocumentStatus

  __all__ = [
      "Tenant", "User", "RoleEnum", "TierEnum",
      "Document", "DocumentChunk", "DocumentStatus"
  ]
  ```
  - In `backend/alembic/env.py`, import all models from `app.models`:
  ```python
  from app.models import Tenant, User, Document, DocumentChunk
  ```

---

### Finding 4: Blocking Runtime spaCy Model Download & Redundant Dockerfile Pinning
- **Dependency / Package**: `spacy` (`en_core_web_lg`)
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 12: `spacy>=3.7.0`)
  - `backend/Dockerfile` (Line 11: `RUN python -m pip install --user spacy==3.7.0`, Line 12: `RUN python -m spacy download en_core_web_lg --user`)
  - `backend/app/services/privacy/ner_masker.py` (Lines 43-48)
- **Severity**: **High**
- **Category**: Dependency Packaging / Runtime Reliability
- **Description**:
  1. `app/services/privacy/ner_masker.py` attempts `spacy.cli.download("en_core_web_lg")` inside an exception handler on `OSError` during `__init__()`. Downloading a ~500MB model synchronously inside a worker thread at runtime causes request timeouts, worker restarts, or crashes in read-only/no-internet production environments.
  2. In `backend/Dockerfile`, line 11 executes `pip install --user spacy==3.7.0`, overriding line 10 (`requirements.txt` with `spacy>=3.7.0`). Note that `spacy 3.7.0` does not provide binary wheels for Python 3.12 (`spacy>=3.7.2` introduced official Python 3.12 wheels).
- **Correct Specification / Fix**:
  - In `backend/requirements.txt`, pin `spacy>=3.7.2` and specify the direct wheel for `en_core_web_lg` or install it deterministically during image build:
  ```text
  spacy>=3.7.2
  https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
  ```
  - In `backend/Dockerfile`: Remove line 11 (`pip install spacy==3.7.0`) completely to prevent downgrading and wheel build failure.
  - In `backend/app/services/privacy/ner_masker.py`: Remove runtime `spacy.cli.download` call and raise a clean configuration error instructing the user/administrator to install the model asset.

---

### Finding 5: Dockerfile Runtime Stage Missing Required C-Libraries for Docling
- **Dependency / Package**: `docling>=2.0.0` / System Dependencies (`libgl1`, `libgomp1`)
- **Affected Files / Imports**:
  - `backend/Dockerfile` (Lines 14-23, runtime stage)
  - `backend/app/services/document_extractor.py` (`from docling.document_converter import DocumentConverter...`)
- **Severity**: **High**
- **Category**: Container Environment / Missing System Dependencies
- **Description**:
  1. Stage 1 (`builder`) in `backend/Dockerfile` installs `build-essential`.
  2. Stage 2 (`runtime`) starts from clean `python:3.12-slim` without installing any system libraries via `apt-get`.
  3. IBM Docling 2.0+ and its underlying layout analysis / OCR dependencies (such as PyMuPDF, Torch, OpenCV, and EasyOCR) dynamically link against `libGL.so.1`, `libgomp.so.1`, and `libglib2.0-0`.
  4. In the runtime container, calling `DocumentExtractor()` will fail with `ImportError: libGL.so.1: cannot open shared object file` or `libgomp.so.1: cannot open shared object file`.
- **Correct Specification / Fix**:
  - In `backend/Dockerfile`, add runtime shared libraries in the `runtime` stage:
  ```dockerfile
  FROM python:3.12-slim as runtime
  WORKDIR /app

  RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
      && rm -rf /var/lib/apt/lists/*
  ```

---

### Finding 6: Pinecone SDK Package Name Mismatch (`pinecone-client` vs `pinecone`)
- **Dependency / Package**: `pinecone-client` vs `pinecone`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 16: `pinecone-client`)
  - `backend/app/services/retrieval/pinecone_store.py` (Line 2: `from pinecone import Pinecone`)
- **Severity**: **Medium**
- **Category**: Deprecated Package / Dependency Naming
- **Description**:
  1. `pinecone-client` was the legacy distribution name for Pinecone SDK v2.x.
  2. In Pinecone SDK v3.0.0+ (and current v5.x), the official PyPI package name is `pinecone`.
  3. Code in `backend/app/services/retrieval/pinecone_store.py` uses the v3+ class syntax `from pinecone import Pinecone` and `self.pc.Index(...)`.
  4. Specifying `pinecone-client` without version pin in `requirements.txt` can resolve to legacy versions or transitional shims, leading to import errors or API discrepancies.
- **Correct Specification / Fix**:
  - In `backend/requirements.txt`, replace `pinecone-client` with `pinecone>=5.0.0` (or `pinecone>=3.0.0`).

---

### Finding 7: Google SDK Duplication and Incompatibility (`google-genai` vs `langchain-google-genai`)
- **Dependency / Package**: `google-genai` vs `langchain-google-genai` (`google-generativeai`)
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 9: `google-genai`, Line 32: `langchain-google-genai`)
  - `backend/app/services/llm/gemini_provider.py` (Line 8: `from google import genai`, Line 9: `from google.genai import types`)
  - `backend/app/services/guardrails/config.yml` (Line 10: `engine: langchain-google-genai`)
- **Severity**: **Medium**
- **Category**: Dependency Conflict / Redundancy
- **Description**:
  1. `backend/app/services/llm/gemini_provider.py` is written using the latest unified **`google-genai`** SDK (launched late 2024 for Gemini 2.0+).
  2. `langchain-google-genai` in `requirements.txt` depends on the older, legacy SDK **`google-generativeai`**.
  3. Installing both packages results in conflicting Google namespaces (`google.genai` vs `google.generativeai`), duplicate protobuf dependencies, and increased Docker image size.
- **Correct Specification / Fix**:
  - Migrate NeMo Guardrails configuration to use OpenAI-compatible engine wrappers or direct GenAI invocation.
  - Remove `langchain-google-genai` from `requirements.txt`.

---

### Finding 8: Redundant LangChain Dependencies vs Native Provider SDKs
- **Dependency / Package**: `langchain-nvidia-ai-endpoints` and `langchain-google-genai`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Lines 30, 32)
  - `backend/app/services/guardrails/config.yml` (Lines 3, 10)
  - `backend/app/services/llm/nvidia_provider.py` (Uses native `openai>=1.40.0` and `httpx`)
  - `backend/app/services/llm/gemini_provider.py` (Uses native `google-genai`)
  - `backend/app/services/llm/router.py` (Uses native providers)
- **Severity**: **Medium**
- **Category**: Redundant Dependency / Architecture Bloat
- **Description**:
  1. The core LLM routing, generation, streaming, embedding, and reranking across `backend/app/services/llm/` are implemented directly via `openai` (AsyncOpenAI for NVIDIA NIM) and `google-genai` (for Gemini).
  2. `langchain-nvidia-ai-endpoints` and `langchain-google-genai` are only referenced in `app/services/guardrails/config.yml`.
  3. These two packages introduce over 40 transitive dependencies (including multiple versions of LangChain core/community), which frequently cause dependency resolution conflicts with `pydantic>=2.0` and `fastapi>=0.112.0`.
- **Correct Specification / Fix**:
  - Configure NeMo Guardrails models to use `openai` engine with `base_url: https://integrate.api.nvidia.com/v1`, eliminating the need for `langchain-nvidia-ai-endpoints` and `langchain-google-genai`.

---

### Finding 9: Unused Dependencies in `requirements.txt` (`tiktoken`, `presidio-anonymizer`)
- **Dependency / Package**: `tiktoken`, `presidio-anonymizer`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 14: `presidio-anonymizer`, Line 24: `tiktoken`)
  - `backend/app/services/privacy/ner_masker.py` (Only imports `from presidio_analyzer import AnalyzerEngine`)
  - `backend/app/services/chunker.py` (Uses regex and whitespace tokenization, no `tiktoken`)
- **Severity**: **Low**
- **Category**: Unused Package / Dependency Bloat
- **Description**:
  1. `tiktoken` is specified in `requirements.txt` (Line 24), but is not imported or used anywhere across `backend/app/`.
  2. `presidio-anonymizer` is specified in `requirements.txt` (Line 14). However, `backend/app/services/privacy/ner_masker.py` only imports `presidio-analyzer`. Masking and replacement are executed by the project's custom `EntityRegistry` and `MaskingPipeline`.
- **Correct Specification / Fix**:
  - Remove `tiktoken` and `presidio-anonymizer` from `backend/requirements.txt`.

---

### Finding 10: Obsolete Pydantic v1 Extra in `requirements.txt`
- **Dependency / Package**: `pydantic[dotenv,email]>=2.0`
- **Affected Files / Imports**:
  - `backend/requirements.txt` (Line 3: `pydantic[dotenv,email]>=2.0`, Line 4: `pydantic-settings`)
  - `backend/app/config.py` (`from pydantic_settings import BaseSettings, SettingsConfigDict`)
- **Severity**: **Low**
- **Category**: Dependency Compatibility / Deprecated Extra
- **Description**:
  1. In Pydantic v1, `pydantic[dotenv]` was used for environment file loading.
  2. In Pydantic v2, all dotenv and settings parsing was moved to the standalone package `pydantic-settings`. The `dotenv` extra in `pydantic[dotenv]` is obsolete and emits deprecation warnings.
  3. `pydantic-settings` is unpinned on line 4.
- **Correct Specification / Fix**:
  - Update `requirements.txt`:
  ```text
  pydantic[email]>=2.8.0
  pydantic-settings>=2.4.0
  email-validator>=2.2.0
  ```

---

### Finding 11: Deprecated `datetime.utcnow()` Usage on Python 3.12
- **Dependency / Package**: `datetime` (Standard Library) / Python 3.12 Runtime
- **Affected Files / Imports**:
  - `backend/app/models/document.py` (Line 29: `default=datetime.utcnow`)
  - `backend/app/models/user.py` (Lines 33, 48: `default=datetime.utcnow`)
  - `backend/app/utils/security.py` (Lines 24, 36: `datetime.utcnow()`)
  - `backend/app/api/health.py` (Line 24: `datetime.utcnow().isoformat()`)
- **Severity**: **Low**
- **Category**: Python 3.12 Compatibility / Deprecation
- **Description**:
  - `datetime.datetime.utcnow()` is officially deprecated in Python 3.12 and emits `DeprecationWarning`. It is scheduled for removal in future Python releases.
- **Correct Specification / Fix**:
  - Replace `datetime.utcnow()` with `datetime.now(datetime.timezone.utc)` (or `datetime.now(timezone.utc)`).

---

## 3. Recommended Clean `backend/requirements.txt`

Below is the fully reconciled, Python 3.12-compatible `requirements.txt` specification:

```text
# Web Framework & Server
fastapi>=0.112.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
httpx>=0.27.0

# Schemas & Settings (Pydantic v2)
pydantic[email]>=2.8.0
pydantic-settings>=2.4.0
email-validator>=2.2.0

# Database & ORM (SQLAlchemy 2.0 Async)
sqlalchemy[asyncio]>=2.0.32
asyncpg>=0.29.0
alembic>=1.13.2
aiosqlite>=0.20.0

# Security & Authentication (RS256 JWT & Modern Bcrypt)
PyJWT[crypto]>=2.8.0
cryptography>=42.0.0
bcrypt>=4.1.0

# Rate Limiting & Caching
upstash-redis>=1.0.0

# LLM Providers (Native SDKs)
openai>=1.40.0
google-genai>=0.1.1

# Document Extraction
docling>=2.0.0
docling-core>=2.0.0

# Privacy & Masking Pipeline
spacy>=3.7.2
https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-3.7.1/en_core_web_lg-3.7.1-py3-none-any.whl
presidio-analyzer>=2.2.355
pyahocorasick>=2.1.0

# Vector Database (Pinecone v3+)
pinecone>=5.0.0

# Guardrails
nemoguardrails>=0.11.0

# Code Quality & Testing
pytest>=8.3.0
pytest-asyncio>=0.23.8
ruff>=0.5.0
mypy>=1.11.0
```

---

## 4. Recommended `backend/Dockerfile` Fix

```dockerfile
FROM python:3.12-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim as runtime

WORKDIR /app

# Install runtime C-libraries required by Docling, OCR, and PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.12/site-packages:$PYTHONPATH

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```
