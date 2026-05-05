"""Tests for configuration loading."""



from ourgraph.config import (
    AppSettings,
    FalkorDBSettings,
    OllamaSettings,
    PipelineSettings,
)


def test_falkordb_defaults():
    s = FalkorDBSettings()
    assert s.host == "localhost"
    assert s.port == 6379
    assert s.graph_name == "ourgraph"


def test_ollama_defaults():
    s = OllamaSettings()
    assert "11434" in s.base_url
    assert s.embedding_dim == 768


def test_pipeline_defaults():
    s = PipelineSettings()
    assert s.batch_size > 0
    assert s.batch_delay >= 0


def test_app_settings_env_override(monkeypatch):
    monkeypatch.setenv("FALKORDB_HOST", "myhost")
    monkeypatch.setenv("FALKORDB_PORT", "7777")
    monkeypatch.setenv("FALKORDB_GRAPH_NAME", "mygraph")

    s = FalkorDBSettings()
    assert s.host == "myhost"
    assert s.port == 7777
    assert s.graph_name == "mygraph"


def test_full_app_settings_composition():
    s = AppSettings()
    assert s.falkordb is not None
    assert s.ollama is not None
    assert s.supabase is not None
    assert s.pipeline is not None
    assert s.scheduler is not None
    assert s.graphiti is not None
