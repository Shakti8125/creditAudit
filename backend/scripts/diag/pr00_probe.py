"""PR-00 verification probe: LLM providers, Pinecone and the rate-limiter config.

Dev-only and read-only. It runs locally from ``backend/`` with
``python -m scripts.diag.pr00_probe`` and reads its keys and settings from
``app.config.settings`` (the local ``.env``), so it sees exactly what the app
sees (runbook: ``docs/qa/pr-00-runbook.md``). Every prompt is synthetic; no
tenant data is read or sent.

Output is one JSON object per line on stdout, each prefixed ``PR00 ``. A line
holds names, HTTP status codes, lengths, counts, dimensions and booleans only.
It never holds a key, a token, a URL, a response body or generated text. The
few strings that could echo a request (provider error excerpts) are truncated
and scrubbed of every configured secret before they are printed.

Side effects: about a dozen small NVIDIA calls, about six Gemini calls and one
``SCRIPT LOAD`` of the rate limiter's own Lua script into Upstash (idempotent;
the app does the same at startup). Nothing is written to Postgres or Pinecone.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.services.llm import model_catalog

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

# Which models to check comes from the app's own settings (NVIDIA_RERANK_MODEL,
# GEMINI_GENERATION_MODEL, ... and their *_CANDIDATES lists), through
# app/services/llm/model_catalog.py. So the probe and the app cannot disagree: the configured
# ID is always checked, first, and every row says whether it is the configured one.
#
# These extras are probe-only observations that the app never calls: IDs the docs list as
# retired (to confirm they really are gone) and newer or sibling IDs worth knowing about
# (README section 5, 2026-09-30).
GEMINI_STATUS_EXTRAS = (
    "gemini-2.0-flash",
    "text-embedding-004",
    "gemini-2.5-flash",
    "gemini-3.8-flash",
    "gemini-embedding-001",
    "gemini-embedding-2",
)

# Namespaces the app itself names (hybrid_retriever.py, documents.py). Any other
# namespace is reported only by its prefix, so tenant and document IDs never
# reach the log.
KNOWN_NAMESPACES = frozenset({"", "__default__", "cbuae-manuals"})

SYNTHETIC_SYSTEM = "You are a model validation assistant. Respond only with JSON that matches the schema."
SYNTHETIC_PROMPT = (
    "Compare two versions of a synthetic credit scoring model document. "
    "Version 1: logistic regression, 12 features, development sample 2019-2021, Gini 0.52. "
    "Version 2: gradient boosting, 18 features, development sample 2020-2023, Gini 0.58. "
    "List the differences and give a one-sentence summary."
)
DIFF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "differences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "v1": {"type": "string"},
                    "v2": {"type": "string"},
                },
                "required": ["area", "v1", "v2"],
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["differences", "summary"],
}

_SECRET_PATTERNS = (
    re.compile(r"nvapi-[A-Za-z0-9_\-]+"),
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),
    re.compile(r"pcsk_[A-Za-z0-9_]+"),
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)(key|token)=[^&\s\"']+"),
    re.compile(r"[a-z][a-z0-9+.\-]*://\S+"),
)
_MAX_TEXT = 200


class ProbeConfig:
    """Settings the probe needs, read from the app's own ``Settings`` object.

    Attributes:
        nvidia_api_key: NVIDIA NIM key.
        nvidia_base_url: OpenAI-compatible NIM base URL.
        gemini_api_key: Google AI Studio key.
        pinecone_api_key: Pinecone key.
        pinecone_index_name: Pinecone index the app queries.
        redis_url: Upstash REST URL.
        redis_token: Upstash REST token.
        rate_limit_enabled: The app's ``RATE_LIMIT_ENABLED`` after parsing.
        lua_dir: Directory holding the rate limiter's Lua scripts.
        models: Settings that name the models to check. ``from_app_settings`` passes the app's
            live settings; a directly built config uses the built-in defaults, so a test never
            depends on the developer's ``.env``.
    """

    def __init__(
        self,
        *,
        nvidia_api_key: str = "",
        nvidia_base_url: str = "https://integrate.api.nvidia.com/v1",
        gemini_api_key: str = "",
        pinecone_api_key: str = "",
        pinecone_index_name: str = "",
        redis_url: str = "",
        redis_token: str = "",
        rate_limit_enabled: bool = True,
        lua_dir: Path | None = None,
        models: Settings | None = None,
    ) -> None:
        self.nvidia_api_key = nvidia_api_key
        self.nvidia_base_url = nvidia_base_url.rstrip("/")
        self.gemini_api_key = gemini_api_key
        self.pinecone_api_key = pinecone_api_key
        self.pinecone_index_name = pinecone_index_name
        self.redis_url = redis_url
        self.redis_token = redis_token
        self.rate_limit_enabled = rate_limit_enabled
        self.lua_dir = lua_dir or Path.cwd() / "lua"
        self.models = models if models is not None else Settings.model_construct()

    @property
    def rerank_models(self) -> tuple[str, ...]:
        """Reranker IDs to check: the configured one first."""
        return model_catalog.nvidia_rerank_candidates(self.models)

    @property
    def generation_models(self) -> tuple[str, ...]:
        """NVIDIA chat IDs to check: the primary, then the 404 fallback."""
        return model_catalog.nvidia_generation_models(self.models)

    @property
    def gemini_chain(self) -> tuple[str, ...]:
        """Gemini chat IDs to call: the configured one first, then the candidates."""
        return model_catalog.gemini_generation_candidates(self.models)

    @property
    def gemini_models(self) -> tuple[str, ...]:
        """Gemini IDs whose status is looked up: the chain plus the probe-only extras."""
        return model_catalog.split_ids(",".join([*self.gemini_chain, *GEMINI_STATUS_EXTRAS]))

    @property
    def secrets(self) -> list[str]:
        """Return every configured value that must never be printed."""
        values = [
            self.nvidia_api_key,
            self.gemini_api_key,
            self.pinecone_api_key,
            self.redis_token,
            self.redis_url,
            self.pinecone_index_name,
        ]
        return [v for v in values if v and len(v) >= 4]

    @classmethod
    def from_app_settings(cls) -> ProbeConfig:
        """Build the config from ``app.config.settings`` (run from ``/app``)."""
        from app.config import settings

        return cls(
            models=settings,
            nvidia_api_key=settings.nvidia_api_key,
            nvidia_base_url=settings.nvidia_base_url,
            gemini_api_key=settings.gemini_api_key,
            pinecone_api_key=settings.pinecone_api_key,
            pinecone_index_name=settings.pinecone_index_name,
            redis_url=settings.redis_url,
            redis_token=settings.redis_token,
            rate_limit_enabled=settings.rate_limit_enabled,
        )


class Emitter:
    """Print scrubbed ``PR00`` JSON lines and keep them for the caller.

    Args:
        secrets: Values that are replaced with ``***`` wherever they appear.
        sink: Where each finished line goes; defaults to stdout.
    """

    def __init__(self, secrets: list[str], sink: Callable[[str], None] | None = None) -> None:
        self._secrets = sorted(set(secrets), key=len, reverse=True)
        self._sink = sink or (lambda line: print(line, flush=True))
        self.lines: list[str] = []

    def scrub(self, value: Any) -> Any:
        """Recursively remove secrets and credential-like substrings from ``value``."""
        if isinstance(value, str):
            text = value
            for secret in self._secrets:
                text = text.replace(secret, "***")
            for pattern in _SECRET_PATTERNS:
                text = pattern.sub("***", text)
            return text[:_MAX_TEXT]
        if isinstance(value, dict):
            return {str(k): self.scrub(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        return value

    def __call__(self, kind: str, /, **fields: Any) -> None:
        """Emit one line of type ``kind`` with the given fields."""
        record = self.scrub({"s": kind, **fields})
        line = "PR00 " + json.dumps(record, sort_keys=True, default=str)
        self.lines.append(line)
        self._sink(line)


def tolerant_json(text: str) -> Any | None:
    """Parse the first JSON object in ``text`` after stripping fences and think blocks.

    Args:
        text: Raw model output.

    Returns:
        The decoded object, or ``None`` when no object can be decoded.
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    except json.JSONDecodeError:
        return None
    return obj


