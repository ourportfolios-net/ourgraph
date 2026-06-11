# Session 3: LLM Provider Abstraction Layer

## Objective
Build a provider-agnostic LLM abstraction that supports any LLM (OpenAI, Anthropic, Google, Ollama, vLLM, etc.) via a common interface.

## Context
Currently, the system uses Ollama via OpenAI-compatible API through graphiti-core's `OpenAIGenericClient`. This is limiting. We need a proper abstraction layer.

## Tasks

### 1. Create LLM Provider Base Class
**File**: `src/ourgraph/llm/provider.py`

Create an abstract base class `LLMProvider` with methods:
- `chat(messages: list[dict], **kwargs)` → `str | dict`
- `embed(texts: list[str], **kwargs)` → `list[list[float]]`
- `rerank(query: str, documents: list[str], **kwargs)` → `list[float]`
- Support both sync and async variants

### 2. Implement Concrete Providers

**File**: `src/ourgraph/llm/openai_provider.py`
- Use OpenAI Python SDK
- Support `api_key`, `base_url`, `model` configuration
- Implement `chat()`, `embed()`, `rerank()`

**File**: `src/ourgraph/llm/anthropic_provider.py`
- Use Anthropic Python SDK
- Support Claude models (Opus, Sonnet, Haiku)
- Implement `chat()` (no embeddings from Anthropic - use OpenAI-compatible endpoint or fallback)

**File**: `src/ourgraph/llm/ollama_provider.py`
- Use httpx or requests to call Ollama's OpenAI-compatible endpoints
- `/v1/chat/completions` for chat
- `/v1/embeddings` for embeddings
- Implement rerank via cross-encoder model

**File**: `src/ourgraph/llm/generic_openai_provider.py`
- For any OpenAI-compatible API (OpenRouter, Together AI, etc.)
- Reuse OpenAI SDK with custom `base_url`

### 3. Update Factory Pattern
**File**: `src/ourgraph/llm/factory.py` (modify)

Update to:
- Accept provider name from config: `LLM_PROVIDER=ollama|openai|anthropic|generic`
- Return appropriate provider instance
- Maintain backward compatibility with existing Graphiti integration

### 4. Update Graphiti Client
**File**: `src/ourgraph/graphiti_layer/client.py` (modify)

- Accept any `LLMProvider` instance
- Adapt Graphiti's expected interface to our abstraction
- Might need adapter classes: `GraphitiLLMAdapter`, `GraphitiEmbedderAdapter`

### 5. Configuration Updates
**File**: `src/ourgraph/config.py` (modify)

Add to `OllamaSettings` or create new `LLMSettings`:
```python
class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore")
    
    provider: str = Field(default="ollama")  # ollama, openai, anthropic, generic
    api_key: str = Field(default="")
    base_url: str = Field(default="http://localhost:11434/v1")
    chat_model: str = Field(default="phi3.5")
    embedding_model: str = Field(default="nomic-embed-text")
    embedding_dim: int = Field(default=768)
    rerank_model: str = Field(default="phi3.5")
```

### 6. Tests
**File**: `tests/test_llm_providers.py` (new)

- Test each provider in isolation
- Test factory creates correct provider
- Mock HTTP calls for unit tests
- Integration test with Ollama (if available)

## Acceptance Criteria
- [ ] Can switch LLM provider by changing `LLM_PROVIDER` env var
- [ ] OpenAI API works with `LLM_PROVIDER=openai` + `LLM_API_KEY=sk-...`
- [ ] Anthropic API works with `LLM_PROVIDER=anthropic` + `LLM_API_KEY=...`
- [ ] Ollama still works as default (backward compatible)
- [ ] Graphiti integration works with any provider
- [ ] All tests pass: `pytest tests/test_llm_providers.py -v`

## CLI Testing
```bash
# Test with Ollama (default)
ourgraph query "What is HPG?"

# Test with OpenAI (set env vars)
LLM_PROVIDER=openai LLM_API_KEY=sk-... ourgraph query "What is HPG?"

# Test with Anthropic
LLM_PROVIDER=anthropic LLM_API_KEY=sk-... ourgraph query "What is HPG?"
```

## Dependencies
- openai >= 2.0.0 (already in pyproject.toml)
- anthropic >= 0.50.0 (add to pyproject.toml)
- httpx (already available)

## Notes
- Keep "extremely free" in mind: Ollama should remain the default and primary recommendation
- Anthropic/OpenAI support is for users who want cloud models
- All providers should work with Graphiti's extraction and search pipelines
