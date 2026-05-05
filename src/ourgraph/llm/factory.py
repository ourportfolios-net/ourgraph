"""LLM and embedder factory.

All models are resolved from config — nothing is hardcoded.
Swap provider by changing env vars, not code.

Currently wires Ollama via the OpenAI-compatible API as documented by Graphiti:
  - Use OpenAIGenericClient (NOT OpenAIClient) for Ollama.
  - Use OpenAIEmbedder with Ollama's /v1/embeddings endpoint.
  - Use OpenAIRerankerClient with Ollama for cross-encoding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

if TYPE_CHECKING:
    from ourgraph.config import OllamaSettings


def build_llm_client(settings: OllamaSettings) -> OpenAIGenericClient:
    """Build an LLM client backed by Ollama via its OpenAI-compatible endpoint.

    OpenAIGenericClient uses /v1/chat/completions with response_format for
    structured outputs — the endpoint that Ollama actually supports.
    """
    config = LLMConfig(
        api_key="ollama",  # Ollama ignores this, but the SDK requires a non-empty value
        model=settings.llm_model,
        small_model=settings.llm_small_model,
        base_url=settings.base_url,
    )
    return OpenAIGenericClient(config=config)


def build_embedder(settings: OllamaSettings) -> OpenAIEmbedder:
    """Build an embedder backed by Ollama's /v1/embeddings endpoint.

    Recommended model: nomic-embed-text (768 dims, fast, good quality).
    Pull it first: ollama pull nomic-embed-text
    """
    config = OpenAIEmbedderConfig(
        api_key="ollama",
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        base_url=settings.base_url,
    )
    return OpenAIEmbedder(config=config)


def build_reranker(
    settings: OllamaSettings,
) -> OpenAIRerankerClient:
    """Build a cross-encoder reranker backed by Ollama.

    The reranker improves GraphRAG search result quality by re-scoring
    candidates after the initial hybrid retrieval pass.
    """
    config = LLMConfig(
        api_key="ollama",
        model=settings.llm_model,
        base_url=settings.base_url,
    )
    return OpenAIRerankerClient(config=config)
