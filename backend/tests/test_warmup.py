from __future__ import annotations

import logging
from unittest.mock import MagicMock

from app.config import Settings, settings
from app.main import app, lifespan
from app.services import warmup


async def test_warm_models_loads_the_extractor_and_the_masker(monkeypatch):
    extractor = MagicMock()
    get_extractor = MagicMock(return_value=extractor)
    get_masker = MagicMock()
    monkeypatch.setattr("app.api.documents.get_document_extractor", get_extractor)
    monkeypatch.setattr("app.services.privacy.ner_masker.get_ner_masker", get_masker)

    await warmup.warm_models()

    extractor.warm_up.assert_called_once_with()
    get_masker.assert_called_once_with()


async def test_a_failing_step_is_logged_and_does_not_stop_the_next(monkeypatch, caplog):
    extractor = MagicMock()
    extractor.warm_up.side_effect = RuntimeError("models not cached")
    get_masker = MagicMock()
    monkeypatch.setattr("app.api.documents.get_document_extractor", lambda: extractor)
    monkeypatch.setattr("app.services.privacy.ner_masker.get_ner_masker", get_masker)

    with caplog.at_level(logging.WARNING, logger=warmup.logger.name):
        await warmup.warm_models()  # must not raise

    assert "models not cached" in caplog.text
    get_masker.assert_called_once_with()


def test_warm_up_is_off_by_default():
    assert Settings(_env_file=None).warm_models_on_startup is False


async def test_lifespan_warms_models_only_when_enabled(monkeypatch):
    calls: list[str] = []

    async def fake_warm_models() -> None:
        calls.append("warm")

    monkeypatch.setattr("app.services.warmup.warm_models", fake_warm_models)

    monkeypatch.setattr(settings, "warm_models_on_startup", False)
    async with lifespan(app):
        pass
    assert calls == []

    monkeypatch.setattr(settings, "warm_models_on_startup", True)
    async with lifespan(app):
        pass
    assert calls == ["warm"]
