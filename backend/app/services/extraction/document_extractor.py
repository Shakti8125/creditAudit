from __future__ import annotations

# Re-export DocumentExtractor from app.services.document_extractor for extraction package compatibility
from app.services.document_extractor import DocumentExtractionError, DocumentExtractor

__all__ = ["DocumentExtractor", "DocumentExtractionError"]
