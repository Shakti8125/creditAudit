# ModelAudit AI — Code Audit Report: Retrieval Pipeline & Analytics Engine

**Audit Date**: 2026-08-28  
**Auditor**: Explorer M3 (Teamwork Read-Only Code Auditor)  
**Scope**: Retrieval Pipeline (`backend/app/services/retrieval/`) and Analytics Engine (`backend/app/services/analytics/`)  
**Status**: Completed  

---

## 1. Executive Summary

A comprehensive static analysis of the ModelAudit AI Retrieval Pipeline and Analytics Engine was conducted. The audit covered all 12 target files in scope:
- `backend/app/services/retrieval/__init__.py`
- `backend/app/services/retrieval/bm25.py`
- `backend/app/services/retrieval/dense_retriever.py`
- `backend/app/services/retrieval/hybrid_retriever.py`
- `backend/app/services/retrieval/pinecone_store.py`
- `backend/app/services/retrieval/reranker.py`
- `backend/app/services/retrieval/rrf_fusion.py`
- `backend/app/services/analytics/__init__.py`
- `backend/app/services/analytics/ews_detector.py`
- `backend/app/services/analytics/model_metrics_extractor.py`
- `backend/app/services/analytics/policy_checker.py`
- `backend/app/services/__init__.py`

### Bug Count Summary by Severity

| Severity | Count | Key Impact Areas |
| :--- | :---: | :--- |
| **Critical** | 4 | Multi-tenancy isolation leak in DB retrieval, crash on `PineconeStore()` instantiation in API routes, unimplemented `upsert_chunks()` stub, truncation of comma-formatted financial numbers |
| **High** | 8 | Pinecone `None` crash on empty index stats, blocking sync I/O in async retrieval loops, BM25 state accumulation on re-fit, in-place candidate mutation in reranker, total candidate loss on reranker error, regex parsing anomalies, false-positive EWS alarms, deprecated `pinecone-client` SDK |
| **Medium** | 10 | Bare exception swallowing in Pinecone queries, naive tokenization breaking on punctuation, ZeroDivisionError in BM25, unnormalized RRF scores, markdown table parsing failures, missing basis points handling, contradictory AUC threshold logic, missing calibration checks |
| **Low** | 7 | Missing `from __future__ import annotations`, missing Google-style docstrings, missing type annotations on helper functions, empty package `__init__.py` exports |
| **Total** | **29** | Full breakdown detailed below |

---

## 2. Per-File Detailed Findings

---

### Module: Retrieval Pipeline (`backend/app/services/retrieval/`)

#### 1. `backend/app/services/retrieval/pinecone_store.py`

##### Finding RET-01 (Critical)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 7–9
- **Severity**: Critical
- **Category**: Incorrect API usage vs. latest library docs / Broken API contract
- **Description**: `PineconeStore.__init__` requires two mandatory positional arguments (`api_key: str, index_name: str`) without default values or settings fallback:
  ```python
  class PineconeStore:
      def __init__(self, api_key: str, index_name: str):
          self.pc = Pinecone(api_key=api_key)
          self.index = self.pc.Index(index_name)
  ```
  However, all consuming API route handlers (`backend/app/api/query.py:23`, `backend/app/api/regulatory.py:21`) instantiate it with no arguments: `pinecone_store = PineconeStore()`. When an API request hits `/query` or `/regulatory/search`, Python immediately raises `TypeError: PineconeStore.__init__() missing 2 required positional arguments: 'api_key' and 'index_name'`, causing an unhandled 500 server crash on every retrieval request.
- **Correct Pattern / Fix**: Provide default parameters that automatically pull from `app.config.settings`:
  ```python
  from __future__ import annotations
  from app.config import settings
  from pinecone import Pinecone

  class PineconeStore:
      def __init__(self, api_key: str | None = None, index_name: str | None = None) -> None:
          self.api_key = api_key or settings.pinecone.api_key
          self.index_name = index_name or settings.pinecone.index_name
          self.pc = Pinecone(api_key=self.api_key)
          self.index = self.pc.Index(self.index_name)
  ```

---

##### Finding RET-02 (Critical)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 11–21
- **Severity**: Critical
- **Category**: Incomplete implementation / Broken API
- **Description**: `upsert_chunks()` is an unimplemented stub with a `pass` statement and developer scratchpad comments:
  ```python
  def upsert_chunks(self, chunks: List[ChunkData], namespace: str):
      vectors = []
      # Expects that chunks are actually already embedded, wait.
      # The schema in SKILL says: upsert_chunks(chunks: list[ChunkData], namespace: str)
      ...
      pass
  ```
  Calling `upsert_chunks()` silently does nothing. Any workflow relying on this method to index chunks into Pinecone fails without warning.
