"""ourgraph: Vietnamese Stock Market Knowledge Graph.

A PyPI-installable Python library for building and querying Vietnamese
stock market knowledge graphs (VNIndex/HOSE + HNX).

Usage::

    from ourgraph import GraphBuilder, GraphQueries, Pipeline

    # Build the graph
    builder = GraphBuilder.from_settings(settings.falkordb)
    await builder.upsert_companies(df)

    # Query the graph
    queries = GraphQueries.from_settings(settings.falkordb)
    df = await queries.get_sector_peers("HPG")

    # Full ETL pipeline
    pipeline = Pipeline(settings)
    await pipeline.run_full()
"""

from ourgraph.graph.builder import GraphBuilder
from ourgraph.graph.queries import GraphQueries
from ourgraph.graphiti_layer.search import GraphRAGSearch
from ourgraph.ingest.pipeline import Pipeline
from ourgraph.ingest.vnstock_fetcher import VnstockFetcher

__all__ = [
    "GraphBuilder",
    "GraphQueries",
    "GraphRAGSearch",
    "Pipeline",
    "VnstockFetcher",
]
