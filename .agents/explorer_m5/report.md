# ModelAudit AI Backend Code Audit — Explorer M5 Report
**Scope**: Configuration, Database, Schemas, Models, Utilities & Alembic
**Date**: 2026-08-28
**Auditor**: Explorer M5
**Parent ID**: 5286cd52-7789-45bb-9c2d-a3aec82dad00

---

## 1. Executive Summary

| Severity | Count | Primary Impact Areas |
| :--- | :---: | :--- |
| **Critical** | 2 | Asymmetric RS256 JWT key configuration mismatch; Alembic env.py missing document model metadata registration |
| **High** | 4 | Missing multi-tenancy indexes on 	enant_id/document_id; Empty __init__.py package exports breaking metadata discovery; Missing chunk_count attribute causing Pydantic validation failure |
| **Medium** | 9 | Legacy SQLAlchemy 1.4 declarative_base(); Pydantic v2 missing model_config = ConfigDict(...) across multiple schemas; Python 3.12 datetime.utcnow deprecations; Missing reverse ORM relationships; SSE streaming missing buffering headers |
| **Low** | 5 | Unused imports; Legacy 	yping imports vs Python 3.12 syntax; Missing Google-style docstrings on config classes; Uncaught/unlogged exceptions |
| **Total** | **20** | |

---

## 2. Detailed Findings by File

### 2.1 Configuration (ackend/app/config.py)

#### Finding M5-CFG-01
- **File**: ackend/app/config.py
- **Line**: 46-47 (also 28-32, 73-74)
- **Severity**: Critical
- **Category**: Security issues / Incorrect API usage vs. latest library docs
- **Description**: Settings defines jwt_algorithm: str = "RS256" and jwt_secret_key: str = "" as a single symmetric secret string. RS256 is an asymmetric algorithm (RSA Signature with SHA-256) which requires an RSA Private Key in PEM format for signing (jwt.encode) and an RSA Public Key in PEM format for verification (jwt.decode). Providing a symmetric secret key string to jose.jwt.encode or jwt.decode with algorithm RS256 will crash at runtime with JWTError: Key must be in PEM format or TypeError. Furthermore, AGENTS.md explicitly specifies "Auth: Custom RS256 JWT (PyJWT, bcrypt)".
- **Correct Pattern / Fix**:
  Either configure separate private and public key paths/PEM strings:
  `python
  class JwtConfig:
      def __init__(self, private_key: str, public_key: str, algorithm: str = "RS256"):
          self.private_key = private_key
          self.public_key = public_key
          self.algorithm = algorithm

  class Settings(BaseSettings):
      jwt_private_key: str = ""
      jwt_public_key: str = ""
      jwt_algorithm: str = "RS256"

      @property
      def jwt(self) -> JwtConfig:
          return JwtConfig(self.jwt_private_key, self.jwt_public_key, self.jwt_algorithm)
  `
  Or, if symmetric HMAC signing is intended during local development, change default to jwt_algorithm: str = "HS256".

#### Finding M5-CFG-02
- **File**: ackend/app/config.py
- **Line**: 5-36
- **Severity**: Low
- **Category**: Type annotation correctness / Code quality
- **Description**: Helper classes DatabaseConfig, RedisConfig, PineconeConfig, NvidiaConfig, GeminiConfig, JwtConfig, and RateLimitConfig lack Google-style docstrings (violating project code convention 6) and are implemented as plain Python classes without Pydantic model validation.
- **Correct Pattern / Fix**:
  Add class-level docstrings and consider using Pydantic BaseModel or dataclass for typed nested configs:
  `python
  class DatabaseConfig(BaseModel):
      """Database connection configuration."""
      url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/modelaudit"
  `

---

### 2.2 Database Layer (ackend/app/db/database.py & ackend/app/db/__init__.py)

#### Finding M5-DB-01
- **File**: ackend/app/db/database.py
- **Line**: 6, 10
- **Severity**: Medium
- **Category**: Incorrect API usage vs. latest library docs (SQLAlchemy 2.0 Compliance)
- **Description**: Base = declarative_base() uses the legacy SQLAlchemy 1.4 syntax. In SQLAlchemy 2.0+, DeclarativeBase subclassing is the standard pattern required for full type checking, Mapped annotation parsing, and static analysis.
- **Correct Pattern / Fix**:
  `python
  from sqlalchemy.orm import DeclarativeBase

  class Base(DeclarativeBase):
      """Base class for all SQLAlchemy declarative models."""
      pass
  `