- **Correct Pattern / Fix**: Complete the method to accept chunk embeddings and delegate to batch upsert:
  ```python
  async def upsert_chunks(
      self, 
      chunks: list[ChunkData], 
      embeddings: list[list[float]], 
      namespace: str
  ) -> None:
      """Embed and upsert document chunks into Pinecone."""
      ids = [str(uuid.uuid4()) for _ in chunks]
      await self.upsert_vectors(ids=ids, vectors=embeddings, chunks=chunks, namespace=namespace)
  ```

---

##### Finding RET-03 (High)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 65–66
- **Severity**: High
- **Category**: Incorrect API usage vs. latest library docs / Runtime crash
- **Description**: In Pinecone Python SDK v3+, `self.index.describe_index_stats()` returns an `IndexDescription` where the `namespaces` field is `None` (or empty dictionary) when an index contains no vectors/namespaces. Calling `stats.namespaces.keys()` raises `AttributeError: 'NoneType' object has no attribute 'keys'`, crashing namespace discovery.
- **Correct Pattern / Fix**: Safely guard against `None`:
  ```python
  def list_namespaces(self, prefix: str | None = None) -> list[str]:
      stats = self.index.describe_index_stats()
      namespaces_dict = getattr(stats, "namespaces", None) or {}
      namespaces = list(namespaces_dict.keys())
      if prefix:
          return [ns for ns in namespaces if ns.startswith(prefix)]
      return namespaces
  ```

---

##### Finding RET-04 (Medium)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 57–58
- **Severity**: Medium
- **Category**: Error handling / Silent exception swallowing
- **Description**: In `query()`, `except Exception:` catches all errors unconditionally and silently returns `[]`:
  ```python
  except Exception:
      return []
  ```
  This violates Code Convention 5 ("Never use bare except:. Always catch specific exceptions. Log with logging.getLogger(__name__)"). It silently hides authentication errors, network timeouts, bad index names, and dimension mismatches.
- **Correct Pattern / Fix**:
  ```python
  import logging
  logger = logging.getLogger(__name__)

  def query(self, embedding: list[float], namespace: str, top_k: int = 20) -> list[VectorResult]:
      try:
          response = self.index.query(
              namespace=namespace,
              vector=embedding,
              top_k=top_k,
              include_metadata=True
          )
          return [
              VectorResult(
                  id=match.id,
                  score=match.score,
                  metadata=match.metadata or {}
              )
              for match in response.matches
          ]
      except Exception as e:
          logger.error(f"Failed to query Pinecone namespace '{namespace}': {e}", exc_info=True)
          return []
  ```

---

##### Finding RET-05 (Medium)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 11, 23, 40, 60, 63
- **Severity**: Medium
- **Category**: Async/await correctness
- **Description**: All methods in `PineconeStore` (`upsert_vectors`, `query`, `delete_namespace`, `list_namespaces`) are synchronous `def` doing blocking network I/O over HTTP/gRPC. Under concurrent load in FastAPI, executing blocking I/O calls blocks the event loop and starves other coroutines, violating Code Convention 2 ("Async-first: All service methods, API handlers, and DB operations MUST be async").
- **Correct Pattern / Fix**: Wrap blocking Pinecone calls in `async def` using `asyncio.to_thread`:
  ```python
  import asyncio

  async def query(self, embedding: list[float], namespace: str, top_k: int = 20) -> list[VectorResult]:
      return await asyncio.to_thread(self._query_sync, embedding, namespace, top_k)
  ```

---

##### Finding RET-06 (Low)
- **File**: `backend/app/services/retrieval/pinecone_store.py`
- **Line**: 1–70
- **Severity**: Low
- **Category**: Type annotation correctness & Code conventions
- **Description**: Missing `from __future__ import annotations`, missing return type annotations (`-> None` on `upsert_vectors`, `delete_namespace`), and missing Google-style docstrings (violates Code Conventions 3 and 6).
- **Correct Pattern / Fix**: Add `from __future__ import annotations`, return types, and Google-style docstrings to all methods.

---

#### 2. `backend/app/services/retrieval/hybrid_retriever.py`

##### Finding RET-07 (Critical)
- **File**: `backend/app/services/retrieval/hybrid_retriever.py`
- **Line**: 26–30
- **Severity**: Critical
- **Category**: Security issues / Multi-tenancy isolation breach
- **Description**: In `_fetch_chunks_for_document`, the database query filters only by `document_id`:
  ```python
  async def _fetch_chunks_for_document(self, db: AsyncSession, document_id: uuid.UUID) -> List[DocumentChunk]:
      result = await db.execute(
          select(DocumentChunk).where(DocumentChunk.document_id == document_id)
      )
      return list(result.scalars().all())
  ```
  This directly violates the core Multi-Tenancy Rule: *"Every database query MUST filter by tenant_id from the JWT"*. If an authenticated user belonging to `tenant_A` passes a `document_id` belonging to `tenant_B`, the backend executes BM25 search over `tenant_B`'s private document chunks and returns them to the caller.
