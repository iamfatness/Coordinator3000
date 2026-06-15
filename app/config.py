"""Centralized configuration loaded from environment / `.env`.

Every tunable lives here so the rest of the codebase never reads `os.environ`
directly. Values are validated once at startup via pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- GitHub --------------------------------------------------------------
    github_token: str = ""
    github_webhook_secret: str = ""
    github_api_url: str = "https://api.github.com"
    ai_task_label: str = "ai-task"

    # ---- LLM --------------------------------------------------------------
    # Default provider + model used by every agent unless overridden per-role.
    # Provider: "anthropic" (Claude), "openai" (Codex/GPT), or "xai" (Grok).
    llm_provider: str = "anthropic"
    llm_model: str = "claude-opus-4-8"
    llm_max_tokens: int = 16000
    llm_timeout: float = 600.0
    llm_max_retries: int = 4

    # Per-role overrides. Empty = use the default provider + model. Each accepts
    # a bare model ("claude-opus-4-8") or "provider:model" so you can mix AIs,
    # e.g. ORCHESTRATOR_MODEL=anthropic:claude-opus-4-8, CODER_MODEL=openai:gpt-5-codex,
    # REVIEWER_MODEL=xai:grok-4.
    orchestrator_model: str = ""
    coder_model: str = ""
    reviewer_model: str = ""

    # Provider API keys.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    xai_api_key: str = ""

    # ---- Postgres checkpointer ----------------------------------------------
    database_url: str = "postgresql://postgres:postgres@localhost:5432/coordinator"

    # ---- Orchestration ------------------------------------------------------
    max_iterations: int = 4
    workspace_root: str = "/tmp/coordinator-workspaces"
    worker_concurrency: int = 2
    require_human_approval: bool = False

    # Admin token guarding board-management + token-minting endpoints. If empty,
    # those endpoints are open (dev only) — set this before exposing publicly.
    admin_token: str = ""

    # ---- Sandbox ------------------------------------------------------------
    sandbox_mode: str = "subprocess"  # "subprocess" | "docker"
    sandbox_timeout: int = 300
    sandbox_docker_image: str = "python:3.12-slim"

    # ---- Git identity -------------------------------------------------------
    git_author_name: str = "Coordinator3000"
    git_author_email: str = "bot@coordinator3000.local"

    # ---- App ----------------------------------------------------------------
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of the resolved settings."""
    return Settings()
