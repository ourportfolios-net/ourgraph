"""Central configuration via pydantic-settings.

All values come from environment variables / .env file.
Nothing is hardcoded here — only defaults that are safe to change.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FalkorDBSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FALKORDB_", env_file=".env", extra="ignore",
    )

    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    username: str = Field(default="")
    password: str = Field(default="")
    graph_name: str = Field(default="ourgraph")


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_", env_file=".env", extra="ignore",
    )

    base_url: str = Field(default="http://localhost:11434/v1")
    llm_model: str = Field(default="phi3.5")
    llm_small_model: str = Field(default="phi3.5")
    embedding_model: str = Field(default="nomic-embed-text")
    embedding_dim: int = Field(default=768)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_db_url: str = Field(default="")
    neon_db_url: str = Field(default="")


class VnstockSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VNSTOCK_", env_file=".env", extra="ignore",
    )

    source: str = Field(default="KBS")
    api_delay: float = Field(default=1.0)


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_", env_file=".env", extra="ignore",
    )

    batch_size: int = Field(default=5)
    batch_delay: float = Field(default=10.0)
    financial_quarters: int = Field(default=8)


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_", env_file=".env", extra="ignore",
    )

    cron: str = Field(default="0 7 * * 1-5")


class GraphitiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRAPHITI_", env_file=".env", extra="ignore",
    )

    semaphore_limit: int = Field(default=2)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = Field(default="INFO")

    falkordb: FalkorDBSettings = Field(default_factory=FalkorDBSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    supabase: DatabaseSettings = Field(default_factory=DatabaseSettings)
    vnstock: VnstockSettings = Field(default_factory=VnstockSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    graphiti: GraphitiSettings = Field(default_factory=GraphitiSettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the singleton settings object (cached after first call)."""
    settings = AppSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    return settings