- **Correct Pattern / Fix**: Accept `tenant_id: uuid.UUID` in `_fetch_chunks_for_document` and join with `Document` to enforce tenant isolation:
  ```python
  from app.models.document import Document, DocumentChunk

  async def _fetch_chunks_for_document(
      self, 
      db: AsyncSession, 
      document_id: uuid.UUID, 
      tenant_id: uuid.UUID
  ) -> list[DocumentChunk]:
      """Fetch chunks for a specific document ensuring strict tenant isolation."""
      result = await db.execute(
          select(DocumentChunk)
          .join(Document, DocumentChunk.document_id == Document.id)
          .where(
              DocumentChunk.document_id == document_id,
              Document.tenant_id == tenant_id
          )
          .order_by(DocumentChunk.chunk_index)
      )
      return list(result.scalars().all())
  ```

---

##### Finding RET-08 (Medium)
- **File**: `backend/app/services/retrieval/hybrid_retriever.py`
- **Line**: 54–73
- **Severity**: Medium
- **Category**: Retrieval logic / Incomplete hybrid search
- **Description**: BM25 keyword index is built purely in-memory from user document chunks (`db_chunks`) when `document_id` is supplied. However, the regulatory corpus (`cbuae-manuals`) is never included in the BM25 index. When a user runs a pure regulatory query via `/regulatory/search` (`document_id=None`), `bm25_candidates` is empty and the pipeline falls back to pure dense retrieval instead of true hybrid search.
- **Correct Pattern / Fix**: Build or query a persistent BM25 index for CBUAE regulatory guidelines, or index regulatory chunks alongside user document chunks so keyword queries for specific CBUAE MMG article numbers (e.g. *"Article 4.2.1"*) match via BM25.

---

##### Finding RET-09 (Low)
- **File**: `backend/app/services/retrieval/hybrid_retriever.py`
- **Line**: 1–113
- **Severity**: Low
- **Category**: Code conventions & Type annotations
- **Description**: Missing `from __future__ import annotations` and missing Google-style docstrings on class and methods.
- **Correct Pattern / Fix**: Add `from __future__ import annotations` and standard Google-style docstrings.

---

#### 3. `backend/app/services/retrieval/bm25.py`

##### Finding RET-10 (High)
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line**: 21–52
- **Severity**: High
- **Category**: Logic bug / Stateful accumulation across multiple `fit()` calls
- **Description**: In `BM25Okapi.fit(self, corpus: List[str])`, instance variables `self.doc_freqs`, `self.doc_len`, and `self.idf` are not cleared before processing:
  ```python
  def fit(self, corpus: List[str]):
      self.corpus = corpus
      self.corpus_size = len(corpus)
      if self.corpus_size == 0:
          return
      ...
      for document in corpus:
          frequencies = Counter(self._tokenize(document))
          self.doc_freqs.append(frequencies) # Appends to existing list!
          ...
          self.doc_len.append(doc_len)       # Appends to existing list!
  ```
  If `fit()` is invoked more than once on a cached/reused `BM25Okapi` instance, `self.doc_freqs` and `self.doc_len` grow indefinitely. `self.corpus_size` becomes `len(corpus)`, so `score()` iterates `range(self.corpus_size)`, which indexes into stale frequencies from the previous run instead of the current corpus.
- **Correct Pattern / Fix**: Reset all internal state collections at the beginning of `fit()`:
  ```python
  def fit(self, corpus: list[str]) -> None:
      """Fit the BM25 model on the provided text corpus."""
      self.corpus = corpus
      self.corpus_size = len(corpus)
      self.doc_freqs = []
      self.doc_len = []
      self.idf = {}
      if self.corpus_size == 0:
          self.avgdl = 0.0
          return
      ...
  ```

---

##### Finding RET-11 (Medium)
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line**: 16–19
- **Severity**: Medium
- **Category**: Tokenization / Retrieval quality bug
- **Description**: `_tokenize` implements naive whitespace splitting:
  ```python
  def _tokenize(self, text: str) -> List[str]:
      if not text:
          return []
      return text.lower().split()
  ```
  This retains trailing/leading punctuation attached to words (e.g. `"model,"`, `"(auc"`, `"accuracy."`, `"0.75;"`). A search query for `"model"` will fail to match `"model,"` in documents. Furthermore, markdown punctuation and formatting tags pollute vocabulary keys.
- **Correct Pattern / Fix**: Use regex-based tokenization that preserves alphanumeric terms, acronyms, and comma-formatted financial numbers (per Rule 10):
  ```python
  import re

  def _tokenize(self, text: str) -> list[str]:
      """Tokenize text into lowercase terms, preserving numbers and alphanumeric tokens."""
      if not text:
          return []
      return re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b|\b[a-zA-Z0-9_-]+\b", text.lower())
  ```

