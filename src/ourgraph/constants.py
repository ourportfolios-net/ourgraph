"""Application constants — defaults and limits throughout the codebase.

These values are used in multiple places and should be changed here to maintain
consistency across features.
"""

from __future__ import annotations

# ===========================================================================
# CLI Defaults
# ===========================================================================

# Query command options
DEFAULT_QUERY_RESULTS = 10
DEFAULT_PEERS_LIMIT = 20
DEFAULT_SHARED_INSIDERS_LIMIT = 30
DEFAULT_NETWORK_LIMIT = 200
DEFAULT_CROSS_SHAREHOLDING_LIMIT = 50
DEFAULT_PRICE_HISTORY_TAIL = 30

# Table formatting
TABLE_FACT_COLUMN_WIDTH = 80
TABLE_DATE_COLUMN_WIDTH = 12

# ===========================================================================
# Graph Query Defaults
# ===========================================================================

# Query limits (can be overridden by CLI options)
GRAPH_QUERY_COMPANY_NETWORK_LIMIT = 200
GRAPH_QUERY_SHARED_INSIDERS_LIMIT = 50
GRAPH_QUERY_SECTOR_PEERS_LIMIT = 20
GRAPH_QUERY_CROSS_SHAREHOLDING_LIMIT = 50

# ===========================================================================
# GraphRAG Search Defaults
# ===========================================================================

GRAPHRAG_DEFAULT_RESULTS = 10

# ===========================================================================
# Data Processing Limits
# ===========================================================================

# Episode content constraints
EPISODE_MAX_WORDS = 350

# Data truncation limits for episode ingestion
EPISODE_PEERS_DISPLAY_LIMIT = 10
EPISODE_SYMBOLS_DISPLAY_LIMIT = 30
EPISODE_SUBSIDIARIES_DISPLAY_LIMIT = 8
EPISODE_SECTOR_NAME_TRUNCATE = 60
EPISODE_PERSON_NAME_TRUNCATE = 50

# ===========================================================================
# Historical Data
# ===========================================================================

# How many days of historical price data to fetch
HISTORICAL_PRICE_DAYS = 730  # 2 years

# Financial statement history
FINANCIAL_HISTORY_QUARTERS = 8

# ===========================================================================
# Retry Configuration
# ===========================================================================

# Default wait time between retries (ms)
RETRY_WAIT_MS = 500
RETRY_MAX_ATTEMPTS = 5

# Database-specific retry
DB_RETRY_WAIT_MS = 500
DB_RETRY_MAX_ATTEMPTS = 3

# ===========================================================================
# Data Processing
# ===========================================================================

# Batch processing
BATCH_SIZE = 5
BATCH_DELAY_SECONDS = 10.0

# Minimum data requirements
MIN_SYMBOLS_FOR_INDUSTRY = 2  # Minimum symbols per industry to include
MIN_COMPANIES_FOR_PERSON = 2  # Minimum companies for a person to be included

# ===========================================================================
# Macro Data
# ===========================================================================

# Macro indicator → affected sectors/industries
MACRO_SECTOR_LINKS = {
    "Crude Oil Price": ["Energy", "Transportation"],
    "Gold Price": ["Materials", "Financials"],
    "Copper Price": ["Industrials", "Materials"],
    "Silver Price": ["Materials", "Financials"],
    "Exchange Rate (VND/USD)": ["Export", "Import", "Financials"],
    "Interest Rate": ["Financials", "Real Estate"],
    "Fed Funds Rate": ["Financials", "Technology"],
    "VIX": ["Financials"],
    "S&P 500": ["Financials", "All sectors (sentiment)"],
    "Hang Seng Index": ["Financials", "All sectors (regional sentiment)"],
    "Shanghai Composite": ["All sectors (China sentiment)"],
    "USD Index (DXY)": ["Financials", "Export", "Import"],
    "GDP": ["All sectors"],
    "CPI": ["Consumer Staples", "Consumer Discretionary"],
    "Industrial Production": ["Industrials", "Materials"],
    "Money Supply (M2)": ["Financials", "Real Estate"],
    "FDI": ["All sectors (investment flow)"],
    "Trade Balance": ["Export", "Import"],
}

# Macro data update defaults
MACRO_DAILY_LIMIT = 5  # Max days to fetch on daily updates
MACRO_MAX_RETRIES = 3
MACRO_RETRY_MIN_WAIT = 4  # seconds
MACRO_RETRY_MAX_WAIT = 60  # seconds

# Industry-to-industry supply chain adjacency.
# Maps a producer industry → list of customer industries that typically
# buy from the producer.
SUPPLY_CHAIN_MAP: dict[str, list[str]] = {
    # Steel → downstream
    "Steel": [
        "Automotive",
        "Construction",
        "Appliances",
        "Machinery",
        "Industrial Engineering",
        "Real Estate",
        "Infrastructure",
        "Manufacturing",
        "Packaging",
        "Electronics",
    ],
    # Basic Resources → downstream
    "Basic Resources": [
        "Industrial Engineering",
        "Manufacturing",
        "Construction",
        "Packaging",
        "Automotive",
        "Machinery",
    ],
    # Chemicals → downstream
    "Chemicals": [
        "Agriculture",
        "Food",
        "Pharmaceuticals",
        "Textiles",
        "Construction",
        "Manufacturing",
        "Plastics",
    ],
    # Oil & Gas → downstream
    "Oil & Gas": [
        "Chemicals",
        "Transportation",
        "Manufacturing",
        "Power Generation",
        "Aviation",
        "Logistics",
    ],
    # Energy → everyone
    "Energy": [
        "Manufacturing",
        "Transportation",
        "Technology",
        "Consumer Goods",
        "All sectors",
    ],
    # Construction → downstream
    "Construction": [
        "Real Estate",
        "Infrastructure",
        "Industrial Engineering",
        "Transportation",
        "Energy",
    ],
    # Technology → downstream (everyone uses tech)
    "Technology": [
        "Finance",
        "Healthcare",
        "Retail",
        "Manufacturing",
        "Transportation",
        "Telecommunications",
        "All sectors",
    ],
    # Plastics & Packaging → downstream
    "Plastics": [
        "Food",
        "Consumer Goods",
        "Pharmaceuticals",
        "Packaging",
        "Retail",
    ],
    # Agriculture → downstream
    "Agriculture": [
        "Food",
        "Beverages",
        "Textiles",
        "Retail",
    ],
    # Logistics → downstream
    "Logistics": [
        "Manufacturing",
        "Retail",
        "E-commerce",
        "Food",
        "All sectors (supply chain)",
    ],
}

# Country name mappings (ISO code → name)
MACRO_COUNTRY_NAMES = {
    "VN": "Vietnam",
    "US": "United States",
    "CN": "China",
    "HK": "Hong Kong",
    "TH": "Thailand",
    "GLOBAL": "Global",
}
