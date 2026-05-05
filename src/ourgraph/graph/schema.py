"""Graph schema constants — aligned with the paper's KG structure.

Paper: "Knowledge Graph Construction for Stock Markets with LLM-Based Explainable Reasoning"
arXiv:2601.11528
"""

from __future__ import annotations


class NodeLabel:
    COMPANY = "Company"
    SECTOR = "Sector"
    INDUSTRY = "Industry"
    STOCK_PRICE = "StockPrice"
    FINANCIAL_STATEMENT = "FinancialStatement"
    INDICATOR = "Indicator"
    OFFICER = "Officer"
    DATE = "Date"
    QUARTER = "Quarter"
    YEAR = "Year"


class RelType:
    # Temporal hierarchy (Date → Quarter → Year)
    IN_QUARTER = "IN_QUARTER"
    IN_YEAR = "IN_YEAR"

    # Company → StockPrice → Date
    HAS_STOCK_PRICE = "HAS_STOCK_PRICE"
    RECORDED_ON = "RECORDED_ON"

    # Company → Indicator → Date/Quarter
    HAS_INDICATOR = "HAS_INDICATOR"
    MEASURED_ON = "MEASURED_ON"

    # Company → FinancialStatement → Quarter / Year
    HAS_FINANCIAL_STATEMENTS = "HAS_FINANCIAL_STATEMENTS"
    FOR_QUARTER = "FOR_QUARTER"
    FOR_YEAR = "FOR_YEAR"

    # Company → Sector/Industry
    BELONGS_TO = "BELONGS_TO"
    BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"

    # Company ↔ Company
    COMPETES_WITH = "COMPETES_WITH"
    SUBSIDIARY_OF = "SUBSIDIARY_OF"
    HOLDS_STAKE_IN = "HOLDS_STAKE_IN"

    # Company → Officer
    LED_BY = "LED_BY"


class Prop:
    # Shared
    SYMBOL = "symbol"
    NAME = "name"

    # Company
    EXCHANGE = "exchange"
    MARKET_CAP = "market_cap"
    NO_EMPLOYEES = "no_employees"
    ESTABLISHED_YEAR = "established_year"
    WEBSITE = "website"
    OUTSTANDING_SHARE = "outstanding_share"
    FOREIGN_PERCENT = "foreign_percent"

    # StockPrice (paper naming)
    DATE = "date"
    OPEN = "open"  # stck_oprc
    HIGH = "high"  # stck_hgpr
    LOW = "low"  # stck_lwpr
    CLOSE = "close"  # stck_clpr
    VOLUME = "volume"

    # Indicator (paper: pbr, per, eps + full payload)
    PBR = "pbr"
    PER = "per"
    EPS = "eps"
    PAYLOAD = "payload"  # full JSON for all metrics

    # FinancialStatement
    PERIOD = "period"
    YEAR = "year"
    QUARTER = "quarter"
    STATEMENT_TYPE = "statement_type"

    # Date
    MONTH = "month"
    DAY = "day"

    # Officer
    OFFICER_NAME = "officer_name"
    POSITION = "position"
    OWN_PERCENT = "own_percent"

    # Edges
    OWNERSHIP_PERCENT = "ownership_percent"
    STAKE_PERCENT = "stake_percent"
    RELATION_TYPE = "relation_type"