#### Finding M5-DB-02
- **File**: ackend/app/db/database.py
- **Line**: 12-17
- **Severity**: Medium
- **Category**: Incorrect API usage vs. latest library docs / Database reliability
- **Description**: create_async_engine lacks pool_pre_ping=True. In cloud/containerized environments (such as AWS RDS PostgreSQL), database connections idle out or are closed by the server, causing stale connection drops (InterfaceError: connection is closed) unless pool_pre_ping=True is enabled.
- **Correct Pattern / Fix**:
  `python
  engine = create_async_engine(
      settings.database.url,
      pool_size=5,
      max_overflow=10,
      pool_pre_ping=True,
      echo=False,
  )
  `

#### Finding M5-DB-03
- **File**: ackend/app/db/__init__.py
- **Line**: 1
- **Severity**: Low
- **Category**: Broken imports and missing dependencies / Module exports
- **Description**: ackend/app/db/__init__.py is completely empty (0 bytes). It fails to export Base, engine, sync_session_maker, and get_db.
- **Correct Pattern / Fix**:
  `python
  from app.db.database import Base, engine, async_session_maker, get_db

  __all__ = ["Base", "engine", "async_session_maker", "get_db"]
  `

---

### 2.3 ORM Models (ackend/app/models/user.py, document.py, __init__.py)

#### Finding M5-MOD-01
- **File**: ackend/app/models/user.py
- **Line**: 43
- **Severity**: High
- **Category**: Multi-Tenancy & Performance Bug
- **Description**: In model User, 	enant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False) is missing index=True. Every user lookup in multi-tenant isolation filters by 	enant_id, and without an index on this foreign key, database queries will result in full-table scans.
- **Correct Pattern / Fix**:
  `python
  tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
  `

#### Finding M5-MOD-02
- **File**: ackend/app/models/document.py
- **Line**: 24, 25, 43
- **Severity**: High
- **Category**: Multi-Tenancy & Performance Bug
- **Description**: Foreign key columns Document.tenant_id, Document.user_id, and DocumentChunk.document_id are missing index=True. Document listing (select(Document).filter(Document.tenant_id == ...)), user document filtering, and chunk loading (select(DocumentChunk).filter(DocumentChunk.document_id == ...)) will cause unindexed sequential table scans.
- **Correct Pattern / Fix**:
  `python
  # In Document:
  tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
  user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)

  # In DocumentChunk:
  document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True, nullable=False)
  `

#### Finding M5-MOD-03
- **File**: ackend/app/models/user.py (lines 33, 48) & ackend/app/models/document.py (line 29)
- **Line**: user.py: 33, 48; document.py: 29
- **Severity**: Medium
- **Category**: Deprecated API / Python 3.12 compatibility
- **Description**: default=datetime.utcnow uses Python's deprecated datetime.utcnow() method (deprecated in Python 3.12 with DeprecationWarning). In addition, python-side defaults without database server_default mean records created outside SQLAlchemy ORM will have NULL timestamps, and timezone information is omitted.
- **Correct Pattern / Fix**:
  `python
  from datetime import datetime, timezone
  from sqlalchemy.sql import func
  from sqlalchemy import DateTime

  created_at: Mapped[datetime] = mapped_column(
      DateTime(timezone=True),
      default=lambda: datetime.now(timezone.utc),
      server_default=func.now(),
      nullable=False,
  )
  `

#### Finding M5-MOD-04
- **File**: ackend/app/models/user.py (line 50) & ackend/app/models/document.py (line 35)
- **Line**: user.py: 50; document.py: 35
- **Severity**: Medium
- **Category**: Type annotation correctness / Relationship configuration
- **Description**: Missing bidirectional ORM relationships:
  - User does not define documents: Mapped[list[Document]] = relationship("Document", back_populates="user", cascade="all, delete-orphan")
  - Document does not define user: Mapped[User] = relationship("User", back_populates="documents") or 	enant: Mapped[Tenant] = relationship("Tenant")
- **Correct Pattern / Fix**:
  Define explicit relationships in User and Document with ack_populates for bidirectional navigation and referential integrity.