---

##### Finding RET-12 (Medium)
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line**: 75
- **Severity**: Medium
- **Category**: Potential ZeroDivisionError
- **Description**: In `score()`, the formula calculates `d_len / self.avgdl`:
  ```python
  denominator = f + self.k1 * (1 - self.b + self.b * (d_len / self.avgdl))
  ```
  If a corpus consists of empty strings or non-tokenizable documents, `self.avgdl == 0.0`, resulting in an unhandled `ZeroDivisionError`.
- **Correct Pattern / Fix**:
  ```python
  len_norm = (d_len / self.avgdl) if self.avgdl > 0 else 1.0
  denominator = f + self.k1 * (1 - self.b + self.b * len_norm)
  ```

---

##### Finding RET-13 (Low)
- **File**: `backend/app/services/retrieval/bm25.py`
- **Line**: 1–83
- **Severity**: Low
- **Category**: Type annotation correctness & Code conventions
- **Description**: Missing `from __future__ import annotations`, missing return type annotation on `fit() -> None`, and missing Google-style docstrings.
- **Correct Pattern / Fix**: Add `from __future__ import annotations`, type hints, and docstrings.

---

#### 4. `backend/app/services/retrieval/dense_retriever.py`

##### Finding RET-14 (High)
- **File**: `backend/app/services/retrieval/dense_retriever.py`
- **Line**: 24–29
- **Severity**: High
- **Category**: Async/await correctness / Blocking event loop
- **Description**: `retrieve()` is an asynchronous coroutine (`async def`), but it executes synchronous blocking method `self.pinecone_store.query(...)` in a sequential `for namespace in namespaces:` loop:
  ```python
  for namespace in namespaces:
      results = self.pinecone_store.query(
          embedding=query_embedding,
          namespace=namespace,
          top_k=top_k
      )
  ```
  This performs synchronous blocking HTTP I/O on the main event loop thread and doubles/triples retrieval latency when querying multiple namespaces (`cbuae-manuals` and `user-docs:...`).
- **Correct Pattern / Fix**: Query multiple namespaces in parallel using `asyncio.gather` and non-blocking calls:
  ```python
  tasks = [
      asyncio.to_thread(self.pinecone_store.query, query_embedding, ns, top_k)
      for ns in namespaces
  ]
  results_per_namespace = await asyncio.gather(*tasks)
  for results in results_per_namespace:
      for res in results:
          ...
  ```

---

##### Finding RET-15 (Low)
- **File**: `backend/app/services/retrieval/dense_retriever.py`
- **Line**: 1–47
- **Severity**: Low
- **Category**: Code conventions & Type annotations
- **Description**: Missing `from __future__ import annotations` and missing Google-style docstrings.
- **Correct Pattern / Fix**: Add `from __future__ import annotations` and Google-style docstrings.

---

#### 5. `backend/app/services/retrieval/rrf_fusion.py`

##### Finding RET-16 (Medium)
- **File**: `backend/app/services/retrieval/rrf_fusion.py`
- **Line**: 34–45
- **Severity**: Medium
- **Category**: Algorithm precision / Score normalization
- **Description**: Raw RRF scores ($1/(k + rank)$) are unnormalized fractions (e.g. ~0.01639 for rank 1 with $k=60$). Downstream citation consumers and UI widgets expecting scores in $[0, 1]$ receive near-zero decimals.
- **Correct Pattern / Fix**: Normalize RRF scores by the maximum possible theoretical score ($\sum_{i=1}^m \frac{1}{k + 1}$ where $m$ is the number of ranked lists):
  ```python
  max_score = sum(1.0 / (k + 1) for _ in ranked_lists) if ranked_lists else 1.0
  fused_candidates = []
  for text_hash, score in rrf_scores.items():
      candidate = candidates_map[text_hash]
      candidate.score = score / max_score
      fused_candidates.append(candidate)
  ```

---

##### Finding RET-17 (Low)
- **File**: `backend/app/services/retrieval/rrf_fusion.py`
- **Line**: 24–31
- **Severity**: Low
- **Category**: Method attribution
- **Description**: If a chunk appears only in `dense` or only in `bm25`, it is unconditionally rebranded as `retrieval_method="hybrid_rrf"`. If multi-method tracking is desired, only items appearing in multiple lists should be tagged `hybrid_rrf`, preserving original provenance otherwise.

---

##### Finding RET-18 (Low)
- **File**: `backend/app/services/retrieval/rrf_fusion.py`
- **Line**: 1–47
- **Severity**: Low
- **Category**: Code conventions & Type annotations
- **Description**: Missing `from __future__ import annotations` and Google-style docstrings.

---

#### 6. `backend/app/services/retrieval/reranker.py`

