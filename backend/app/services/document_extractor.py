from __future__ import annotations

import asyncio
import typing
from io import BytesIO

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    WordFormatOption,
)


class DocumentExtractionError(Exception):
    """Raised when document extraction via Docling fails."""
    pass


class DocumentExtractor:
    """Extracts text/markdown from documents using IBM Docling."""

    def __init__(self) -> None:
        """Initializes DocumentExtractor with PDF and DOCX pipeline options."""
        pdf_opts = PdfPipelineOptions()
        pdf_opts.do_table_structure = True
        pdf_opts.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        )

        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_opts),
                InputFormat.DOCX: WordFormatOption(),
            },
        )

    async def extract_to_markdown(self, file_source: bytes | typing.BinaryIO, filename: str) -> str:
        """Extracts markdown from a PDF or DOCX file.

        Args:
            file_source: Raw bytes or file-like object of the uploaded file.
            filename: Name of the uploaded file including extension.

        Returns:
            Extracted markdown string.

        Raises:
            ValueError: If file format is not PDF or DOCX.
            DocumentExtractionError: If Docling extraction/conversion fails.
        """
        ext = filename.lower().split(".")[-1]
        if ext not in ("pdf", "docx"):
            raise ValueError(
                f"Unsupported file type: {ext}. Only PDF and DOCX are supported."
            )

        def _convert() -> str:
            try:
                if not isinstance(file_source, bytes) and hasattr(file_source, "seek"):
                    file_source.seek(0)
                stream_obj = BytesIO(file_source) if isinstance(file_source, bytes) else file_source
                stream = DocumentStream(name=filename, stream=stream_obj)
                result = self.converter.convert(stream)
                return result.document.export_to_markdown()
            except Exception as exc:
                raise DocumentExtractionError(
                    f"Failed to extract document '{filename}': {exc}"
                ) from exc

        loop = asyncio.get_running_loop()
        markdown_text = await loop.run_in_executor(None, _convert)

        return markdown_text

