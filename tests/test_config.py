"""Tests for configuration loading."""

from __future__ import annotations

from ourgraph.config import (
    AppSettings,
    FalkorDBSettings,
    OllamaSettings,
    PipelineSettings,
)

DEFAULT_FALKOR_PORT = 6379
DEFAULT_EMBED_DIM = 768
OVERRIDE_FALKOR_PORT = 7777


def _expect(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_falkordb_defaults() -> None:
    s = FalkorDBSettings()
    _expect(s.host == "localhost", "Expected default FalkorDB host")
    _expect(s.port == DEFAULT_FALKOR_PORT, "Expected default FalkorDB port")
    _expect(s.graph_name == "ourgraph", "Expected default graph name")


def test_ollama_defaults() -> None:
    s = OllamaSettings()
    _expect("11434" in s.base_url, "Expected default Ollama port in base URL")
    _expect(s.embedding_dim == DEFAULT_EMBED_DIM, "Expected default embedding dim")


def test_pipeline_defaults() -> None:
    s = PipelineSettings()
    _expect(s.batch_size > 0, "Expected positive batch size")
    _expect(s.batch_delay >= 0, "Expected non-negative batch delay")


def test_app_settings_env_override(monkeypatch: object) -> None:
    setenv = monkeypatch.setenv
    setenv("FALKORDB_HOST", "myhost")
    setenv("FALKORDB_PORT", str(OVERRIDE_FALKOR_PORT))
    setenv("FALKORDB_GRAPH_NAME", "mygraph")

    s = FalkorDBSettings()
    _expect(s.host == "myhost", "Expected overridden host")
    _expect(s.port == OVERRIDE_FALKOR_PORT, "Expected overridden port")
    _expect(s.graph_name == "mygraph", "Expected overridden graph name")


def test_full_app_settings_composition() -> None:
    s = AppSettings()
    _expect(s.falkordb is not None, "Expected falkordb settings")
    _expect(s.ollama is not None, "Expected ollama settings")
    _expect(s.supabase is not None, "Expected supabase settings")
    _expect(s.pipeline is not None, "Expected pipeline settings")
    _expect(s.scheduler is not None, "Expected scheduler settings")
    _expect(s.graphiti is not None, "Expected graphiti settings")
