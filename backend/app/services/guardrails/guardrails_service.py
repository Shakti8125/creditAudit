from __future__ import annotations

import logging
import os
from typing import Any

from pydantic import BaseModel, ConfigDict
from nemoguardrails import LLMRails, RailsConfig

logger = logging.getLogger(__name__)


class GuardrailsResult(BaseModel):
    """Schema for NeMo Guardrails execution results."""
    model_config = ConfigDict(from_attributes=True)

    response: str | None = None
    blocked: bool = False
    block_reason: str | None = None
    rail_type: str | None = None


class GuardrailsService:
    """Service wrapping NeMo Guardrails 2.0 with Colang flows."""

    def __init__(self) -> None:
        """Initializes the NeMo Guardrails runtime and wires model credentials."""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config = RailsConfig.from_path(current_dir)

        # Custom actions are auto-discovered from actions.py (via the @action
        # decorators) when the config is loaded from this directory, so there is
        # no need to register them explicitly here.

        # Wire the NVIDIA API key and base URL into the main model configuration.
        from app.config import settings

        nvidia_key = settings.nvidia.api_key
        nvidia_url = settings.nvidia.base_url
        if nvidia_key or nvidia_url:
            for model in config.models:
                if model.engine == "nvidia_ai_endpoints":
                    if nvidia_key:
                        model.parameters["api_key"] = nvidia_key
                    if nvidia_url:
                        model.parameters["base_url"] = nvidia_url

        self.rails = LLMRails(config)


    @staticmethod
    def _extract_content(response: Any) -> str:
        """Extracts text content safely from dict, object, or string responses."""
        if response is None:
            return ""
        if isinstance(response, dict):
            return str(response.get("content", "") or response.get("text", "") or "").strip()
        if isinstance(response, str):
            return response.strip()
        if hasattr(response, "response") and isinstance(response.response, str):
            return response.response.strip()
        if hasattr(response, "content") and isinstance(response.content, str):
            return response.content.strip()
        return str(response).strip()

    async def generate_with_guardrails(
        self,
        prompt: str,
        context: str = "",
        retrieved_contexts: list[str] | None = None,
    ) -> GuardrailsResult:
        """Executes a prompt through NeMo Guardrails with context and retrieved chunks.

        Args:
            prompt: The user input prompt.
            context: Additional context or document string.
            retrieved_contexts: List of retrieved context text chunks.

        Returns:
            GuardrailsResult with the assistant response or block reason.
        """
        try:
            retrieved_list = retrieved_contexts if retrieved_contexts is not None else []
            from app.services.guardrails.actions import (
                check_jailbreak_action,
                check_off_topic_action,
            )

            # Pass retrieved contexts and context string via messages
            context_data = {
                "context": context,
                "retrieved_contexts": retrieved_list,
            }
            messages = [
                {
                    "role": "context",
                    "content": context_data,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]

            try:
                raw_response = await self.rails.generate_async(
                    messages=messages,
                )
            except Exception as e:
                logger.error(f"Guardrails generation error: {str(e)}", exc_info=True)
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason=f"Error executing guardrails: {str(e)}",
                    rail_type="system",
                )

            content = self._extract_content(raw_response)

            # Check for domain refusal / guardrail blocks
            if (
                "I am ModelAudit AI, specialized in credit risk model validation" in content
                and ("cannot help with that topic" in content or "specialized in credit risk" in content)
            ) or content == "I am ModelAudit AI, specialized in credit risk model validation and CBUAE MMG regulatory compliance. I cannot help with that topic.":
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Off-topic query",
                    rail_type="dialog",
                )

            if "I cannot process this request as it violates safety guidelines." in content or "violates safety guidelines" in content:
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Jailbreak attempt detected",
                    rail_type="input",
                )

            if "The generated metrics are inconsistent or out of bounds." in content:
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Inconsistent financial metrics",
                    rail_type="output",
                )

            if "The generated response contains broken placeholders." in content:
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Broken placeholders in output",
                    rail_type="output",
                )

            if (
                "cannot verify this answer against the provided credit documentation" in content
                or "I'm sorry, but I cannot verify this answer against the provided credit documentation." in content
                or "I'm sorry, I can't respond to that." in content
            ):
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Blocked by guardrails (Hallucination detected)",
                    rail_type="output",
                )

            if not content:
                # Empty content means an input rail intercepted generation (e.g.
                # off-topic, jailbreak, or prompt-injection refusal). Inspect the
                # user message to determine which rail blocked it.
                if await check_off_topic_action(context={"user_message": prompt}):
                    return GuardrailsResult(
                        response=None,
                        blocked=True,
                        block_reason="Off-topic query",
                        rail_type="dialog",
                    )
                if not await check_jailbreak_action(context={"user_message": prompt}):
                    return GuardrailsResult(
                        response=None,
                        blocked=True,
                        block_reason="Jailbreak attempt detected",
                        rail_type="input",
                    )
                return GuardrailsResult(
                    response=None,
                    blocked=True,
                    block_reason="Blocked by guardrails (Empty response)",
                    rail_type="unknown",
                )

            return GuardrailsResult(
                response=content,
                blocked=False,
                block_reason=None,
                rail_type=None,
            )


        except Exception as e:
            logger.error(f"Guardrails generation error: {str(e)}", exc_info=True)
            return GuardrailsResult(
                response=None,
                blocked=True,
                block_reason=f"Error executing guardrails: {str(e)}",
                rail_type="system",
            )