#### Finding M5-MOD-05
- **File**: ackend/app/models/__init__.py
- **Line**: 1
- **Severity**: High
- **Category**: Broken imports and missing dependencies / Model discovery
- **Description**: ackend/app/models/__init__.py is empty (0 bytes). As a result, importing pp.models does not import or register Tenant, User, Document, DocumentChunk, DocumentStatus, RoleEnum, or TierEnum into Base.metadata.
- **Correct Pattern / Fix**:
  `python
  from app.models.user import Tenant, User, RoleEnum, TierEnum
  from app.models.document import Document, DocumentChunk, DocumentStatus

  __all__ = [
      "Tenant",
      "User",
      "RoleEnum",
      "TierEnum",
      "Document",
      "DocumentChunk",
      "DocumentStatus",
  ]
  `

---

### 2.4 Alembic Migration Configuration (ackend/alembic/env.py)

#### Finding M5-ALM-01
- **File**: ackend/alembic/env.py
- **Line**: 12, 19
- **Severity**: Critical
- **Category**: Database Schema / Migration Bug
- **Description**: lembic/env.py only imports Tenant and User (rom app.models.user import Tenant, User). It does NOT import Document and DocumentChunk from pp.models.document. Because pp/models/__init__.py is also empty, 	arget_metadata = Base.metadata does not contain table metadata for documents and document_chunks. Running lembic revision --autogenerate will generate migrations that DROP documents / document_chunks or fail to create them.
- **Correct Pattern / Fix**:
  `python
  from app.db.database import Base
  import app.models  # Imports all models and registers with Base.metadata
  # Or:
  from app.models.user import Tenant, User
  from app.models.document import Document, DocumentChunk

  target_metadata = Base.metadata
  `

---

### 2.5 Pydantic Schemas (ackend/app/schemas/)

#### Finding M5-SCH-01
- **File**: ackend/app/schemas/auth.py
- **Line**: 6-30
- **Severity**: Medium
- **Category**: Pydantic v2 compliance (R3)
- **Description**: Schemas in uth.py (RegisterRequest, LoginRequest, RefreshRequest, TokenResponse, TokenPayload) do not specify model_config = ConfigDict(...), violating project code convention 4 ("All request/response schemas use Pydantic BaseModel with model_config = ConfigDict(...)").
- **Correct Pattern / Fix**:
  `python
  from pydantic import BaseModel, ConfigDict, EmailStr

  class RegisterRequest(BaseModel):
      model_config = ConfigDict(str_strip_whitespace=True)
      email: EmailStr
      password: str
      tenant_name: str

  class TokenResponse(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      access_token: str
      refresh_token: str
      token_type: str = "Bearer"
      expires_in: int = 3600

  class TokenPayload(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      sub: uuid.UUID
      tenant_id: uuid.UUID | None = None
      role: str | None = None
      exp: int
      type: str
  `

#### Finding M5-SCH-02
- **File**: ackend/app/schemas/compare.py & ackend/app/schemas/gap_analysis.py
- **Line**: compare.py: 12; gap_analysis.py: 6
- **Severity**: Medium
- **Category**: Pydantic v2 compliance (R3)
- **Description**: ComparisonDifference in compare.py and ComplianceGap in gap_analysis.py are missing model_config = ConfigDict(from_attributes=True).
- **Correct Pattern / Fix**:
  Add model_config = ConfigDict(from_attributes=True) to ComparisonDifference and ComplianceGap.

#### Finding M5-SCH-03
- **File**: ackend/app/schemas/document.py
- **Line**: 23-32, 34-35
- **Severity**: High
- **Category**: Schema / Model Mismatch & Pydantic v2 compliance
- **Description**:
  1. DocumentMetadata defines chunk_count: int with model_config = ConfigDict(from_attributes=True). However, the SQLAlchemy Document model in models/document.py does not possess a chunk_count attribute or column (it only has a chunks relationship). Calling DocumentMetadata.model_validate(db_doc) raises a runtime ValidationError: Field required [type=missing, input_value=..., input_type=Document].
  2. DocumentListResponse is missing model_config = ConfigDict(from_attributes=True).
- **Correct Pattern / Fix**:
  Add a hybrid property or @property on Document OR default chunk_count: int = 0 in schema:
  `python
  # In backend/app/models/document.py:
  @property
  def chunk_count(self) -> int:
      return len(self.chunks) if self.chunks is not None else 0

  # In backend/app/schemas/document.py:
  class DocumentMetadata(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      id: uuid.UUID
      filename: str
      file_type: str
      upload_time: datetime
      status: DocumentStatus
      chunk_count: int = 0

  class DocumentListResponse(BaseModel):
      model_config = ConfigDict(from_attributes=True)
      documents: list[DocumentMetadata]
  `

