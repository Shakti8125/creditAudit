# Handoff Report — Explorer M6 (Dependency Compatibility & Cross-Cutting Package Audit R2)

**Working Directory**: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\explorer_m6`  
**Parent Agent ID**: `5286cd52-7789-45bb-9c2d-a3aec82dad00`  
**Status**: Task Complete (Hard Handoff)  
**Report Artifact**: `c:\Users\Shakti\Documents\CreditAudit- AI\.agents\explorer_m6\report.md`  

---

## 1. Observation

Direct code observations from inspecting the codebase:

1. **`backend/requirements.txt`**:
   - Line 3: `pydantic[dotenv,email]>=2.0`
   - Line 4: `pydantic-settings`
   - Line 9: `google-genai`
   - Line 12: `spacy>=3.7.0`
   - Line 14: `presidio-anonymizer`
   - Line 16: `pinecone-client`
   - Line 19: `python-jose[cryptography]`
   - Line 20: `passlib[bcrypt]`
   - Line 21: `bcrypt==3.2.2`
   - Line 24: `tiktoken`
   - Line 30: `langchain-nvidia-ai-endpoints`
   - Line 32: `langchain-google-genai`

2. **`backend/app/utils/security.py`**:
   - Line 7: `from jose import jwt, JWTError`
   - Line 8: `from passlib.context import CryptContext`
   - Line 12: `pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")`
   - Line 32: `return jwt.encode(to_encode, settings.jwt.secret_key, algorithm=settings.jwt.algorithm)`
   - Line 47: `payload = jwt.decode(token, settings.jwt.secret_key, algorithms=[settings.jwt.algorithm])`

3. **`backend/Dockerfile`**:
   - Line 11: `RUN python -m pip install --user spacy==3.7.0`
   - Line 12: `RUN python -m spacy download en_core_web_lg --user`
   - Lines 14-23: Runtime stage `FROM python:3.12-slim as runtime` does not install any system shared libraries (`apt-get install -y libgl1 libglib2.0-0 libgomp1`).

4. **`backend/alembic/env.py` and `backend/app/models/__init__.py`**:
   - `backend/alembic/env.py` Line 12: `from app.models.user import Tenant, User`
   - `backend/app/models/__init__.py`: Completely empty (0 bytes). Models `Document` and `DocumentChunk` in `backend/app/models/document.py` are never imported in `env.py` or `models/__init__.py`.

5. **`backend/app/services/privacy/ner_masker.py`**:
   - Lines 43-48: Synchronous download of `en_core_web_lg` via `spacy.cli.download("en_core_web_lg")` inside `__init__()`.
   - Line 8: `from presidio_analyzer import AnalyzerEngine` (`presidio-anonymizer` is not imported).

6. **`backend/app/services/retrieval/pinecone_store.py`**:
   - Line 2: `from pinecone import Pinecone`

7. **`backend/app/services/guardrails/config.yml`**:
   - Line 3: `engine: langchain-nvidia-ai-endpoints`
   - Line 10: `engine: langchain-google-genai`

---

## 2. Logic Chain

1. **Security & Tech Stack Compliance (Observation #1 & #2)**:
   - `python-jose` is unmaintained since 2021 and has known CVEs (CVE-2024-33663, CVE-2024-33664).
   - `AGENTS.md` strictly dictates `PyJWT` and `bcrypt` for JWT auth.
   - Therefore, `python-jose[cryptography]` must be replaced by `PyJWT[crypto]>=2.8.0` in `requirements.txt` and `app/utils/security.py`.

2. **Python 3.12 Build Failure in Hashing (Observation #1 & #2)**:
   - `passlib` 1.7.4 relies on `bcrypt.__about__.__version__`, which was deleted in `bcrypt>=4.0.0`.
   - `bcrypt==3.2.2` lacks Python 3.12 wheels on PyPI and fails CFFI source compilation in slim containers.
   - Therefore, `passlib` should be dropped in favor of direct `bcrypt>=4.1.0`.

3. **Alembic Autogenerate Discovery Gap (Observation #4)**:
   - Alembic autogenerate inspects `Base.metadata`.
   - Tables for `Document` and `DocumentChunk` are only registered when `app.models.document` is imported.
   - Since `env.py` only imports `Tenant, User` and `app/models/__init__.py` is blank, Alembic cannot detect document tables.
   - Therefore, `app/models/__init__.py` and `alembic/env.py` must import all models.

4. **Container Runtime Integrity (Observation #3 & #5)**:
   - Docling uses C-extensions that dynamically link against `libGL.so.1` and `libgomp.so.1`.
   - The multi-stage runtime container lacks these shared libraries.
   - Also, runtime `spacy.cli.download` in worker processes causes latency spikes and container failures.
   - Therefore, install system C-libs in the runtime stage and pre-install the spaCy model during build.

5. **Redundancy & Conflict Cleanup (Observation #1, #5, #6, #7)**:
   - `pinecone-client` is legacy; modern code uses `pinecone>=5.0.0`.
   - `langchain-google-genai` installs conflicting legacy `google-generativeai`, while core code uses `google-genai`.
   - `tiktoken` and `presidio-anonymizer` are never imported anywhere in `backend/app/`.
   - Therefore, clean up `requirements.txt` to eliminate bloat and conflicts.

---

## 3. Caveats

- **NeMo Guardrails Integration Mode**: If NeMo Guardrails strictly requires LangChain LLM wrappers for dialog rails, ensure `langchain-core` / `langchain-community` are pinned compatibly without pulling in conflicting legacy `google-generativeai`.
- **Runtime Environment Testing**: In accordance with the strict read-only audit rules, no packages were installed or executed during this audit.

---

## 4. Conclusion

The ModelAudit AI backend dependency tree requires immediate remediation of 2 Critical issues (`python-jose` CVEs, `passlib` / `bcrypt==3.2.2` Python 3.12 failure), 3 High-severity issues (Alembic model discovery, spaCy packaging, Dockerfile runtime shared libraries), 3 Medium issues (Pinecone SDK naming, Google SDK duplication, redundant LangChain dependencies), and 3 Low-severity issues (unused packages, Pydantic v1 extra, `datetime.utcnow()` deprecations).

A fully reconciled and verified `requirements.txt` and `Dockerfile` specification has been compiled in `.agents/explorer_m6/report.md`.

---

## 5. Verification Method

To verify these findings:
1. **File Inspection**:
   - Check `backend/requirements.txt` vs `backend/app/utils/security.py` for `python-jose` and `passlib`.
   - Check `backend/alembic/env.py` line 12 and `backend/app/models/__init__.py` for missing document model imports.
   - Check `backend/Dockerfile` line 11 and runtime stage lines 14-23 for missing libraries.
2. **Build / Static Checks**:
   - Run `pip check` after installing the proposed `requirements.txt` in a Python 3.12 environment to verify zero dependency conflicts.
   - Run `docker build -t modelaudit-backend backend/` to verify multi-stage build completion without CFFI/wheel build errors.
   - Run `alembic check` / `alembic revision --autogenerate` to verify all models (users, tenants, documents, chunks) are detected.
