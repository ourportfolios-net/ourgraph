"""
Graphiti temporal knowledge graph client.

Graphiti sits on top of FalkorDB and adds:
  - Temporal fact management (validity windows)
  - Hybrid search (BM25 + vector + graph)
  - Episode-based ingestion with provenance
  - GraphRAG via the search() API

This module wires Graphiti to:
  - FalkorDB via FalkorDriver (official supported backend)
  - Ollama via OpenAIGenericClient (Ollama's OpenAI-compatible endpoint)
  - nomic-embed-text via OpenAIEmbedder (Ollama embeddings)

The graph used by Graphiti is separate from the raw structured graph
built by GraphBuilder. They share the same FalkorDB instance but use
different graph names to avoid schema conflicts.
"""

from __future__ import annotations

import logging

from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver

from ourgraph.config import AppSettings
from ourgraph.llm.factory import build_embedder, build_llm_client, build_reranker

logger = logging.getLogger(__name__)

# Graphiti uses its own graph name — separate from the raw structured graph
GRAPHITI_GRAPH_SUFFIX = "_graphiti"


def build_graphiti_client(settings: AppSettings) -> Graphiti:
    """
    Build and return a configured Graphiti instance.

    The Graphiti graph is named <graph_name>_graphiti to keep it
    separate from the raw structured KG built by GraphBuilder.

    Call `await client.build_indices_and_constraints()` once before use.

    Args:
        settings: Full AppSettings object.

    Returns:
        A configured (but not yet initialised) Graphiti instance.
    """
    falkor_settings = settings.falkordb
    graphiti_graph_name = falkor_settings.graph_name + GRAPHITI_GRAPH_SUFFIX

    driver_kwargs: dict = {
        "host": falkor_settings.host,
        "port": falkor_settings.port,
        "database": graphiti_graph_name,
    }
    if falkor_settings.username:
        driver_kwargs["username"] = falkor_settings.username
    if falkor_settings.password:
        driver_kwargs["password"] = falkor_settings.password

    driver = FalkorDriver(**driver_kwargs)

    llm_client = build_llm_client(settings.ollama)
    embedder = build_embedder(settings.ollama)
    reranker = build_reranker(settings.ollama, client=llm_client)

    logger.info(
        "Building Graphiti client — graph: %s, llm: %s, embedder: %s",
        graphiti_graph_name,
        settings.ollama.llm_model,
        settings.ollama.embedding_model,
    )

    return Graphiti(
        graph_driver=driver,
        llm_client=llm_client,
        embedder=embedder,
        cross_encoder=reranker,
        max_coroutines=settings.graphiti.semaphore_limit,
    )