##### Finding RET-19 (High)
- **File**: `backend/app/services/retrieval/reranker.py`
- **Line**: 24–27
- **Severity**: High
- **Category**: Logic bug / Mutable state side-effects
- **Description**: In `rerank()`, `candidate = candidates[idx]` directly mutates candidate objects in the caller's input list:
  ```python
  candidate = candidates[idx]
  candidate.score = res.score
  candidate.retrieval_method += "_reranked"
  ```
  If candidates are logged, re-reranked, or used across retry loops, the candidate's `retrieval_method` mutates to `"hybrid_rrf_reranked_reranked"`, corrupting retrieval metadata.
- **Correct Pattern / Fix**: Clone candidate objects using Pydantic `model_copy`:
  ```python
  orig = candidates[idx]
  cloned = orig.model_copy(update={
      "score": res.score,
      "retrieval_method": f"{orig.retrieval_method}_reranked"
  })
  reranked_candidates.append(cloned)
  ```

---

##### Finding RET-20 (High)
- **File**: `backend/app/services/retrieval/reranker.py`
- **Line**: 17–31
- **Severity**: High
- **Category**: Resilience / Total candidate drop on error
- **Description**: If `llm_router.rerank()` returns an empty list (e.g. due to cross-encoder timeout, NVIDIA API rate limit, or invalid response format), `reranked_candidates` is empty `[]`. The reranker drops all valid RRF candidates and returns `[]`, causing the entire RAG pipeline to return 0 citations to the user.
- **Correct Pattern / Fix**: Fall back to the top input candidates when reranking fails:
  ```python
  if not rerank_results:
      logger.warning("Neural reranking produced no results; falling back to RRF candidates.")
      return candidates[:top_n]
  ```

---

##### Finding RET-21 (Low)
- **File**: `backend/app/services/retrieval/reranker.py`
- **Line**: 1–32
- **Severity**: Low
- **Category**: Code conventions & Type annotations
- **Description**: Missing `from __future__ import annotations` and Google-style docstrings.

---

### Module: Analytics Engine (`backend/app/services/analytics/`)

#### 7. `backend/app/services/analytics/model_metrics_extractor.py`

##### Finding ANA-01 (Critical)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line**: 12
- **Severity**: Critical
- **Category**: Parsing / Financial number formatting violation
- **Description**: Regex pattern `self.val_pattern = r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|percent|%?)?"` splits numbers at the first comma. This directly violates Rule 10: *"Financial numbers: Commas in numbers (e.g., 1,250,000) must be preserved during text processing. Never split on commas."* When parsing financial metrics such as `EAD: 1,500,000 AED` or `IFRS 9 ECL Provision: 2,400,000`, the pattern captures only `1` or `2`, extracting completely erroneous metrics (`1.0` or `2.0`).
- **Correct Pattern / Fix**: Support comma-grouped integers and clean commas before floating-point parsing:
  ```python
  self.val_pattern = r"(?P<value>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<unit>%|percent|bps|bp)?"
  ...
  value_str = match.group("value").replace(",", "")
  value = float(value_str)
  ```

---

##### Finding ANA-02 (High)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line**: 12
- **Severity**: High
- **Category**: Regex syntax / Ambiguous optional group
- **Description**: The unit regex contains `%?` inside the alternation `(?P<unit>%|percent|%?)?`. Because `%?` matches the empty string, the alternation is non-deterministic and can match an empty string even when a percent sign is present.
- **Correct Pattern / Fix**: Use `(?P<unit>%|percent|bps|bp)?` without nested zero-or-one quantifiers.

---

##### Finding ANA-03 (Medium)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line**: 16–30
- **Severity**: Medium
- **Category**: Markdown table parsing incompatibility
- **Description**: Metric regexes only match prose delimiters `(?:of|:|=|is)?`. In IBM Docling markdown output, model validation metrics are formatted in markdown tables (e.g. `| Gini Coefficient | 62.5% |` or `| AUC | 0.82 |`). The regex fails to match table pipes `|` and table delimiters, missing tabular metrics completely.
- **Correct Pattern / Fix**: Include markdown table pipe delimiters `[:=|\|\s]+` in separator patterns:
  ```python
  self.patterns = {
      "gini": re.compile(rf"Gini\s*(?:coefficient|index)?\s*[:=|\|\s]+\s*{self.val_pattern}", re.IGNORECASE),
      "auc": re.compile(rf"(?:AUC|AUROC)\s*[:=|\|\s]+\s*{self.val_pattern}", re.IGNORECASE),
      "ks": re.compile(rf"KS\s*(?:statistic)?\s*[:=|\|\s]+\s*{self.val_pattern}", re.IGNORECASE),
      ...
  }
  ```

---