def strict_json_ok(text: str) -> bool:
    """Return whether ``json.loads`` accepts ``text`` as is (what the app does today)."""
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return True


def schema_ok(obj: Any) -> bool:
    """Return whether ``obj`` has the shape of ``DIFF_SCHEMA`` with at least one difference."""
    if not isinstance(obj, dict):
        return False
    diffs = obj.get("differences")
    return (
        isinstance(diffs, list)
        and len(diffs) > 0
        and all(isinstance(d, dict) and {"area", "v1", "v2"} <= d.keys() for d in diffs)
        and isinstance(obj.get("summary"), str)
    )


def error_excerpt(response: httpx.Response) -> str:
    """Return a short provider error message from ``response`` (scrubbed later)."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return f"{err.get('status') or err.get('type') or ''} {err.get('message') or ''}".strip()
        if isinstance(err, str):
            return err
        for key in ("detail", "message", "title"):
            if isinstance(body.get(key), str):
                return body[key]
    return ""


async def _timed(call: Callable[[], Awaitable[httpx.Response]]) -> tuple[httpx.Response | None, str, int]:
    """Run an HTTP call and return ``(response, exception class name, elapsed ms)``."""
    started = time.monotonic()
    try:
        response = await call()
    except httpx.HTTPError as exc:
        return None, type(exc).__name__, int((time.monotonic() - started) * 1000)
    return response, "", int((time.monotonic() - started) * 1000)


def _status(response: httpx.Response | None, exc_name: str) -> int | str:
    return response.status_code if response is not None else exc_name


async def probe_config(cfg: ProbeConfig, emit: Emitter) -> None:
    """Report which settings are present, without printing any value."""
    parsed = urlparse(cfg.redis_url) if cfg.redis_url else None
    emit(
        "config",
        nvidia_key_present=bool(cfg.nvidia_api_key),
        gemini_key_present=bool(cfg.gemini_api_key),
        pinecone_key_present=bool(cfg.pinecone_api_key),
        pinecone_index_name_present=bool(cfg.pinecone_index_name),
        nvidia_base_url_is_default=cfg.nvidia_base_url == "https://integrate.api.nvidia.com/v1",
        rate_limit_enabled=cfg.rate_limit_enabled,
        redis_url_present=bool(cfg.redis_url),
        redis_url_scheme=parsed.scheme if parsed else "",
        redis_host_is_upstash=bool(parsed and (parsed.hostname or "").endswith(".upstash.io")),
        redis_token_present=bool(cfg.redis_token),
        configured_models={
            "nvidia_generation": cfg.models.nvidia_generation_model,
            "nvidia_rerank": cfg.models.nvidia_rerank_model,
            "nvidia_embedding": cfg.models.nvidia_embedding_model,
            "embedding_dimensions": cfg.models.embedding_dimensions,
            "gemini_generation": cfg.models.gemini_generation_model,
        },
    )


async def probe_nvidia(cfg: ProbeConfig, client: httpx.AsyncClient, emit: Emitter, facts: dict[str, Any]) -> None:
    """Catalogue, reranker, generation, structured-output and embedding probes on NVIDIA."""
    if not cfg.nvidia_api_key:
        emit("nvidia_skipped", reason="no key")
        return
    headers = {"Authorization": f"Bearer {cfg.nvidia_api_key}", "Accept": "application/json"}

    resp, exc, ms = await _timed(lambda: client.get(f"{cfg.nvidia_base_url}/models", headers=headers))
    if resp is not None and resp.status_code == 200:
        ids = sorted(m.get("id", "") for m in resp.json().get("data", []))
        probed = cfg.generation_models + cfg.rerank_models + (cfg.models.nvidia_embedding_model,)
        emit(
            "nvidia_catalog",
            status=200,
            model_count=len(ids),
            listed={m: m in ids for m in probed},
            rerank_ids=[i for i in ids if "rerank" in i][:30],
            embed_ids=[i for i in ids if "embed" in i][:30],
        )
    else:
        emit("nvidia_catalog", status=_status(resp, exc), error=error_excerpt(resp) if resp is not None else "")

    for model in cfg.rerank_models:
        payload = {
            "model": model,
            "query": {"text": "PD model calibration test"},
            "passages": [
                {"text": "The binomial test compares observed default rates with predicted PDs per grade."},
                {"text": "The office is open from nine to five on weekdays."},
            ],
            "truncate": "END",
        }
        url = model_catalog.rerank_url(model, cfg.models)
        resp, exc, ms = await _timed(lambda url=url, payload=payload: client.post(url, headers=headers, json=payload))
        fields: dict[str, Any] = {
            "model": model,
            "configured": model == cfg.models.nvidia_rerank_model,
            "status": _status(resp, exc),
            "ms": ms,
        }
        if resp is not None and resp.status_code == 200:
            rankings = resp.json().get("rankings", [])
            fields.update(rankings=len(rankings), top_index=rankings[0].get("index") if rankings else None)
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("nvidia_rerank", **fields)

    chat_url = f"{cfg.nvidia_base_url}/chat/completions"
    for model in cfg.generation_models:
        body = {"model": model, "messages": [{"role": "user", "content": "Reply with the single word OK."}], "max_tokens": 64}
        resp, exc, ms = await _timed(lambda body=body: client.post(chat_url, headers=headers, json=body))
        fields = {
            "model": model,
            "configured": model == cfg.models.nvidia_generation_model,
            "status": _status(resp, exc),
            "ms": ms,
        }
        if resp is not None and resp.status_code == 200:
            choice = (resp.json().get("choices") or [{}])[0]
            fields.update(finish_reason=choice.get("finish_reason"), content_len=len((choice.get("message") or {}).get("content") or ""))
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("nvidia_generate", **fields)

    await probe_nvidia_structured(cfg, client, emit, headers)

    emb_url = f"{cfg.nvidia_base_url}/embeddings"
    embed_model = cfg.models.nvidia_embedding_model
    pinned = cfg.models.embedding_dimensions
    facts["pinned_dimension"] = pinned
    for dims in (None, pinned or 1024):
        body: dict[str, Any] = {"model": embed_model, "input": ["test"], "input_type": "query"}
        if dims:
            body["dimensions"] = dims
        resp, exc, ms = await _timed(lambda body=body: client.post(emb_url, headers=headers, json=body))
        fields = {"model": embed_model, "requested_dimensions": dims, "status": _status(resp, exc), "ms": ms}
        if resp is not None and resp.status_code == 200:
            data = resp.json().get("data") or [{}]
            dim = len(data[0].get("embedding") or [])
            fields["dimension"] = dim
            if dims is None:
                facts["embed_dimension"] = dim
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("nvidia_embed", **fields)


async def probe_nvidia_structured(
    cfg: ProbeConfig, client: httpx.AsyncClient, emit: Emitter, headers: dict[str, str]
) -> None:
    """Send one synthetic structured-output prompt in seven parameter variants (QA-005).

    ``deployed`` is the exact request the app sends today (top-level
    ``guided_json``, no ``chat_template_kwargs``, the router defaults
    ``temperature=0.7`` and ``max_tokens=1024``, router.py:279-285). The other
    six are each of top-level ``guided_json``, ``nvext.guided_json`` and
    ``response_format`` with thinking explicitly on and off, at the same
    temperature and budget.
    """
    model = cfg.generation_models[0]
    variants: list[tuple[str, dict[str, Any], bool | None]] = [("deployed", {"guided_json": DIFF_SCHEMA}, None)]
    for thinking in (True, False):
        variants += [
            ("top_guided_json", {"guided_json": DIFF_SCHEMA}, thinking),
            ("nvext_guided_json", {"nvext": {"guided_json": DIFF_SCHEMA}}, thinking),
            (
                "response_format_json_schema",
                {"response_format": {"type": "json_schema", "json_schema": {"name": "differences", "schema": DIFF_SCHEMA}}},
                thinking,
            ),
        ]
    url = f"{cfg.nvidia_base_url}/chat/completions"
    for name, extra, thinking in variants:
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYNTHETIC_SYSTEM},
                {"role": "user", "content": SYNTHETIC_PROMPT},
            ],
            "temperature": 0.7,
            "max_tokens": 1024,
            **extra,
        }
        if thinking is not None:
            body["chat_template_kwargs"] = {"enable_thinking": thinking}
        resp, exc, ms = await _timed(lambda body=body: client.post(url, headers=headers, json=body))
        fields: dict[str, Any] = {"model": model, "variant": name, "thinking": thinking, "status": _status(resp, exc), "ms": ms}
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            parsed = tolerant_json(content)
            fields.update(
                finish_reason=choice.get("finish_reason"),
                content_len=len(content),
                reasoning_len=len(reasoning),
                think_tag_in_content="<think>" in content,
                json_strict_ok=strict_json_ok(content),
                json_tolerant_ok=parsed is not None,
                schema_ok=schema_ok(parsed),
                completion_tokens=(data.get("usage") or {}).get("completion_tokens"),
            )
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("nvidia_structured", **fields)


async def probe_gemini(cfg: ProbeConfig, client: httpx.AsyncClient, emit: Emitter) -> None:
    """Model status, catalogue, the D10 chain and one structured call on Gemini.

    The key goes in the ``x-goog-api-key`` header, never in the URL, so that no
    exception message or access log can carry it.
    """
    if not cfg.gemini_api_key:
        emit("gemini_skipped", reason="no key")
        return
    headers = {"x-goog-api-key": cfg.gemini_api_key}

    for model in cfg.gemini_models:
        resp, exc, ms = await _timed(lambda model=model: client.get(f"{GEMINI_BASE_URL}/models/{model}", headers=headers))
        fields: dict[str, Any] = {"model": model, "status": _status(resp, exc)}
        if resp is not None and resp.status_code == 200:
            info = resp.json()
            fields.update(
                resolved_name=info.get("name"),
                version=info.get("version"),
                methods=info.get("supportedGenerationMethods"),
                thinking=info.get("thinking"),
            )
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("gemini_model", **fields)

    names: list[str] = []
    page_token = ""
    catalog_status: int | str = ""
    for _ in range(5):
        params = {"pageSize": "1000", **({"pageToken": page_token} if page_token else {})}
        resp, exc, ms = await _timed(
            lambda params=params: client.get(f"{GEMINI_BASE_URL}/models", headers=headers, params=params)
        )
        catalog_status = _status(resp, exc)
        if resp is None or resp.status_code != 200:
            break
        data = resp.json()
        names += [m.get("name", "") for m in data.get("models", [])]
        page_token = data.get("nextPageToken") or ""
        if not page_token:
            break
    emit(
        "gemini_catalog",
        status=catalog_status,
        model_count=len(names),
        flash=sorted(n for n in names if "flash" in n)[:40],
        embedding=sorted(n for n in names if "embedding" in n)[:20],
    )

    for model in cfg.gemini_chain:
        body = {
            "contents": [{"parts": [{"text": "Reply with the single word OK."}]}],
            "generationConfig": {"maxOutputTokens": 256},
        }
        url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
        resp, exc, ms = await _timed(lambda url=url, body=body: client.post(url, headers=headers, json=body))
        fields = {
            "model": model,
            "configured": model == cfg.models.gemini_generation_model,
            "status": _status(resp, exc),
            "ms": ms,
        }
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            fields.update(
                model_version=data.get("modelVersion"),
                finish_reason=cand.get("finishReason"),
                text_len=sum(len(p.get("text") or "") for p in parts if not p.get("thought")),
                thoughts_tokens=(data.get("usageMetadata") or {}).get("thoughtsTokenCount"),
            )
        elif resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("gemini_generate", **fields)

    await probe_gemini_structured(client, emit, headers, cfg.gemini_chain[0])


def _gemini_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a JSON Schema subset to the upper-case OpenAPI form of ``responseSchema``."""
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type":
            out[key] = str(value).upper()
        elif key == "properties":
            out[key] = {k: _gemini_openapi_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _gemini_openapi_schema(value)
        else:
            out[key] = value
    return out


async def probe_gemini_structured(
    client: httpx.AsyncClient, emit: Emitter, headers: dict[str, str], model: str
) -> None:
    """Try ``responseJsonSchema`` then ``responseSchema`` on the first chain model (PR-02 input)."""
    url = f"{GEMINI_BASE_URL}/models/{model}:generateContent"
    for field_name, schema in (
        ("responseJsonSchema", DIFF_SCHEMA),
        ("responseSchema", _gemini_openapi_schema(DIFF_SCHEMA)),
    ):
        body = {
            "systemInstruction": {"parts": [{"text": SYNTHETIC_SYSTEM}]},
            "contents": [{"parts": [{"text": SYNTHETIC_PROMPT}]}],
            "generationConfig": {"maxOutputTokens": 2048, "responseMimeType": "application/json", field_name: schema},
        }
        resp, exc, ms = await _timed(lambda body=body: client.post(url, headers=headers, json=body))
        fields: dict[str, Any] = {"model": model, "schema_field": field_name, "status": _status(resp, exc), "ms": ms}
        if resp is not None and resp.status_code == 200:
            data = resp.json()
            cand = (data.get("candidates") or [{}])[0]
            parts = (cand.get("content") or {}).get("parts") or []
            text = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
            fields.update(
                model_version=data.get("modelVersion"),
                finish_reason=cand.get("finishReason"),
                text_len=len(text),
                json_strict_ok=strict_json_ok(text),
                schema_ok=schema_ok(tolerant_json(text)),
            )
            emit("gemini_structured", **fields)
            return
        if resp is not None:
            fields["error"] = error_excerpt(resp)
        emit("gemini_structured", **fields)


def summarise_namespaces(namespaces: dict[str, Any]) -> dict[str, Any]:
    """Group Pinecone namespaces by prefix so tenant and document IDs are never printed.

    Args:
        namespaces: ``describe_index_stats()["namespaces"]``.

    Returns:
        Counts per prefix plus the regulatory namespace facts QA-001 needs.
    """
    by_prefix: dict[str, dict[str, int]] = {}
    for name, info in namespaces.items():
        count = int((info or {}).get("vector_count", 0))
        if ":" in name:
            key = name.split(":", 1)[0] + ":*"
        elif name.startswith("reg-"):
            key = "reg-*"
        elif name in KNOWN_NAMESPACES:
            key = name or "(default)"
        else:
            key = "(other)"
        bucket = by_prefix.setdefault(key, {"namespaces": 0, "vectors": 0})
        bucket["namespaces"] += 1
        bucket["vectors"] += count
    return {
        "namespace_count": len(namespaces),
        "by_prefix": by_prefix,
        "cbuae_manuals_present": "cbuae-manuals" in namespaces,
        "cbuae_manuals_vectors": int((namespaces.get("cbuae-manuals") or {}).get("vector_count", 0)),
    }


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


async def probe_pinecone(
    cfg: ProbeConfig, emit: Emitter, facts: dict[str, Any], client_factory: Callable[[str], Any] | None = None
) -> None:
    """Describe the app's Pinecone index and its namespaces (QA-001, NEW-07, dimension check)."""
    if not (cfg.pinecone_api_key and cfg.pinecone_index_name):
        emit("pinecone_skipped", reason="no key or index name")
        return
    try:
        if client_factory is None:
            from pinecone import Pinecone

            client_factory = lambda key: Pinecone(api_key=key)
        pc = client_factory(cfg.pinecone_api_key)
        names = await asyncio.to_thread(lambda: list(pc.list_indexes().names()))
        desc = _as_dict(await asyncio.to_thread(pc.describe_index, cfg.pinecone_index_name))
    except Exception as exc:  # noqa: BLE001 - report the class only, never the message
        emit("pinecone_index", ok=False, error_class=type(exc).__name__)
        return
    spec = desc.get("spec") or {}
    serverless = spec.get("serverless") if isinstance(spec, dict) else None
    status = desc.get("status") or {}
    index_dim = desc.get("dimension")
    facts["index_dimension"] = index_dim
    emit(
        "pinecone_index",
        ok=True,
        index_count=len(names),
        configured_index_listed=cfg.pinecone_index_name in names,
        dimension=index_dim,
        metric=desc.get("metric"),
        vector_type=desc.get("vector_type"),
        spec_kind="serverless" if serverless else ("pod" if isinstance(spec, dict) and spec.get("pod") else "unknown"),
        cloud=(serverless or {}).get("cloud"),
        region=(serverless or {}).get("region"),
        ready=status.get("ready"),
        state=status.get("state"),
        deletion_protection=desc.get("deletion_protection"),
    )
    try:
        index = pc.Index(host=desc.get("host")) if desc.get("host") else pc.Index(cfg.pinecone_index_name)
        stats = _as_dict(await asyncio.to_thread(index.describe_index_stats))
    except Exception as exc:  # noqa: BLE001 - report the class only, never the message
        emit("pinecone_stats", ok=False, error_class=type(exc).__name__)
        return
    emit(
        "pinecone_stats",
        ok=True,
        dimension=stats.get("dimension"),
        total_vector_count=stats.get("total_vector_count"),
        **summarise_namespaces(stats.get("namespaces") or {}),
    )


async def probe_redis(cfg: ProbeConfig, emit: Emitter, client_factory: Callable[[str, str], Any] | None = None) -> None:
    """PING Upstash and load the token-bucket script, as the rate limiter does (QA-007)."""
    if not (cfg.redis_url and cfg.redis_token):
        emit("redis", configured=False)
        return
    result: dict[str, Any] = {"configured": True}
    try:
        if client_factory is None:
            from upstash_redis.asyncio import Redis

            client_factory = lambda url, token: Redis(url=url, token=token)
        redis = client_factory(cfg.redis_url, cfg.redis_token)
    except Exception as exc:  # noqa: BLE001 - report the class only, never the message
        emit("redis", **result, client_ok=False, error_class=type(exc).__name__)
        return
    result["client_ok"] = True
    try:
        result["ping_ok"] = bool(await redis.ping())
    except Exception as exc:  # noqa: BLE001
        result.update(ping_ok=False, ping_error_class=type(exc).__name__)
    script_path = cfg.lua_dir / "token_bucket.lua"
    if script_path.is_file():
        try:
            sha = await redis.script_load(script_path.read_text(encoding="utf-8"))
            result["script_load_ok"] = bool(sha)
        except Exception as exc:  # noqa: BLE001
            result.update(script_load_ok=False, script_load_error_class=type(exc).__name__)
    else:
        result["script_load_ok"] = None
    close = getattr(redis, "close", None)
    if close is not None:
        with contextlib.suppress(Exception):  # closing is best effort
            maybe = close()
            if asyncio.iscoroutine(maybe):
                await maybe
    emit("redis", **result)


async def run(
    cfg: ProbeConfig,
    sections: set[str],
    emit: Emitter,
    client: httpx.AsyncClient,
    pinecone_factory: Callable[[str], Any] | None = None,
    redis_factory: Callable[[str, str], Any] | None = None,
) -> dict[str, Any]:
    """Run the selected probe sections and return the shared facts."""
    started = time.monotonic()
    facts: dict[str, Any] = {}
    steps: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("config", lambda: probe_config(cfg, emit)),
        ("nvidia", lambda: probe_nvidia(cfg, client, emit, facts)),
        ("gemini", lambda: probe_gemini(cfg, client, emit)),
        ("pinecone", lambda: probe_pinecone(cfg, emit, facts, pinecone_factory)),
        ("redis", lambda: probe_redis(cfg, emit, redis_factory)),
    ]
    for name, step in steps:
        if name != "config" and name not in sections:
            continue
        try:
            await step()
        except Exception as exc:  # noqa: BLE001 - one broken section must not lose the others
            emit("section_error", section=name, error_class=type(exc).__name__)
    if facts.get("embed_dimension") is not None and facts.get("index_dimension") is not None:
        # The app pins the size (EMBEDDING_DIMENSIONS): longer vectors are sliced to it, so
        # what reaches Pinecone is the pinned size, not the model's native one.
        native, pinned = facts["embed_dimension"], facts.get("pinned_dimension") or 0
        effective = pinned if 0 < pinned <= native else native
        emit(
            "embed_vs_index",
            embed_dimension=native,
            pinned_dimension=pinned,
            effective_dimension=effective,
            index_dimension=facts["index_dimension"],
            match=effective == facts["index_dimension"],
        )
    emit("done", elapsed_s=round(time.monotonic() - started, 1), sections=sorted(sections))
    return facts


async def main(argv: list[str]) -> int:
    """Parse arguments, run the probe with the app's settings and return an exit code."""
    parser = argparse.ArgumentParser(description="PR-00 verification probe (read-only).")
    parser.add_argument(
        "--only",
        default="nvidia,gemini,pinecone,redis",
        help="comma-separated sections to run (default: all)",
    )
    args = parser.parse_args(argv)
    sections = {s.strip() for s in args.only.split(",") if s.strip()}
    cfg = ProbeConfig.from_app_settings()
    emit = Emitter(cfg.secrets)
    timeout = httpx.Timeout(180.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await run(cfg, sections, emit, client)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
