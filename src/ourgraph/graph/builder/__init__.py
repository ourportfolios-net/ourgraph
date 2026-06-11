"""GraphBuilder package — split from the original builder.py monolith.

The builder class is composed via mixin inheritance so that type checkers
(Ty) can resolve all method references statically.
"""

from ourgraph.graph.builder.companies import _CompanyMixin
from ourgraph.graph.builder.core import _GraphBuilderCore
from ourgraph.graph.builder.dedup import _DedupMixin
from ourgraph.graph.builder.financials import _FinancialMixin
from ourgraph.graph.builder.people import _PeopleMixin
from ourgraph.graph.builder.relations import _RelationsMixin


class GraphBuilder(
    _CompanyMixin,
    _FinancialMixin,
    _PeopleMixin,
    _RelationsMixin,
    _DedupMixin,
    _GraphBuilderCore,
):
    """Async knowledge graph builder backed by FalkorDB.

    Combines core connection/index management with domain methods from:
    - ``_CompanyMixin`` — companies, sectors, industries, subsidiaries
    - ``_FinancialMixin`` — financial statements, indicators
    - ``_PeopleMixin`` — officers, shareholders, person nodes
    - ``_RelationsMixin`` — macro, country, auditor, events, bonds, scrapers
    - ``_DedupMixin`` — deduplication for all node types
    """


__all__ = ["GraphBuilder"]
