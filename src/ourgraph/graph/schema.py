"""Graph schema constants — aligned with the paper's KG structure.

Paper: "Knowledge Graph Construction for Stock Markets with LLM-Based Explainable Reasoning"
arXiv:2601.11528
"""

from __future__ import annotations


class NodeLabel:
    COMPANY = "Company"
    PERSON = "Person"  # Individual — officer, individual shareholder, or both
    SECTOR = "Sector"
    INDUSTRY = "Industry"
    FINANCIAL_STATEMENT = "FinancialStatement"
    INDICATOR = "Indicator"
    DATE = "Date"
    QUARTER = "Quarter"
    YEAR = "Year"
    MACRO_INDICATOR = "MacroIndicator"
    COUNTRY = "Country"
    BOND = "Bond"


class RelType:
    # Ownership & Control
    SUBSIDIARY_OF = "SUBSIDIARY_OF"  # Company → Company
    HOLDS_STAKE_IN = "HOLDS_STAKE_IN"  # (Company|Person) → Company

    # Competition & Market
    COMPETES_WITH = "COMPETES_WITH"  # Company → Company (symmetric)

    # People & Roles
    IS_OFFICER = "IS_OFFICER"  # Person → Company (general officer)
    IS_BOARD_MEMBER = "IS_BOARD_MEMBER"  # Person → Company (board role)
    IS_FOUNDER = "IS_FOUNDER"  # Person → Company (founder)
    IS_EXECUTIVE = "IS_EXECUTIVE"  # Person → Company (C-level/executive)

    # Company → Sector/Industry
    BELONGS_TO = "BELONGS_TO"
    BELONGS_TO_INDUSTRY = "BELONGS_TO_INDUSTRY"

    # Temporal hierarchy (Date → Quarter → Year)
    IN_QUARTER = "IN_QUARTER"
    IN_YEAR = "IN_YEAR"

    # Company → Indicator → Quarter
    HAS_INDICATOR = "HAS_INDICATOR"
    MEASURED_ON = "MEASURED_ON"

    # Company → FinancialStatement → Quarter / Year
    HAS_FINANCIAL_STATEMENTS = "HAS_FINANCIAL_STATEMENTS"
    FOR_QUARTER = "FOR_QUARTER"
    FOR_YEAR = "FOR_YEAR"

    # Audit
    AUDITED_BY = "AUDITED_BY"  # Company → Company (audit firm)

    # MacroIndicator relationships
    HAS_MACRO_INDICATOR = "HAS_MACRO_INDICATOR"  # Country → MacroIndicator
    AFFECTS_SECTOR = "AFFECTS_SECTOR"  # MacroIndicator → Sector
    AFFECTS_INDUSTRY = "AFFECTS_INDUSTRY"  # MacroIndicator → Industry

    # Phase 2: Structured scrapers — corporate disclosure relationships
    RELATED_PARTY_TRANSACTION = "RELATED_PARTY_TRANSACTION"  # Company ↔ Company
    GUARANTEES = "GUARANTEES"  # Company → Company
    LENDS_TO = "LENDS_TO"  # Company → Company
    HAS_JOINT_VENTURE_WITH = "HAS_JOINT_VENTURE_WITH"  # Company ↔ Company
    UNDERWRITTEN_BY = "UNDERWRITTEN_BY"  # Company → Company (issuer → underwriter)
    HAS_BUSINESS_COOPERATION = "HAS_BUSINESS_COOPERATION"  # Company ↔ Company
    STATE_OWNS = "STATE_OWNS"  # Company → Company (state entity → company)
    HAS_BOND = "HAS_BOND"  # Company → Bond


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
    DATE = "date"

    # Indicator (financial ratios)
    PBR = "pbr"
    PER = "per"
    EPS = "eps"
    ROE = "roe"
    ROA = "roa"
    DEBT_TO_EQUITY = "debt_to_equity"
    CURRENT_RATIO = "current_ratio"
    QUICK_RATIO = "quick_ratio"
    GROSS_MARGIN = "gross_margin"
    NET_MARGIN = "net_margin"
    REVENUE_GROWTH = "revenue_growth"
    DIVIDEND_YIELD = "dividend_yield"
    PAYLOAD = "payload"

    # FinancialStatement
    PERIOD = "period"
    YEAR = "year"
    QUARTER = "quarter"
    STATEMENT_TYPE = "statement_type"

    # Date
    MONTH = "month"
    DAY = "day"

    # Person
    PERSON_NAME = "person_name"
    POSITION = "position"
    OWN_PERCENT = "own_percent"

    # MacroIndicator
    VALUE = "value"
    UNIT = "unit"
    COUNTRY = "country"
    CATEGORY = "category"
    FREQUENCY = "frequency"
    SOURCE = "source"

    # Country
    CODE = "code"

    # Price history (computed from OHLCV)
    PRICE_CURRENT = "price_current"
    PRICE_52W_HIGH = "price_52w_high"
    PRICE_52W_LOW = "price_52w_low"
    VOLATILITY_90D = "volatility_90d"
    AVG_VOLUME_30D = "avg_volume_30d"
    RETURN_1M = "return_1m"
    RETURN_3M = "return_3m"
    RETURN_1Y = "return_1y"
    PRICE_MIN = "price_min"
    PRICE_MAX = "price_max"
    PRICE_AVG = "price_avg"
    PRICE_MEDIAN = "price_median"

    # Event metadata (Phase 1b — VCI corporate actions)
    LAST_DIVIDEND_DATE = "last_dividend_date"
    LAST_ISSUANCE_DATE = "last_issuance_date"
    LAST_MEETING_DATE = "last_meeting_date"

    # Edges
    OWNERSHIP_PERCENT = "ownership_percent"
    STAKE_PERCENT = "stake_percent"
    RELATION_TYPE = "relation_type"
    REASON = "reason"
    AUDITOR_NAME = "auditor_name"
