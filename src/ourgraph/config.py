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
        env_prefix="FALKORDB_",
        env_file=".env",
        extra="ignore",
    )

    # Connection via URL (preferred) — e.g. falkor://user:pass@host:port
    url: str = Field(default="")

    # Fallback: individual fields (ignored if url is set)
    host: str = Field(default="localhost")
    port: int = Field(default=6379)
    username: str = Field(default="")
    password: str = Field(default="")
    graph_name: str = Field(default="ourgraph")


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OLLAMA_",
        env_file=".env",
        extra="ignore",
    )

    base_url: str = Field(default="http://localhost:11434/v1")
    llm_model: str = Field(default="phi3.5")
    llm_small_model: str = Field(default="phi3.5")
    embedding_model: str = Field(default="nomic-embed-text")
    embedding_dim: int = Field(default=768)


class VnstockSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VNSTOCK_",
        env_file=".env",
        extra="ignore",
    )

    source: str = Field(default="KBS")
    api_delay: float = Field(default=0.0)
    api_key: str = Field(default="")

    @property
    def effective_delay(self) -> float:
        """Return the per-API-call delay based on API tier.

        With an API key:  60 req/min → 1.5s per call (conservative).
        Without a key:    20 req/min → 4.0s per call.
        """
        if self.api_delay > 0:
            return self.api_delay
        if self.api_key:
            return 1.5
        return 4.0

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PIPELINE_",
        env_file=".env",
        extra="ignore",
    )

    batch_size: int = Field(default=5)
    batch_delay: float = Field(default=10.0)
    financial_quarters: int = Field(default=8)


class SchedulerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_",
        env_file=".env",
        extra="ignore",
    )

    cron: str = Field(default="0 7 * * 1-5")


class GraphitiSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GRAPHITI_",
        env_file=".env",
        extra="ignore",
    )

    semaphore_limit: int = Field(default=2)


class TigerDataSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TIGER_",
        env_file=".env",
        extra="ignore",
    )

    url: str = Field(default="")
    api_key: str = Field(default="")


class MacroSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MACRO_",
        env_file=".env",
        extra="ignore",
    )

    # Which sources to enable (comma-separated list)
    sources: str = Field(default="worldbank,imf,yfinance")

    # Date range for historical data
    start_year: int = Field(default=2010)

    # yfinance specific
    yfinance_commodities: str = Field(
        default="GC=F,CL=F,SI=F,HG=F,^VIX,^GSPC",
    )
    yfinance_indices: str = Field(
        default="^HSI,000001.SS,^SETI,DX-Y.NYB",
    )

    # World Bank specific
    worldbank_vn_indicators: str = Field(
        default=(
            "NY.GDP.MKTP.CD,"
            "NY.GDP.MKTP.KD.ZG,"
            "FP.CPI.TOTL.ZG,"
            "PA.NUS.FCRF,"
            "SL.UEM.TOTL.ZS,"
            "FM.LBL.MQMY.CN,"
            "BX.KLT.DINV.CD.WD,"
            "NE.IMP.GNFS.CD,"
            "NE.EXP.GNFS.CD,"
            "NV.IND.TOTL.ZS"
        ),
    )

    # IMF specific
    imf_vn_indicators: str = Field(
        default="PCPI_IX,ENDE_XDC_USD_RATE,FM_LBL_MQMY_CN,FR_INR_LR",
    )


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = Field(default="INFO")

    falkordb: FalkorDBSettings = Field(default_factory=FalkorDBSettings)
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    vnstock: VnstockSettings = Field(default_factory=VnstockSettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    tiger_data: TigerDataSettings = Field(default_factory=TigerDataSettings)
    graphiti: GraphitiSettings = Field(default_factory=GraphitiSettings)
    macro: MacroSettings = Field(default_factory=MacroSettings)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return the singleton settings object (cached after first call)."""
    settings = AppSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    return settings