#### Finding M5-SCH-04
- **File**: ackend/app/schemas/retrieval.py
- **Line**: 6-35
- **Severity**: Medium
- **Category**: Pydantic v2 compliance (R3)
- **Description**: None of the models in etrieval.py (ChunkData, VectorResult, RetrievalCandidate, Citation, RetrievalResult) have model_config = ConfigDict(from_attributes=True) defined, despite importing ConfigDict on line 3. Also, line 4 has an unused import import uuid.
- **Correct Pattern / Fix**:
  Add model_config = ConfigDict(from_attributes=True) to each model and remove unused import uuid.

#### Finding M5-SCH-05
- **File**: ackend/app/schemas/__init__.py
- **Line**: 1
- **Severity**: Low
- **Category**: Module exports / Code structure
- **Description**: ackend/app/schemas/__init__.py is empty (0 bytes), requiring deep nested imports across modules instead of unified package imports.
- **Correct Pattern / Fix**:
  Export all schemas from ackend/app/schemas/__init__.py.

---

### 2.6 Security & Streaming Utilities (ackend/app/utils/)

#### Finding M5-UTL-01
- **File**: ackend/app/utils/security.py
- **Line**: 7, 32, 42, 47
- **Severity**: Critical
- **Category**: Security issues / Library incompatibility
- **Description**:
  1. security.py uses python-jose to encode and decode tokens with settings.jwt.secret_key and algorithm RS256. Passing a string key to jose.jwt.encode(..., algorithm="RS256") fails because RS256 requires an RSA Private Key.
  2. Project tech stack rule in AGENTS.md explicitly specifies: Auth: Custom RS256 JWT (PyJWT, bcrypt). python-jose is used instead of PyJWT.
- **Correct Pattern / Fix**:
  Use jwt (PyJWT) with RS256 private/public key pairs (or HS256 for symmetric key):
  `python
  import jwt
  from datetime import datetime, timezone, timedelta

  def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
      expire = datetime.now(timezone.utc) + timedelta(hours=1)
      to_encode = {
          "sub": str(user_id),
          "tenant_id": str(tenant_id),
          "role": role,
          "exp": expire,
          "type": "access"
      }
      return jwt.encode(to_encode, settings.jwt.private_key, algorithm="RS256")

  def decode_token(token: str) -> dict[str, Any]:
      try:
          return jwt.decode(token, settings.jwt.public_key, algorithms=["RS256"])
      except jwt.PyJWTError as e:
          raise ValueError("Invalid token") from e
  `

#### Finding M5-UTL-02
- **File**: ackend/app/utils/security.py
- **Line**: 24, 36
- **Severity**: Medium
- **Category**: Deprecated API / Python 3.12 compatibility
- **Description**: datetime.utcnow() is deprecated in Python 3.12.
- **Correct Pattern / Fix**:
  Replace datetime.utcnow() with datetime.now(timezone.utc).

#### Finding M5-UTL-03
- **File**: ackend/app/utils/streaming.py
- **Line**: 1, 24
- **Severity**: Medium
- **Category**: Missing HTTP Headers / Reverse Proxy Compatibility
- **Description**:
  1. Missing rom __future__ import annotations (Code Convention 3).
  2. StreamingResponse on line 24 does not provide streaming headers (Cache-Control: no-cache, Connection: keep-alive, X-Accel-Buffering: no). In production deployments behind Nginx or AWS ALB, without X-Accel-Buffering: no the response stream will be buffered and sent all at once when completed, breaking the real-time SSE streaming user experience.
- **Correct Pattern / Fix**:
  `python
  from __future__ import annotations
  import json
  import logging
  from typing import AsyncIterator, Any
  from fastapi.responses import StreamingResponse

  logger = logging.getLogger(__name__)

  def sse_stream(generator: AsyncIterator[str | dict[str, Any]]) -> StreamingResponse:
      """Wraps an async generator into an SSE StreamingResponse."""
      async def event_generator() -> AsyncIterator[str]:
          try:
              async for item in generator:
                  if isinstance(item, dict):
                      yield f"data: {json.dumps(item)}\n\n"
                  else:
                      yield f"data: {json.dumps({'type': 'token', 'content': str(item)})}\n\n"
              yield f"data: {json.dumps({'type': 'done'})}\n\n"
          except Exception as e:
              logger.error("SSE stream error: %s", str(e), exc_info=True)
              yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

      return StreamingResponse(
          event_generator(),
          media_type="text/event-stream",
          headers={
              "Cache-Control": "no-cache",
              "Connection": "keep-alive",
              "X-Accel-Buffering": "no",
          }
      )
  `