##### Finding ANA-04 (Medium)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line**: 43–46
- **Severity**: Medium
- **Category**: Unit normalization / Basis points handling
- **Description**: Metrics given in basis points (`bps`, `bp`) are classified as `unit = "absolute"` with no scale conversion. For example, a PD of `45 bps` is recorded as `45.0` absolute instead of `0.45%` (0.0045).
- **Correct Pattern / Fix**:
  ```python
  if unit_str.lower() in ("%", "percent"):
      unit = "%"
  elif unit_str.lower() in ("bps", "bp"):
      unit = "%"
      value = value / 100.0
  else:
      unit = "absolute"
  ```

---

##### Finding ANA-05 (Low)
- **File**: `backend/app/services/analytics/model_metrics_extractor.py`
- **Line**: 1–71
- **Severity**: Low
- **Category**: Code conventions
- **Description**: Missing Google-style docstrings for `__init__` and `_extract_metric`.

---

#### 8. `backend/app/services/analytics/policy_checker.py`

##### Finding ANA-06 (High)
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line**: 22–28
- **Severity**: High
- **Category**: Analytics logic / Value normalization bug
- **Description**: `get_absolute_value` only divides by 100 if `metric.unit == "%"`:
  ```python
  def get_absolute_value(metric: MetricValue | None) -> float | None:
      if metric is None:
          return None
      val = metric.value
      if metric.unit == "%":
          return val / 100.0
      return val
  ```
  If a document states `AUC: 78.5` without a `%` symbol, `metric.unit` is `"absolute"`, and `get_absolute_value` returns `78.5`. Line 48 evaluates `78.5` against `0.70` (evaluating as `PASS`), but records `PolicyResult.value = 78.5` against `threshold = ">= 0.70"`, corrupting the audit report data.
- **Correct Pattern / Fix**:
  ```python
  def get_absolute_value(metric: MetricValue | None) -> float | None:
      if metric is None:
          return None
      val = metric.value
      if metric.unit == "%" or val > 1.0:
          return val / 100.0
      return val
  ```

---

##### Finding ANA-07 (Medium)
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line**: 48–62
- **Severity**: Medium
- **Category**: Regulatory standard consistency
- **Description**: The reported threshold is `">= 0.70"`, but the check classifies `auc_val <= 0.77` as `WARNING` and requires `auc_val > 0.77` for `PASS`:
  ```python
  if auc_val < 0.70:
      status = "BREACH"
  elif auc_val <= 0.77:
      status = "WARNING"
  else:
      status = "PASS"
  ```
  Under CBUAE MMG benchmarks, AUC >= 0.75 is considered acceptable discriminatory power (PASS), 0.70–0.75 is WARNING, and < 0.70 is BREACH. The threshold label and condition boundaries conflict.
- **Correct Pattern / Fix**:
  ```python
  if auc_val < 0.70:
      status = "BREACH"
  elif auc_val < 0.75:
      status = "WARNING"
  else:
      status = "PASS"
  threshold = ">= 0.75 (Warning: 0.70-0.75)"
  ```

---

##### Finding ANA-08 (Medium)
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line**: 8–151
- **Severity**: Medium
- **Category**: Incomplete policy validation coverage
- **Description**: `ModelValidationProfile` includes `hosmer_lemeshow_p_value`, `brier_score`, and `pd_accuracy_ratio`, but `PolicyChecker` ignores all calibration metrics.
- **Correct Pattern / Fix**: Implement checks for calibration metrics:
  - Hosmer-Lemeshow: p-value < 0.05 (BREACH), 0.05–0.10 (WARNING), >= 0.10 (PASS).
  - Brier score: <= 0.10 (PASS), 0.10–0.25 (WARNING), > 0.25 (BREACH).

---

##### Finding ANA-09 (Low)
- **File**: `backend/app/services/analytics/policy_checker.py`
- **Line**: 1–152
- **Severity**: Low
- **Category**: Code conventions
- **Description**: Missing Google-style docstrings for `check`, `get_normalized_value`, and `get_absolute_value`.

---

#### 9. `backend/app/services/analytics/ews_detector.py`

##### Finding ANA-10 (High)
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line**: 137–145
- **Severity**: High
- **Category**: False-positive trigger in EWS detection
- **Description**: `obs_vs_pred` uses `get_absolute_value()`. If `observed_vs_predicted_default_rate` is extracted without a `%` sign (e.g. `Observed vs Predicted Default Rate: 105` meaning 105%), `get_absolute_value` returns `105.0`. Then `105.0 > 1.2` immediately triggers a false-positive HIGH severity `"Calibration Failure"` alert.
- **Correct Pattern / Fix**: Normalize ratio values where `val > 10.0`:
  ```python
  def get_ratio_value(metric: MetricValue | None) -> float | None:
      if metric is None:
          return None
      val = metric.value
      if metric.unit == "%" or val > 10.0:
          return val / 100.0
      return val
  ```

---

