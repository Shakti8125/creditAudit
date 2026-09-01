from __future__ import annotations

import re
from typing import List


class MarkdownChunker:
    """Header-aware markdown chunker that preserves privacy tokens, financial numbers, and tables."""

    def __init__(self, chunk_size: int = 2400, overlap: int = 400) -> None:
        """Initializes MarkdownChunker with chunk size and sliding window overlap.

        Args:
            chunk_size: Maximum character length for each chunk.
            overlap: Character overlap between consecutive chunks.
        """
        self.chunk_size = chunk_size
        self.overlap = min(overlap, chunk_size - 1) if chunk_size > 1 else 0

    def _is_table_line(self, line: str) -> bool:
        """Checks if a given line belongs to a markdown table."""
        s = line.strip()
        return bool(s) and ((s.startswith("|") and s.endswith("|")) or s.count("|") >= 2)

    def _split_text(self, text: str, delimiters: List[str]) -> List[str]:
        """Recursively splits text using the provided delimiters and accumulates chunks with overlap.

        Preserves financial numbers (never splits on commas).
        Preserves bracketed tokens ([BANK_1], [ORG_1]).
        Preserves sentence punctuation and spacing.

        Args:
            text: Input text to split.
            delimiters: Ordered list of delimiters for hierarchical splitting.

        Returns:
            List of accumulated text chunks within chunk_size.
        """
        clean_text = text.strip()
        if not clean_text:
            return []

        if len(clean_text) <= self.chunk_size:
            return [clean_text]

        if not delimiters:
            return self._hard_split(clean_text)

        delimiter = delimiters[0]

        # Split text according to delimiter type while preserving punctuation/formatting
        if delimiter == "\n\n":
            raw_parts = [p.strip() for p in clean_text.split("\n\n") if p.strip()]
            separator = "\n\n"
        elif delimiter == "\n":
            raw_parts = [p.strip() for p in clean_text.split("\n") if p.strip()]
            separator = "\n"
        elif delimiter == ". ":
            raw_parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", clean_text) if p.strip()]
            separator = " "
        elif delimiter == " ":
            raw_parts = [p.strip() for p in clean_text.split(" ") if p.strip()]
            separator = " "
        else:
            raw_parts = [p.strip() for p in clean_text.split(delimiter) if p.strip()]
            separator = delimiter

        if len(raw_parts) <= 1:
            if delimiters[1:]:
                return self._split_text(clean_text, delimiters[1:])
            if len(clean_text) > self.chunk_size:
                return self._hard_split(clean_text)
            return raw_parts

        units: List[str] = []
        for part in raw_parts:
            if len(part) > self.chunk_size and delimiters[1:]:
                sub_units = self._split_text(part, delimiters[1:])
                units.extend(sub_units)
            else:
                units.append(part)

        return self._accumulate_with_overlap(units, separator)

    def _hard_split(self, text: str) -> List[str]:
        """Split text into chunk_size windows with overlap, dropping tiny trailing fragments.

        Used as a final fallback when no finer-grained delimiter is available.

        Args:
            text: Text to split.

        Returns:
            List of pieces each no longer than chunk_size.
        """
        clean_text = text.strip()
        if not clean_text:
            return []
        if len(clean_text) <= self.chunk_size:
            return [clean_text]

        step = max(self.chunk_size - self.overlap, 1)
        pieces: List[str] = []
        start = 0
        text_len = len(clean_text)
        while start < text_len:
            piece = clean_text[start : start + self.chunk_size].strip()
            end = start + self.chunk_size
            if end >= text_len:
                if len(piece) > self.overlap:
                    pieces.append(piece)
                break
            if piece:
                pieces.append(piece)
            start += step
        return pieces

    def _accumulate_with_overlap(self, units: List[str], separator: str) -> List[str]:
        """Accumulates atomic text units into chunks up to self.chunk_size with sliding window overlap.

        Args:
            units: List of atomic text pieces.
            separator: Delimiter to join units with.

        Returns:
            List of accumulated chunk strings.
        """
        chunks: List[str] = []
        current_units: List[str] = []
        current_len = 0

        for unit in units:
            unit_str = unit.strip()
            if not unit_str:
                continue

            sep_len = len(separator) if current_units else 0
            added_len = len(unit_str) + sep_len

            if current_units and (current_len + added_len > self.chunk_size):
                chunk_str = separator.join(current_units).strip()
                if chunk_str:
                    chunks.append(chunk_str)

                overlap_units: List[str] = []
                overlap_len = 0
                if self.overlap > 0:
                    for u in reversed(current_units):
                        u_sep_len = len(separator) if overlap_units else 0
                        overlap_units.insert(0, u)
                        overlap_len += len(u) + u_sep_len
                        if overlap_len >= self.overlap:
                            break

                while overlap_units and (
                    sum(len(u) for u in overlap_units)
                    + (len(separator) * len(overlap_units))
                    + len(unit_str)
                    > self.chunk_size
                ):
                    overlap_units.pop(0)

                current_units = list(overlap_units)
                current_len = sum(len(u) for u in current_units) + (
                    len(separator) * (len(current_units) - 1) if len(current_units) > 1 else 0
                )

                sep_len = len(separator) if current_units else 0
                added_len = len(unit_str) + sep_len

            current_units.append(unit_str)
            current_len += added_len

        if current_units:
            chunk_str = separator.join(current_units).strip()
            if chunk_str and (not chunks or chunk_str != chunks[-1]):
                chunks.append(chunk_str)

        return chunks

    def chunk(self, text: str) -> List[str]:
        """Chunks markdown text into pieces, prepending parent header context.

        Markdown tables (| ... |) are treated as atomic chunks and exempt from the
        8-word filter to preserve financial metrics and validation tables.
        Paragraph breaks (double newlines) are preserved.

        Args:
            text: Raw or masked markdown document text.

        Returns:
            List of formatted chunk strings with parent header contexts.
        """
        lines = text.split("\n")
        chunks: List[str] = []

        current_headers = {i: "" for i in range(1, 7)}
        current_section_lines: List[str] = []

        def _get_header_context() -> str:
            context = [current_headers[i] for i in range(1, 7) if current_headers[i]]
            if context:
                return " > ".join(context) + ":\n"
            return ""

        def _process_section() -> None:
            if not current_section_lines:
                return

            header_context = _get_header_context()

            blocks: List[tuple[str, List[str]]] = []
            current_block_type: str | None = None
            current_block_lines: List[str] = []

            for line in current_section_lines:
                line_type = "table" if self._is_table_line(line) else "text"

                if current_block_type is None:
                    current_block_type = line_type
                    current_block_lines.append(line)
                elif line_type == current_block_type:
                    current_block_lines.append(line)
                else:
                    if current_block_lines:
                        blocks.append((current_block_type, list(current_block_lines)))
                    current_block_type = line_type
                    current_block_lines = [line]

            if current_block_lines and current_block_type is not None:
                blocks.append((current_block_type, list(current_block_lines)))

            for block_type, block_lines in blocks:
                if block_type == "table":
                    table_content = "\n".join(block_lines).strip()
                    if table_content:
                        chunks.append(header_context + table_content)
                else:
                    text_content = "\n".join(block_lines).strip()
                    if not text_content:
                        continue

                    delims = ["\n\n", "\n", ". ", " "]
                    raw_chunks = self._split_text(text_content, delims)

                    for rc in raw_chunks:
                        rc_clean = rc.strip()
                        if len(rc_clean.split()) >= 8:
                            chunks.append(header_context + rc_clean)

            current_section_lines.clear()

        for line in lines:
            header_match = re.match(r"^(#{1,6})\s+(.*)", line.strip())
            if header_match:
                _process_section()
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                current_headers[level] = title
                for i in range(level + 1, 7):
                    current_headers[i] = ""
            else:
                current_section_lines.append(line)

        _process_section()

        return chunks

