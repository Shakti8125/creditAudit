from __future__ import annotations

import pytest
from app.services.chunker import MarkdownChunker


def test_markdown_chunker_table_preservation():
    """Verify Markdown tables with sub-8-word rows are kept intact and not dropped."""
    chunker = MarkdownChunker(chunk_size=1000, overlap=100)

    doc = (
        "# Model Validation Report\n\n"
        "## Performance Metrics\n\n"
        "The following table summarizes the quantitative validation results:\n\n"
        "| Metric | Benchmark | Value | Status |\n"
        "|---|---|---|---|\n"
        "| AUC | >= 0.70 | 0.82 | Pass |\n"
        "| Gini | >= 0.40 | 0.64 | Pass |\n"
        "| KS | >= 30.0 | 38.5 | Pass |\n"
        "| PSI | <= 0.25 | 0.08 | Pass |\n\n"
        "All metrics meet the regulatory requirements set by CBUAE MMG."
    )

    chunks = chunker.chunk(doc)

    # Verify table chunk exists
    table_chunks = [c for c in chunks if "| Metric | Benchmark |" in c]
    assert len(table_chunks) == 1, "Markdown table was dropped or fragmented!"
    table_chunk = table_chunks[0]

    # Verify all table rows are preserved
    assert "| AUC | >= 0.70 | 0.82 | Pass |" in table_chunk
    assert "| Gini | >= 0.40 | 0.64 | Pass |" in table_chunk
    assert "| KS | >= 30.0 | 38.5 | Pass |" in table_chunk
    assert "| PSI | <= 0.25 | 0.08 | Pass |" in table_chunk

    # Verify parent header context is prepended
    assert "Model Validation Report > Performance Metrics:" in table_chunk


def test_markdown_chunker_sliding_window_overlap():
    """Verify consecutive chunks have non-zero sliding window overlap."""
    chunk_size = 200
    overlap = 50
    chunker = MarkdownChunker(chunk_size=chunk_size, overlap=overlap)

    long_paragraph = (
        "In credit risk modeling, the Probability of Default represents the likelihood that a borrower will "
        "fail to make required debt payments within a specified horizon. Loss Given Default represents the "
        "percentage of exposure that is lost if the borrower defaults. Exposure at Default is the total value "
        "a bank is exposed to when a loan defaults. Together, PD, LGD, and EAD determine Expected Credit Loss."
    )

    chunks = chunker.chunk(f"# Overview\n\n{long_paragraph}")
    assert len(chunks) > 1, "Long text should have produced multiple chunks"

    for c in chunks:
        assert len(c) <= chunk_size + 100, f"Chunk exceeded size bound: {len(c)}"

    # Check overlap between consecutive chunks
    overlap_found = False
    for i in range(len(chunks) - 1):
        words_1 = set(chunks[i].split())
        words_2 = set(chunks[i + 1].split())
        common = words_1.intersection(words_2)
        # Exclude header words
        common_non_header = [w for w in common if w not in ("#", "Overview:", "Overview")]
        if len(common_non_header) >= 2:
            overlap_found = True
            break

    assert overlap_found, "Consecutive chunks lacked overlapping content!"


def test_markdown_chunker_never_splits_on_number_commas():
    """Verify lookbehind sentence splitting does not split formatted numbers like 1,250,000."""
    chunker = MarkdownChunker(chunk_size=1000, overlap=100)

    text = (
        "# Financial Summary\n\n"
        "The total facility exposure was AED 1,250,000.50 at default date. "
        "The recovery amount was AED 500,000.00 with 150,000 in direct legal expenses. "
        "Final net loss was evaluated at 600,000 AED."
    )

    chunks = chunker.chunk(text)
    assert len(chunks) == 1
    assert "1,250,000.50" in chunks[0]
    assert "500,000.00" in chunks[0]
    assert "150,000" in chunks[0]
