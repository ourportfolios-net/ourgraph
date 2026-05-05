"""
Graph schema constants.

All node labels, relationship types, and property names live here.
The graph builder uses these constants — never string literals.
This makes refactoring safe and keeps the schema documented in one place.

Schema is derived from the paper:
  "Knowledge Graph Construction for Stock Markets with LLM-Based Explainable Reasoning"
  arXiv:2601.11528
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Node labels
# ---------------------------------------------------------------------------


class NodeLabel:
    COMPANY = "Company"
    SECTOR = "Sector"
    INDUSTRY = "Industry"
    STOCK_PRICE = "StockPrice"
    FINANCIAL_STATEMENT = "FinancialStatement"
    FINANCIAL_INDICATOR = "FinancialIndicator"
    OFFICER = "Officer"


# ---------------------------------------------------------------------------
# Relationship types
# ---------------------------------------------------------------------------


class RelType:
    # Company → Sector / Industry hierarchy
    BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"
    INDUSTRY_IN_SECTOR = "INDUSTRY_IN_SECTOR"

    # Price & financials
    HAS_PRICE = "HAS_PRICE"
    HAS_STATEMENT = "HAS_STATEMENT"
    HAS_INDICATOR = "HAS_INDICATOR"

    # Ownership / corporate structure
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    HOLDS_STAKE_IN = "HOLDS_STAKE_IN"   # shareholder → company

    # Leadership
    LED_BY = "LED_BY"


# ---------------------------------------------------------------------------
# Property keys (keep these as constants to avoid typos)
# ---------------------------------------------------------------------------


class Prop:
    # Shared
    SYMBOL = "symbol"
    NAME = "name"
    UPDATED_AT = "updated_at"

    # Company
    EXCHANGE = "exchange"
    MARKET_CAP = "market_cap"
    NO_EMPLOYEES = "no_employees"
    ESTABLISHED_YEAR = "established_year"
    WEBSITE = "website"
    OUTSTANDING_SHARE = "outstanding_share"
    FOREIGN_PERCENT = "foreign_percent"

    # Sector / Industry
    ICB_CODE = "icb_code"

    # StockPrice
    DATE = "date"
    OPEN = "open"
    HIGH = "high"
    LOW = "low"
    CLOSE = "close"
    VOLUME = "volume"

    # FinancialStatement
    PERIOD = "period"       # 'quarter' | 'year'
    YEAR = "year"
    QUARTER = "quarter"
    STATEMENT_TYPE = "statement_type"  # 'balance_sheet' | 'income_statement' | 'cash_flow'
    PAYLOAD = "payload"     # JSON-serialised metric dict

    # FinancialIndicator
    METRIC = "metric"
    VALUE = "value"

    # Officer
    OFFICER_NAME = "officer_name"
    POSITION = "position"
    OWN_PERCENT = "own_percent"

    # Ownership edge
    OWNERSHIP_PERCENT = "ownership_percent"
    STAKE_PERCENT = "stake_percent"
    SUB_ORGAN_CODE = "sub_organ_code"
    RELATION_TYPE = "relation_type"     # 'subsidiary' | 'associate'
