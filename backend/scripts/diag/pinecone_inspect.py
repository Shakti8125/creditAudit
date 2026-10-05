"""Read-only look at the Pinecone index: what each namespace holds, and whether this app can search it.

Use it when an index already holds records the app did not write (for example IFRS 9 text ingested
by an earlier project). Vectors can only be searched with the model that made them, so the check
that matters is the last one: the app's pinned embedding model embeds a query, and the closest
records of each namespace are printed with a short excerpt. If the excerpts are on topic and the
scores are clearly above the rest, the vectors are compatible. If they are unrelated, the earlier
project used another embedding model and the records cannot be reused.

    python -m scripts.diag.pinecone_inspect                      # every namespace that is not user-docs:*
    python -m scripts.diag.pinecone_inspect --namespace ifrs9 --query "ECL staging"

It calls only ``describe_index``, ``describe_index_stats``, ``list``, ``fetch`` and ``query``, so it
writes and deletes nothing. It never prints a key; an error shows its class, not its message.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any, Callable

DEFAULT_QUERY = "A financial asset shall be measured at amortised cost if both of the following conditions are met"
USER_DOCS_PREFIX = "user-docs:"
MAX_NAMESPACES = 6
EXCERPT_CHARS = 100
TEXT_KEYS = ("text", "chunk_text", "content", "page_content")


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return dict(obj)


def _short(value: Any, limit: int = 60) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def ids_from_page(page: Any) -> list[str]:
    """Return the ids of one ``index.list`` page (a list of ids in older SDKs, a response object in newer ones)."""
    vectors = getattr(page, "vectors", None)
    if vectors is not None:
        return [str(getattr(v, "id", v)) for v in vectors]
    return [str(item) for item in page]


def pick_namespaces(stats: dict[str, Any], requested: list[str]) -> list[str]:
    """The namespaces to inspect: the requested ones, else every one that is not a per-document ``user-docs:`` one."""
    names = list((stats.get("namespaces") or {}).keys())
    if requested:
        return requested
    return [n for n in names if not n.startswith(USER_DOCS_PREFIX)][:MAX_NAMESPACES]


def text_of(metadata: dict[str, Any]) -> str:
    for key in TEXT_KEYS:
        if isinstance(metadata.get(key), str):
            return metadata[key]
    return ""


def sample_records(index: Any, namespace: str, count: int) -> list[str]:
    """Describe up to ``count`` stored records: id shape, vector length and the metadata fields they carry."""
    lines: list[str] = []
    ids: list[str] = []
    for page in index.list(namespace=namespace, limit=count):
        ids.extend(ids_from_page(page))
        if len(ids) >= count:
            break
    ids = ids[:count]
    if not ids:
        return ["    (no records listed)"]
    fetched = _as_dict(index.fetch(ids=ids, namespace=namespace)).get("vectors") or {}
    for vid in ids:
        record = _as_dict(fetched.get(vid))
        meta = _as_dict(record.get("metadata"))
        fields = ", ".join(f"{k}:{type(v).__name__}" for k, v in sorted(meta.items())) or "(none)"
        lines.append(
            f"    id {_short(vid, 40)} | vector length {len(record.get('values') or [])} | "
            f"text {len(text_of(meta))} chars | metadata {fields}"
        )
    return lines


def search_records(index: Any, namespace: str, vector: list[float], top_k: int) -> list[str]:
    """The closest records to ``vector`` with score, source, section and a short excerpt."""
    response = index.query(namespace=namespace, vector=vector, top_k=top_k, include_metadata=True)
    lines = []
    for match in _as_dict(response).get("matches") or []:
        match = _as_dict(match)
        meta = _as_dict(match.get("metadata"))
        lines.append(
            f"    score {float(match.get('score') or 0):.3f} | source {_short(meta.get('source', '-'), 40)} | "
            f"section {_short(meta.get('section', '-'), 40)} | {_short(text_of(meta), EXCERPT_CHARS)}"
        )
    return lines or ["    (no matches)"]


async def inspect(
    *,
    api_key: str,
    index_name: str,
    query: str,
    namespaces: list[str],
    sample: int,
    top_k: int,
    out: Callable[[str], None] = print,
    client_factory: Callable[[str], Any] | None = None,
    embed: Callable[[list[str]], Any] | None = None,
) -> int:
    """Run the inspection; returns 0, or 1 when the index cannot be read."""
    if not (api_key and index_name):
        out("PINECONE_API_KEY or PINECONE_INDEX_NAME is not set.")
        return 1
    try:
        if client_factory is None:
            from pinecone import Pinecone

            client_factory = lambda key: Pinecone(api_key=key)
        pc = client_factory(api_key)
        desc = _as_dict(await asyncio.to_thread(pc.describe_index, index_name))
        index = pc.Index(host=desc["host"]) if desc.get("host") else pc.Index(index_name)
        stats = _as_dict(await asyncio.to_thread(index.describe_index_stats))
    except Exception as exc:  # noqa: BLE001 - the class only, never the message
        out(f"Cannot read the index: {type(exc).__name__}")
        return 1

    all_ns = _as_dict(stats.get("namespaces"))
    user_docs = {n: v for n, v in all_ns.items() if n.startswith(USER_DOCS_PREFIX)}
    out(f"Index dimension {desc.get('dimension')}, metric {desc.get('metric')}, {stats.get('total_vector_count')} vectors, {len(all_ns)} namespaces")
    for name, info in all_ns.items():
        if name not in user_docs:
            out(f"  namespace {name or '(default)'!r}: {int(_as_dict(info).get('vector_count', 0))} vectors")
    if user_docs:
        out(f"  {len(user_docs)} per-document 'user-docs:' namespaces: {sum(int(_as_dict(v).get('vector_count', 0)) for v in user_docs.values())} vectors (documents uploaded through this app)")

    chosen = pick_namespaces(stats, namespaces)
    if not chosen:
        out("No namespace other than the per-document ones to inspect.")
        return 0

    vector: list[float] | None = None
    try:
        if embed is None:
            from app.services.llm.router import LLMRouter

            embed = LLMRouter().embed
        vector = (await embed([query]))[0]
    except Exception as exc:  # noqa: BLE001
        out(f"Cannot embed the query with the app's model ({type(exc).__name__}); showing the stored records only.")

    for ns in chosen:
        label = ns or "(default)"
        out(f"Namespace {label!r}")
        try:
            for line in sample_records(index, ns, sample):
                out(line)
            if vector is not None:
                out(f"  closest to {query!r} with the app's embedding model:")
                for line in search_records(index, ns, vector, top_k):
                    out(line)
        except Exception as exc:  # noqa: BLE001
            out(f"    failed: {type(exc).__name__}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--namespace", action="append", default=[], help="namespace to inspect (repeatable)")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="text to embed and search for")
    parser.add_argument("--sample", type=int, default=3, help="records to describe per namespace")
    parser.add_argument("--top-k", type=int, default=3, help="search results per namespace")
    args = parser.parse_args(argv)

    from app.config import settings

    return asyncio.run(
        inspect(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
            query=args.query,
            namespaces=args.namespace,
            sample=args.sample,
            top_k=args.top_k,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