##### Finding ANA-11 (Medium)
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line**: 94, 102
- **Severity**: Medium
- **Category**: Type annotation correctness
- **Description**: Helper functions `get_normalized_value(metric)` and `get_absolute_value(metric)` omit type annotations on the `metric` parameter (violates Code Convention 3).
- **Correct Pattern / Fix**: Annotate as `metric: MetricValue | None`.

---

##### Finding ANA-12 (Medium)
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line**: 120–126
- **Severity**: Medium
- **Category**: Incomplete EWS degradation trigger granularity
- **Description**: PSI drift check only triggers on `psi > 0.25` (HIGH severity). PSI between 0.10 and 0.25 (moderate drift requiring monitoring under CBUAE MMG) is ignored and produces no MEDIUM warning signal.
- **Correct Pattern / Fix**: Add MEDIUM severity signal for moderate drift:
  ```python
  if psi is not None:
      if psi > 0.25:
          signals.append(EWSSignal(
              signal_name="Significant Population Drift",
              description="PSI is greater than 0.25, indicating severe population drift.",
              severity="HIGH",
              source_excerpt=profile.psi.context if profile.psi else "N/A"
          ))
      elif psi >= 0.10:
          signals.append(EWSSignal(
              signal_name="Moderate Population Drift",
              description="PSI is between 0.10 and 0.25, requiring monitoring.",
              severity="MEDIUM",
              source_excerpt=profile.psi.context if profile.psi else "N/A"
          ))
  ```

---

##### Finding ANA-13 (Low)
- **File**: `backend/app/services/analytics/ews_detector.py`
- **Line**: 1–172
- **Severity**: Low
- **Category**: Code conventions
- **Description**: Missing Google-style docstrings on methods and class.

---

#### 10. `backend/app/services/analytics/__init__.py`

##### Finding ANA-14 (Low)
- **File**: `backend/app/services/analytics/__init__.py`
- **Line**: 1
- **Severity**: Low
- **Category**: Package export / API completeness
- **Description**: `__init__.py` is completely empty (0 bytes) and does not export `ModelMetricsExtractor`, `PolicyChecker`, or `EarlyWarningDetector`.
- **Correct Pattern / Fix**:
  ```python
  from app.services.analytics.model_metrics_extractor import ModelMetricsExtractor
  from app.services.analytics.policy_checker import PolicyChecker
  from app.services.analytics.ews_detector import EarlyWarningDetector

  __all__ = [
      "ModelMetricsExtractor",
      "PolicyChecker",
      "EarlyWarningDetector"
  ]
  ```

---

### Cross-Cutting: Dependencies Compatibility (`backend/requirements.txt`)

##### Finding DEP-01 (High)
- **File**: `backend/requirements.txt`
- **Line**: 16
- **Severity**: High
- **Category**: Deprecated package dependency
- **Description**: `requirements.txt` lists `pinecone-client` instead of modern `pinecone` (`pinecone>=3.0.0`). The codebase uses `from pinecone import Pinecone` which is the v3+ modern SDK interface.
- **Correct Pattern / Fix**: Replace `pinecone-client` with `pinecone>=3.0.0`.

---

##### Finding DEP-02 (Medium)
- **File**: `backend/requirements.txt`
- **Line**: 30, 32
- **Severity**: Medium
- **Category**: Redundant dependencies
- **Description**: `requirements.txt` includes `langchain-nvidia-ai-endpoints` and `langchain-google-genai`. Neither package is imported anywhere in the backend codebase (retrieval and LLM routing directly use `openai` and `google-genai` SDKs).
- **Correct Pattern / Fix**: Remove unused `langchain-*` packages to reduce build surface and dependency bloat.

---

## 3. Summary Matrix of All Findings

