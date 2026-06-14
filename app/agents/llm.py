"""LLM factory — provider-pluggable, Claude by default.

Every agent (orchestrator / coder / reviewer) is built through `build_llm(role)`.
The default provider is Anthropic Claude (``claude-opus-4-8``), the most capable
model and a strong fit for multi-step agentic tool use. Because LangGraph speaks
to any tool-calling chat model, you can run individual agents on a different AI
by setting a per-role override in the form ``provider:model`` — for example:

    CODER_MODEL=openai:gpt-5-codex      # Codex
    REVIEWER_MODEL=xai:grok-4           # Grok

Supported providers: ``anthropic`` (Claude), ``openai`` (Codex/GPT), ``xai`` (Grok).
The OpenAI and xAI integrations are imported lazily, so a Claude-only deployment
doesn't need them installed.

Note: Claude Opus 4.8 rejects ``temperature`` / ``top_p`` / ``top_k`` (they 400),
so we never set sampling params on the Anthropic path.
"""
from __future__ import annotations

import logging

from langchain_anthropic import ChatAnthropic

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

_ROLE_FIELD = {
    "orchestrator": "orchestrator_model",
    "coder": "coder_model",
    "reviewer": "reviewer_model",
}


def _resolve(role: str, cfg: Settings) -> tuple[str, str]:
    """Return (provider, model) for a role, honoring per-role overrides."""
    spec = getattr(cfg, _ROLE_FIELD.get(role, ""), "") if role in _ROLE_FIELD else ""
    if not spec:
        return cfg.llm_provider.lower(), cfg.llm_model
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return provider.strip().lower(), model.strip()
    return cfg.llm_provider.lower(), spec.strip()


def build_llm(role: str = "default"):
    """Construct the chat model for the given agent role."""
    cfg = get_settings()
    provider, model = _resolve(role, cfg)
    log.debug("building llm for role=%s provider=%s model=%s", role, provider, model)

    if provider == "anthropic":
        kwargs: dict = {
            "model": model,
            "max_tokens": cfg.llm_max_tokens,
            "default_request_timeout": cfg.llm_timeout,
            "max_retries": cfg.llm_max_retries,
            # To enable adaptive thinking + effort (recommended for harder runs,
            # if your langchain-anthropic supports it):
            #   "thinking": {"type": "adaptive"},
            #   "model_kwargs": {"output_config": {"effort": "high"}},
        }
        if cfg.anthropic_api_key:
            kwargs["anthropic_api_key"] = cfg.anthropic_api_key
        return ChatAnthropic(**kwargs)

    if provider == "openai":
        from langchain_openai import ChatOpenAI  # lazy: optional dependency

        kwargs = {
            "model": model,
            "max_tokens": cfg.llm_max_tokens,
            "timeout": cfg.llm_timeout,
            "max_retries": cfg.llm_max_retries,
        }
        if cfg.openai_api_key:
            kwargs["api_key"] = cfg.openai_api_key
        return ChatOpenAI(**kwargs)

    if provider in ("xai", "grok"):
        from langchain_xai import ChatXAI  # lazy: optional dependency

        kwargs = {
            "model": model,
            "max_tokens": cfg.llm_max_tokens,
            "timeout": cfg.llm_timeout,
            "max_retries": cfg.llm_max_retries,
        }
        if cfg.xai_api_key:
            kwargs["api_key"] = cfg.xai_api_key
        return ChatXAI(**kwargs)

    raise ValueError(
        f"unknown LLM provider {provider!r} (expected anthropic | openai | xai)"
    )
