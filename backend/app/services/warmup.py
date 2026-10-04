"""Loads the heavy models once at startup (QA-026: the first upload took about 38 s)."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)


def _warm_extractor() -> None:
    from app.api.documents import get_document_extractor

    get_document_extractor().warm_up()


def _warm_masker() -> None:
    from app.services.privacy.ner_masker import get_ner_masker

    get_ner_masker()


_STEPS: tuple[tuple[str, Callable[[], None]], ...] = (
    ("document extractor (Docling)", _warm_extractor),
    ("privacy masker (spaCy and Presidio)", _warm_masker),
)


async def warm_models() -> None:
    """Loads each model in turn. A failing step is logged and skipped, never raised.

    A step that fails here is not lost work: the model then loads lazily on first use,
    exactly as it did before warm-up existed.
    """
    for name, step in _STEPS:
        started = time.perf_counter()
        try:
            await run_in_threadpool(step)
        except Exception as exc:  # noqa: BLE001 - warm-up must never stop the app starting.
            logger.warning(
                "Warm-up of the %s failed after %.1f s; it will load on first use: %s",
                name,
                time.perf_counter() - started,
                exc,
            )
        else:
            logger.info("Warmed the %s in %.1f s", name, time.perf_counter() - started)