#### Finding M5-UTL-04
- **File**: ackend/app/utils/__init__.py
- **Line**: 1
- **Severity**: Low
- **Category**: Module exports
- **Description**: ackend/app/utils/__init__.py is empty (0 bytes).
- **Correct Pattern / Fix**:
  Export security and streaming functions in __init__.py.

---

## 3. Dependency Compatibility Issues (ackend/requirements.txt)

#### Finding M5-DEP-01: Passlib + Bcrypt 4.x Incompatibility
- **Severity**: High
- **Category**: Dependency Compatibility (R2)
- **Description**: ackend/requirements.txt contains:
  `
  passlib[bcrypt]
  bcrypt==3.2.2
  `
  passlib (version 1.7.4, last released in 2020) relies on internal crypt.__about__.__version__ which was removed in crypt>=4.0.0. Installing modern crypt alongside passlib causes immediate crashes when CryptContext is initialized. While pinning crypt==3.2.2 temporarily avoids the crash, passlib is unmaintained and crypt 3.2.2 contains known security vulnerabilities and lacks wheels for newer Python 3.12 builds.
- **Correct Pattern / Fix**:
  Migrate from passlib to direct crypt or pwdlib[bcrypt] / rgon2-cffi. In equirements.txt, replace passlib[bcrypt] and crypt==3.2.2 with crypt>=4.1.0 or pwdlib[bcrypt].

#### Finding M5-DEP-02: Deprecated pydantic[dotenv]
- **Severity**: Low
- **Category**: Dependency Compatibility (R2)
- **Description**: equirements.txt specifies pydantic[dotenv,email]>=2.0. In Pydantic v2, dotenv support was separated into pydantic-settings. The [dotenv] extra on pydantic is deprecated and a no-op.
- **Correct Pattern / Fix**:
  Change to pydantic[email]>=2.0 and pydantic-settings>=2.0.0.

#### Finding M5-DEP-03: Redundant LangChain Dependencies
- **Severity**: Medium
- **Category**: Dependency Compatibility (R2)
- **Description**: equirements.txt includes:
  `
  langchain-nvidia-ai-endpoints
  langchain-google-genai
  `
  alongside native openai>=1.40.0 and google-genai. Per project architecture, LLM interactions use native NVIDIA NIM (via openai) and Google Gemini (via google-genai). The langchain-* packages are unused, introduce dozens of transitive dependencies, and create potential version conflicts.
- **Correct Pattern / Fix**:
  Remove langchain-nvidia-ai-endpoints and langchain-google-genai from equirements.txt.

#### Finding M5-DEP-04: PyJWT vs Python-Jose Mismatch
- **Severity**: High
- **Category**: Dependency Compatibility (R2)
- **Description**: equirements.txt includes python-jose[cryptography], whereas AGENTS.md mandates PyJWT for RS256 JWT tokens. python-jose has unmaintained dependencies (ecdsa, sa) with known CVEs.
- **Correct Pattern / Fix**:
  Replace python-jose[cryptography] with pyjwt[crypto]>=2.8.0 in equirements.txt.

---

## 4. Verification & Recommendations

| Item | Verification Command / Method |
| :--- | :--- |
| Pydantic v2 ConfigDict | Inspect all schema classes for model_config = ConfigDict(...) and verify no class Config: or @validator remain. |
| SQLAlchemy 2.0 Models | Verify DeclarativeBase subclassing in database.py and Mapped[] / mapped_column() in all models. |
| Multi-Tenancy Indexing | Verify index=True on 	enant_id across User, Document, and document_id on DocumentChunk. |
| Alembic Autogenerate | Run lembic check or autogenerate dry-run to ensure 	arget_metadata detects both users, 	enants, documents, and document_chunks. |
| JWT RS256 Auth | Test token creation and verification with RSA key pair and verify no symmetric key string is passed to RS256. |
