"""Tests for the read-only Pinecone inspection script (``scripts/diag/pinecone_inspect.py``).

It is run by the owner against an index that holds records the app did not write, so what
matters is that it only reads, groups the per-document namespaces, shows what an unknown
namespace holds, and never prints a key or an error message.
"""

from __future__ import annotations

import asyncio
from typing import Any

from scripts.diag import pinecone_inspect as inspector

FAKE_KEY = "pcsk_FAKEPINECONEKEY"
TENANT = "7d0c5a4e-1111-2222-3333-444455556666"
DOC = "a1b2c3d4-aaaa-bbbb-cccc-ddddeeeeffff"
READ_ONLY = {"describe_index_stats", "list", "fetch", "query"}


class FakeIndex:
    """Index with read methods only: any write or delete raises AttributeError."""

    def __init__(self, list_pages: list[Any]) -> None:
        self.calls: list[str] = []
        self._pages = list_pages

    def describe_index_stats(self) -> dict[str, Any]:
        self.calls.append("describe_index_stats")
        return {
            "total_vector_count": 12,
            "namespaces": {
                "ifrs9": {"vector_count": 9},
                f"user-docs:{TENANT}:{DOC}": {"vector_count": 3},
            },
        }

    def list(self, **kwargs: Any):
        self.calls.append("list")
        yield from self._pages

    def fetch(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("fetch")
        return {
            "vectors": {
                "ifrs9-0": {
                    "values": [0.1] * 1024,
                    "metadata": {"text": "Impairment: 5.5.1 An entity shall recognise a loss allowance.", "chapter": "5"},
                }
            }
        }

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append("query")
        return {
            "matches": [
                {"id": "ifrs9-0", "score": 0.83, "metadata": {"text": "Impairment: 5.5.1 An entity shall recognise a loss allowance.", "source": "IFRS 9", "section": "5.5.1"}}
            ]
        }


class FakeClient:
    def __init__(self, index: FakeIndex, describe_error: Exception | None = None) -> None:
        self.index = index
        self.describe_error = describe_error

    def describe_index(self, name: str) -> dict[str, Any]:
        if self.describe_error:
            raise self.describe_error
        return {"dimension": 1024, "metric": "cosine", "host": "fake-host"}

    def Index(self, **kwargs: Any) -> FakeIndex:  # noqa: N802 - mirrors the SDK
        return self.index


async def _embed(texts: list[str]) -> list[list[float]]:
    return [[0.2] * 1024 for _ in texts]


def _run(index: FakeIndex, *, embed=_embed, describe_error: Exception | None = None, namespaces: list[str] | None = None):
    lines: list[str] = []
    code = asyncio.run(
        inspector.inspect(
            api_key=FAKE_KEY,
            index_name="fake-index",
            query="ECL staging",
            namespaces=namespaces or [],
            sample=2,
            top_k=3,
            out=lines.append,
            client_factory=lambda key: FakeClient(index, describe_error),
            embed=embed,
        )
    )
    return code, "\n".join(lines)


def test_shows_the_unknown_namespace_and_groups_the_per_document_ones():
    index = FakeIndex([["ifrs9-0"]])
    code, text = _run(index)
    assert code == 0
    assert "namespace 'ifrs9': 9 vectors" in text
    assert "1 per-document 'user-docs:' namespaces: 3 vectors" in text
    assert TENANT not in text and DOC not in text, "tenant and document ids must not be listed"
    assert "vector length 1024" in text
    assert "metadata chapter:str, text:str" in text
    assert "score 0.830" in text and "IFRS 9" in text and "5.5.1" in text


def test_only_reads_and_inspects_the_unknown_namespace_by_default():
    index = FakeIndex([["ifrs9-0"]])
    _run(index)
    assert set(index.calls) <= READ_ONLY
    assert {"describe_index_stats", "list", "fetch", "query"} <= set(index.calls)


def test_accepts_a_list_page_object_of_newer_sdks():
    class Vec:
        id = "ifrs9-0"

    class Page:
        vectors = [Vec()]

    code, text = _run(FakeIndex([Page()]))
    assert code == 0 and "id ifrs9-0" in text


def test_an_unreadable_index_prints_the_class_only():
    code, text = _run(FakeIndex([]), describe_error=PermissionError(f"bad key {FAKE_KEY}"))
    assert code == 1
    assert "PermissionError" in text
    assert FAKE_KEY not in text


def test_a_failing_embedding_still_shows_the_stored_records():
    async def broken(texts: list[str]):
        raise RuntimeError(f"nvapi key {FAKE_KEY} rejected")

    code, text = _run(FakeIndex([["ifrs9-0"]]), embed=broken)
    assert code == 0
    assert "RuntimeError" in text and FAKE_KEY not in text
    assert "vector length 1024" in text and "score" not in text


def test_missing_configuration_is_reported():
    lines: list[str] = []
    code = asyncio.run(
        inspector.inspect(api_key="", index_name="", query="q", namespaces=[], sample=1, top_k=1, out=lines.append)
    )
    assert code == 1 and "not set" in lines[0]