| ID | File | Line(s) | Severity | Category | Short Summary |
| :--- | :--- | :---: | :---: | :--- | :--- |
| **RET-01** | `retrieval/pinecone_store.py` | 7–9 | **Critical** | API Misuse / Crash | `PineconeStore()` missing default params crashes API routes |
| **RET-02** | `retrieval/pinecone_store.py` | 11–21 | **Critical** | Incomplete Code | `upsert_chunks()` is an unimplemented stub |
| **RET-03** | `retrieval/pinecone_store.py` | 65–66 | **High** | API Misuse / Crash | `stats.namespaces.keys()` raises AttributeError on empty index |
| **RET-04** | `retrieval/pinecone_store.py` | 57–58 | **Medium** | Error Handling | Bare `except Exception:` swallows errors silently |
| **RET-05** | `retrieval/pinecone_store.py` | 11–63 | **Medium** | Async/Await | Synchronous blocking I/O calls freeze event loop |
| **RET-06** | `retrieval/pinecone_store.py` | 1–70 | **Low** | Code Conventions | Missing `__future__` annotations, docstrings, return types |
| **RET-07** | `retrieval/hybrid_retriever.py` | 26–30 | **Critical** | Security / Multi-Tenancy | `_fetch_chunks_for_document` misses `tenant_id` filter |
| **RET-08** | `retrieval/hybrid_retriever.py` | 54–73 | **Medium** | Retrieval Logic | BM25 corpus omits CBUAE regulatory guidelines |
| **RET-09** | `retrieval/hybrid_retriever.py` | 1–113 | **Low** | Code Conventions | Missing `__future__` annotations and docstrings |
| **RET-10** | `retrieval/bm25.py` | 21–52 | **High** | Logic Bug | `fit()` accumulates document stats across multiple calls |
| **RET-11** | `retrieval/bm25.py` | 16–19 | **Medium** | Tokenization | `split()` tokenizer fails on words with punctuation |
| **RET-12** | `retrieval/bm25.py` | 75 | **Medium** | Logic Bug | Potential `ZeroDivisionError` when `avgdl == 0` |
| **RET-13** | `retrieval/bm25.py` | 1–83 | **Low** | Code Conventions | Missing annotations, return types, and docstrings |
| **RET-14** | `retrieval/dense_retriever.py` | 24–29 | **High** | Async/Await | Blocking synchronous loop in async retrieval method |
| **RET-15** | `retrieval/dense_retriever.py` | 1–47 | **Low** | Code Conventions | Missing `__future__` annotations and docstrings |
| **RET-16** | `retrieval/rrf_fusion.py` | 34–45 | **Medium** | Algorithm Precision | Unnormalized raw RRF scores |
| **RET-17** | `retrieval/rrf_fusion.py` | 24–31 | **Low** | Logic / Provenance | Unconditional `hybrid_rrf` tagging for single-source results |
| **RET-18** | `retrieval/rrf_fusion.py` | 1–47 | **Low** | Code Conventions | Missing `__future__` annotations and docstrings |
| **RET-19** | `retrieval/reranker.py` | 24–27 | **High** | Logic / Mutability | In-place mutation of input candidates |
| **RET-20** | `retrieval/reranker.py` | 17–31 | **High** | Resilience / Bug | Empty rerank results drop all RRF candidates |
| **RET-21** | `retrieval/reranker.py` | 1–32 | **Low** | Code Conventions | Missing `__future__` annotations and docstrings |
| **ANA-01** | `analytics/model_metrics_extractor.py` | 12 | **Critical** | Parsing / Rule 10 | Regex truncates comma-formatted financial numbers |
| **ANA-02** | `analytics/model_metrics_extractor.py` | 12 | **High** | Regex Syntax | Ambiguous nested optional group `(?P<unit>%|percent|%?)?` |
| **ANA-03** | `analytics/model_metrics_extractor.py` | 16–30 | **Medium** | Parsing | Fails to parse Markdown table formatting |
| **ANA-04** | `analytics/model_metrics_extractor.py` | 43–46 | **Medium** | Unit Conversion | Missing scale handling for basis points (`bps`) |
| **ANA-05** | `analytics/model_metrics_extractor.py` | 1–71 | **Low** | Code Conventions | Missing Google-style docstrings |
| **ANA-06** | `analytics/policy_checker.py` | 22–28 | **High** | Analytics Logic | `get_absolute_value` fails on unflagged percentages |
| **ANA-07** | `analytics/policy_checker.py` | 48–62 | **Medium** | Regulatory Alignment | Conflicting AUC threshold string and condition checks |
| **ANA-08** | `analytics/policy_checker.py` | 8–151 | **Medium** | Validation Scope | Missing calibration checks (Hosmer-Lemeshow, Brier) |
| **ANA-09** | `analytics/policy_checker.py` | 1–152 | **Low** | Code Conventions | Missing docstrings on helper methods |
| **ANA-10** | `analytics/ews_detector.py` | 137–145 | **High** | False Positive Alert | `obs_vs_pred` triggers false positive calibration alarm |
| **ANA-11** | `analytics/ews_detector.py` | 94, 102 | **Medium** | Type Annotations | Missing type annotations on parameter `metric` |
| **ANA-12** | `analytics/ews_detector.py` | 120–126 | **Medium** | EWS Granularity | Missing moderate PSI shift warning (0.10–0.25) |
| **ANA-13** | `analytics/ews_detector.py` | 1–172 | **Low** | Code Conventions | Missing Google-style docstrings |
| **ANA-14** | `analytics/__init__.py` | 1 | **Low** | Package Exports | Empty `__init__.py` without public exports |
| **DEP-01** | `requirements.txt` | 16 | **High** | Dependencies | Deprecated `pinecone-client` vs `pinecone>=3.0.0` |
| **DEP-02** | `requirements.txt` | 30, 32 | **Medium** | Dependencies | Redundant/unused `langchain-*` dependencies |
