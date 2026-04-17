"""LLM client factory for the Device Agent."""

from __future__ import annotations

import json
import logging
import re

from langchain_openai import AzureChatOpenAI, ChatOpenAI

from src.device_agent.utility.config import utility_config

logger = logging.getLogger(__name__)


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    """Return a configured ChatOpenAI or AzureChatOpenAI instance.

    Uses AzureChatOpenAI if AZURE_OPENAI_ENDPOINT is set in the environment,
    otherwise falls back to standard ChatOpenAI.

    Args:
        temperature: Sampling temperature. 0.0 for deterministic output.

    Returns:
        A ChatOpenAI (or AzureChatOpenAI) instance ready to invoke.

    Raises:
        ValueError: If OPENAI_API_KEY is not set.
    """
    if not utility_config.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set in environment.")

    if utility_config.azure_openai_endpoint:
        logger.debug("Initialising Azure LLM deployment: %s", utility_config.openai_model)
        return AzureChatOpenAI(
            azure_deployment=utility_config.openai_model,
            azure_endpoint=utility_config.azure_openai_endpoint,
            api_version=utility_config.azure_openai_api_version,
            api_key=utility_config.openai_api_key,
            temperature=temperature,
        )

    logger.debug("Initialising LLM model: %s", utility_config.openai_model)
    return ChatOpenAI(
        model=utility_config.openai_model,
        temperature=temperature,
        api_key=utility_config.openai_api_key,
    )


def call_llm_for_json(
    prompt: str,
    temperature: float = 0.0,
) -> dict:
    """Send a prompt to the LLM and parse the JSON response.

    Args:
        prompt:      The prompt to send.
        temperature: Sampling temperature (0.0 = deterministic).

    Returns:
        Parsed JSON dict, or {"__error__": "...", "raw_text": "..."} on failure.
    """
    try:
        llm = get_llm(temperature=temperature)
        response = llm.invoke(prompt)
        text = response.content if hasattr(response, "content") else str(response)
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"(\{(?:.|\n)*\})", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1))
                except Exception:
                    pass
        logger.warning("call_llm_for_json: could not parse JSON from LLM response")
        return {"__error__": "Could not parse JSON from LLM response", "raw_text": text}
    except Exception as exc:
        logger.exception("call_llm_for_json failed")
        return {"__error__": str(exc)}


