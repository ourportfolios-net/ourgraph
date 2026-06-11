# Hidden Relationship Discovery: Deep Exploration

> Techniques and strategies for uncovering non-obvious connections in the Vietnamese stock market knowledge graph.

---

## Table of Contents

1. [Why Hidden Relationships Matter](#1-why-hidden-relationships-matter)
2. [Graph-Theoretic Approaches](#2-graph-theoretic-approaches)
3. [NLP / LLM-Based Approaches](#3-nlp--llm-based-approaches)
4. [Temporal & Price-Based Approaches](#4-temporal--price-based-approaches)
5. [External Data Sources](#5-external-data-sources)
6. [Scoring & Ranking](#6-scoring--ranking)
7. [System Architecture](#7-system-architecture)
8. [Research Frontier](#8-research-frontier)

---

## 1. Why Hidden Relationships Matter

The Vietnamese stock market (HOSE + HNX, ~800 companies) has structural characteristics that make hidden relationships particularly important:

- **Pyramid ownership structures**: Families control conglomerates through cascading holding companies (Vingroup, Masan, Hoa Phat)
- **Cross-shareholding loops**: Banks and corporates hold mutual stakes, creating circular ownership (common in Vietnamese banking)
- **Informal insider networks**: Family members, former colleagues, and political connections that don't appear in formal disclosures
- **State-owned enterprise (SOE) ties**: Companies with shared state ownership that coordinate behavior
- **Supply chain opacity**: Inter-company transactions not always disclosed as related-party

Finding these relationships transforms the graph from "what companies exist" to "who actually controls what."

---

## 2. Graph-Theoretic Approaches

### 2.1 Ownership Graph Analysis

The ownership graph is a directed weighted graph where nodes are companies/persons and edges are HOLDS_STAKE_IN with `stake_percent` weights.

#### Control Detection

Beyond simple majority ownership (≥50%), control can be achieved through:

**Controlling Minority**: A shareholder with <50% but significantly more than any other single shareholder. Detect via:

```
Given company C with shareholders S = {s1, s2, ..., sn} sorted by stake descending:
  If stake(s1) > 2 * stake(s2) AND no other entity exceeds stake(s1):
    → s1 has "working control" of C
```

**Ultimate Beneficial Ownership (UBO)**: The自然人 who ultimately controls a company through chains:

```
For each company C, trace all ownership chains upward:
  Follow HOLDS_STAKE_IN edges in reverse (target → source)
  At each Person node, record the chain and compute cumulative effective ownership
  Merge by normalized person_name (handling Vietnamese diacritics variations)
  Filter by effective_ownership > threshold (e.g., 5%)
```

**Pseudo-code for UBO detection**:

```
function find_ubo(company, visited=set(), depth=0):
    if depth > MAX_DEPTH or company in visited: return []
    visited.add(company)
    results = []
    for shareholder in get_shareholders(company):
        stake = get_stake(shareholder, company)
        if shareholder is Person:
            results.append((shareholder, chain=[company], effective=stake/100))
        elif shareholder is Company:
            sub_results = find_ubo(shareholder, visited, depth+1)
            for person, chain, eff in sub_results:
                results.append((person, chain+[company], eff * stake/100))
    return results
```

#### Circular Ownership Detection

Circular ownership exists when a chain of HOLDS_STAKE_IN edges forms a cycle. This is particularly relevant in Vietnamese banking:

```
Bank A ← holds 8% ── Company X
  └── holds 5% ──→ Company Y ── holds 15% ──→ Bank A
```

Detection via cycle enumeration on the directed ownership graph:

1. Build adjacency matrix or edge list from all HOLDS_STAKE_IN edges
2. Run Tarjan's SCC (Strongly Connected Components) algorithm
3. Any SCC containing 2+ companies is a circular ownership group
4. For each cycle, compute total circular capital = Σ(min(stake_in_pair) for each pair in cycle)

**SCC detection in Cypher**:

```cypher
// Pseudo — FalkorDB doesn't support recursive CTEs natively
// Requires application-layer traversal
MATCH (a:Company)-[:HOLDS_STAKE_IN]->(b:Company)
WHERE a.symbol < b.symbol
// Application layer: build adjacency list, run Tarjan
RETURN a.symbol, b.symbol
```

#### Ownership Concentration Metrics

For each company, compute:

```
Herfindahl-Hirschman Index (HHI) = Σ(stake_i²)
  High HHI → concentrated ownership → fewer decision-makers
  
Shannon Entropy = -Σ(stake_i * ln(stake_i))
  Low entropy → dominated by few shareholders
  
Controllable Percentage = stake_1 + stake_2 + ... + stake_k
  where k is the minimum set summing to >50%
```

Use these to flag companies where ownership is concentrated enough that a few actors coordinate decisions.

### 2.2 Board Interlock Networks

Board interlocks occur when a person sits on the boards of multiple companies. The network of interlocks reveals information flow paths and potential coordination.

#### Pruning for Significance

Not every shared director is meaningful. Filter by:

1. **Director tier**: Only count independent directors and board chairs (not nominal members)
2. **Company size**: Interlocks between HNX small-caps and HOSE large-caps are more significant
3. **Temporal overlap**: The person must have held both positions simultaneously (use `since_date`/`until_date`)

#### Centrality Analysis

On the board interlock graph (undirected, companies as nodes, shared directors as edges):

```
Betweenness Centrality:
  Companies that bridge otherwise disconnected clusters
  → Likely to be information brokers or coordination points

Closeness Centrality:
  Companies with shortest average path length to all others
  → Can disseminate or receive information quickly

Eigenvector Centrality:
  Companies connected to highly-connected companies
  → Part of influential cliques
```

#### Community Detection

Apply Louvain or Leiden community detection on the board interlock graph:

- **Communities of companies sharing multiple directors** → Likely coordinated governance
- **Bridge nodes** (people serving across communities) → Information conduits
- **Isolated nodes** → Companies with truly independent boards

#### Clique Analysis

A k-clique in the board interlock graph means k companies all share board members (possibly through different people). A 3-clique (triangle) means:

```
Company A ←→ Person X, Person Y
Company B ←→ Person X, Person Z  
Company C ←→ Person Y, Person Z
```

This is significant because even if no single person connects all three, the shared directors across the clique create a dense information-sharing environment.

### 2.3 Supply Chain Inference

#### Industry Adjacency Matrix

Build a weighted adjacency matrix of industries based on:

1. **Input-Output tables**: Use the Vietnam Input-Output (I/O) table from GSO (General Statistics Office) to quantify how much each industry supplies to others
2. **Keyword co-occurrence**: In annual reports, count how often sector-product keywords co-occur
3. **Transaction probability**: Learned from known customer-supplier disclosures

**Example I/O derived adjacency**:

| Sector | Supplies To | Coefficient |
|--------|------------|-------------|
| Steel | Construction | 0.35 |
| Steel | Automotive | 0.12 |
| Steel | Manufacturing | 0.28 |
| Rubber | Automotive | 0.40 |
| Textiles | Retail/Export | 0.55 |

#### Product-Level Matching

Beyond industry-level, match at the product level using Vietnamese HS codes (Harmonized System):

```
Company A (Steel, products: HRC, CRC) 
  + HS 7208 (flat-rolled iron/steel)
  → Customer: Company B (Construction, needs: steel beams)
Company C (Plastics, products: PVC resin)
  + HS 3904 (PVC polymers)
  → Customer: Company D (Pipes, needs: PVC)
```

#### Transaction Volume Inference

When customer-supplier relationships are inferred, estimate transaction volume:

```
transaction_pct(revenue_A) ≈ (revenue_A × industry_supply_coeff) / n_customers_in_industry
```

This gives a rough "materiality" score — without disclosure, you can estimate how important a given relationship is.

### 2.4 Entity Linking & Name Resolution

Vietnamese names present unique challenges:

#### Person Name Normalization

```python
# Vietnamese diacritics: Nguyễn Văn A → Nguyen Van A
# Honorifics: TS. Nguyễn Văn A → Nguyen Van A
# Variations: Nguyễn Văn A, Nguyễn Văn A (Mr.), Nguyễn V A → all resolve to same
```

**Soundex/Vietnamese phonetic matching**: Different spellings of the same name:

- "Nguyen Van Hai" vs "Nguyễn Văn Hải" (diacritics)
- "Tran Thi Mai" vs "Trần Thị Mai" (diacritics)
- "John Tran" vs "Trần Văn John" (Western vs Vietnamese ordering)

**Approach**: Use double-metaphone adapted for Vietnamese phonetics, then apply Jaro-Winkler distance for final matching with threshold > 0.85.

#### Company Name Variations

```python
patterns = [
    r"(CTCP|CÔNG TY CỔ PHẦN)",  # Joint Stock Company
    r"(CTY TNHH|CÔNG TY TNHH)",  # Limited Liability
    r"-\s*CP$",                   # Suffix abbreviations
    r"(TẬP ĐOÀN|TĐ)",            # Conglomerate
]
```

---

## 3. NLP / LLM-Based Approaches

### 3.1 Annual Report Mining

Vietnamese annual reports (Báo cáo thường niên) are published as PDFs on each company's website and contain rich relationship data.

#### Text Extraction Pipeline

```
PDF → OCR (if scanned) → Text → Chunking → Embedding → Semantic Search
```

**Entity extraction targets**:

| Entity Type | Regex / NER Pattern | Example |
|------------|---------------------|---------|
| Related parties | "bên liên quan", "công ty thành viên", "công ty con" | Công ty con: CTCP XYZ |
| Major customers | "khách hàng chính", "khách hàng lớn" | Khách hàng A chiếm 30% doanh thu |
| Major suppliers | "nhà cung cấp chính", "nhà cung cấp lớn" | Nhà cung cấp thép XYZ |
| Guarantees | "bảo lãnh", "bảo lãnh vay vốn" | Bảo lãnh cho công ty thành viên vay 500 tỷ |
| Loans to related parties | "cho vay", "ứng trước", "phải thu" | Phải thu của bên liên quan: 200 tỷ |

#### LLM-Powered Extraction

Use an LLM to extract structured relationship data from report sections:

```
System: Extract all related-party relationships from this Vietnamese annual report section.
Return as JSON: [{source, target, relationship_type, detail, confidence}]

Input: "Công ty có quan hệ với CTCP Đầu tư XYZ trong đó Ông Nguyễn Văn A là 
thành viên HĐQT tại cả hai công ty. Công ty cũng mua thép từ CTCP ABC với 
giá trị 500 tỷ đồng trong năm 2023."

Output:
[
  {
    "source": "CTCP Đầu tư XYZ",
    "target": "Company",
    "relationship_type": "BOARD_INTERLOCK",
    "detail": "Ông Nguyễn Văn A là thành viên HĐQT tại cả hai công ty",
    "confidence": 0.95
  },
  {
    "source": "Company",
    "target": "CTCP ABC",
    "relationship_type": "SUPPLIER",
    "detail": "Mua thép trị giá 500 tỷ đồng năm 2023",
    "confidence": 0.90
  }
]
```

#### Batch Processing Strategy

```
For ~800 companies, ~4 quarters of reports each:
  ~3200 reports × ~50 pages each = ~160,000 pages
  ↓
  Extract + Chunk + Embed: ~1-2 hours (parallelized)
  ↓  
  LLM extraction (key pages only): ~4-8 hours (cost-optimized)
  
Strategy: Process ALL text for known entity patterns (fast)
          Only LLM-extract sections that match "bên liên quan" / related-party keywords
```

### 3.2 News Sentiment & Event Extraction

Vietnamese financial news (Cafef, VnEconomy, NDH, VietnamBiz) is a continuous stream of relationship-relevant information.

#### Event Types to Track

| Event Type | News Signal | Graph Action |
|-----------|------------|-------------|
| Board changes | "Ông X từ nhiệm/được bổ nhiệm" | Update IS_BOARD_MEMBER, IS_EXECUTIVE |
| Major deals | "Mua lại/bán cổ phần tại Y" | Update HOLDS_STAKE_IN |
| Disputes | "Tranh chấp cổ đông tại Z" | Flag CONFLICT_BETWEEN |
| Partnership | "Hợp tác chiến lược với ABC" | Create STRATEGIC_PARTNERSHIP |
| Related-party transactions | "Giao dịch với bên liên quan" | Flag for review |

#### Co-News Coverage Correlation

Two companies that consistently appear in the same news articles — even without explicitly mentioned relationships — may have hidden connections.

**Metric**: Jaccard similarity of news article mentions over a rolling window:

```
J(A, B) = |articles_mentioning_A ∩ articles_mentioning_B| 
         / |articles_mentioning_A ∪ articles_mentioning_B|

Significant at J > 0.15 over a 90-day window
```

#### Key Person Detection

Track named entities across articles. When a person name frequently appears in articles about company A, and later starts appearing in articles about company B, this may indicate:

- An upcoming board appointment
- A consulting/advisory relationship (not disclosed)
- Personal investment interest

**Approach**:

```
For each person P, maintain a "company association vector" over time:
  [t1: {A: 0.8, B: 0.1, C: 0.1}, t2: {A: 0.6, B: 0.3, C: 0.1}, ...]
  
When association weight shifts significantly between t and t+30d:
  → Flag as "emerging relationship"
```

### 3.3 Business Description Similarity

Use embedding similarity on company business descriptions (ngành nghề kinh doanh) to find companies that should be connected but aren't.

```
For each company:
  Encode business description → vector (via nomic-embed-text or similar)
  
For all pairs:
  cosine_sim(desc_A, desc_B) → similarity score
  
Pairs with high similarity but no COMPETES_WITH or BELONGS_TO_INDUSTRY edge:
  → Potential missing competitive relationship
  
Pairs with moderate similarity but no SUPPLIER edge and one company is upstream:
  → Potential missing supply chain relationship
```

---

## 4. Temporal & Price-Based Approaches

### 4.1 Price Lead-Lag Analysis

Cross-correlation can reveal which company's stock price movements predict another's:

```
For each pair (A, B) over a 1-year window:
  For lag ∈ [-20, +20] trading days:
    corr(A_t, B_{t+lag}) → cross-correlation at lag
  
  If max_cross_corr occurs at lag > 3:
    → A's price movements lead B's (or vice versa)
    → Possible information asymmetry or supply chain dependency
```

**Interpretation**:

| Lead-Lag Pattern | Possible Interpretation |
|-----------------|------------------------|
| A → B (+3-5 days) | A is supplier of B (earnings news propagates) |
| A → B (+1-2 days) | A is a bellwether for the sector |
| A ↔ B (same day) | Common factors (macro, sector) or mutual relationship |
| A ← B (negative lag) | B is the price leader, A reacts to B |

### 4.2 Correlation Regime Detection

Correlation regimes — periods where correlation is high vs. low — reveal relationship changes:

```
Sliding window: 60 trading days, step 1 day
For each pair, compute r_pearson at each step
Plot r(t) over 1-year period

Regime changes (r shifts by > 0.5 sustained for 10+ days):
  → RISE: New relationship formed (contract won, acquisition target, etc.)
  → FALL: Relationship ended (divestiture, competition entered, etc.)
```

### 4.3 Abnormal Trading Volume Correlation

Beyond price correlation, correlated abnormal trading volume suggests shared information flow:

```
For each company on day t:
  abnormal_volume_t = (volume_t - avg_volume_30d) / std_volume_30d
  
For each pair (A, B):
  corr(abnormal_volume_A, abnormal_volume_B) over 90d
  
  If high (>0.6) but price correlation is low (<0.3):
    → Possible hidden information sharing without price impact
    → Insider communication, shared investor base
```

### 4.4 Bankruptcy / Distress Contagion

Risk propagation through hidden connections:

```
When company A experiences a distress event (price drop > 15% in a week):
  For each connected company B (direct edge or shared insider):
    Track B's abnormal return over [+1, +10] trading days
    
  If B also drops significantly (>5%, unrelated to sector):
    → Risk transmission through the relationship
    → Quantify: transmission_coeff = B_return / A_return
    
  Flag relationships with high transmission coefficient:
    → These represent material exposure that deserves disclosure
```

---

## 5. External Data Sources

### 5.1 Vietnamese Sources

| Source | Data Type | Update Frequency | Access |
|--------|-----------|-----------------|--------|
| **Cafef.vn** | News, financials, ownership, insiders | Daily | Web scraping |
| **Vietstock.vn** | Financials, ratios, news | Daily | Web scraping / API |
| **SSC (ssc.gov.vn)** | Material disclosures, ownership changes | Real-time | Website monitoring |
| **VSD (vsd.vn)** | Securities depository — large holder reports | T+1 | Restricted |
| **GSO (gso.gov.vn)** | I/O tables, economic statistics | Annual | Open data |
| **BIZ (bizlive.vn)** | News, industry analysis | Daily | Web scraping |
| **DPI portals** | Business registration, legal reps | Static | Provincial portals |

### 5.2 International Sources

| Source | Data Type | Coverage |
|--------|-----------|---------|
| **Bloomberg Terminal** | Supply chain data (SPLC function) | Limited Vietnamese coverage |
| **Refinitiv Supply Chain** | Customer-supplier links | ~50 major VN companies |
| **Crunchbase** | PE/VC investments in VN companies | Startup-focused |
| **OpenCorporates** | Corporate registry links | Limited VN coverage |
| **Wikidata** | Company relationships (P749, P127) | Sparse but useful |

### 5.3 Proprietary Enhancement

For production use, consider:

1. **SEC/Filing crawler**: Vietnamese subsidiaries of US-listed companies (e.g., Vingroup's SPAC) must file disclosures with the SEC
2. **Patent assignee network**: Companies sharing patent inventors (limited in VN but growing)
3. **Legal judgment database**: Companies appearing in the same lawsuits
4. **Government contract database**: Shared bidding patterns on public tenders
5. **Real estate registry**: Shared property addresses (common indicator of related parties)

---

## 6. Scoring & Ranking

### 6.1 Relationship Confidence Score

Every discovered relationship should carry a confidence score:

```
confidence = f(evidence_weight, source_reliability, temporal_recency)

Components:
  Evidence Weight: How many independent signals point to this relationship?
    1 signal: base weight 0.3
    2 signals: 0.6
    3+ signals: 0.9

  Source Reliability:
    Annual report (audited): 1.0
    Official disclosure: 1.0
    News article: 0.6
    Inferred (price/industry): 0.3

  Temporal Recency:
    < 3 months: 1.0
    3-12 months: 0.8
    1-2 years: 0.5
    > 2 years: 0.2

confidence = Σ(W_i × R_i) / Σ(W_i) × recency_factor
```

### 6.2 Materiality Score

How much does this relationship matter for investment decisions?

```
materiality = f(ownership_impact, revenue_exposure, board_representation)

For cross-shareholding:
  materiality = (stake_A_in_B + stake_B_in_A) / 2 × market_cap_weight
  
For supply chain:
  materiality = estimated_transaction_value / revenue_A
  
For board interlock:
  materiality = n_directors_shared / min(board_size_A, board_size_B)
  
For shared insider:
  materiality = person_influence_score / n_companies
```

### 6.3 Novelty Score

How surprising is this relationship? Novelty helps prioritize which relationships to investigate first:

```
novelty = 1 - expectedness

Where expectedness is derived from:
  Known industry ties: Steel ↔ Construction = expected (0.8)
  Cross-industry: Bank ↔ Agriculture = unexpected (0.2)
  Same sector pair: expected (0.7)
  Cross-sector pair: less expected (0.3)
  Existing graph distance:
    distance = 1 (directly connected): 1.0 (not novel)
    distance = 2 (shared neighbor): 0.5
    distance = 3+: 0.1 (very novel if found)
```

### 6.4 Holistic Risk Scoring

Combine all scores into a single "hidden relationship risk" metric per company:

```
company_risk = Σ(materiality_i × confidence_i × novelty_i) for all discovered 
               relationships involving the company

Use this to answer: "Which companies most likely have material undisclosed 
relationships?" → High-risk companies for further investigation.
```

---

## 7. System Architecture

### 7.1 Discovery Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                    Scheduler (daily/weekly)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Orchestrator (discovery.run())              │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Graph-Based  │  │ External     │  │ ML/LLM-Based     │  │
│  │ Discovery    │  │ Source Sync  │  │ Discovery        │  │
│  │              │  │              │  │                  │  │
│  │ • Ownership  │  │ • News crawl │  │ • NER extraction │  │
│  │ • Board net  │  │ • Report     │  │ • Embedding sim  │  │
│  │ • Supply ch. │  │   download   │  │ • Clustering     │  │
│  │ • Price corr │  │ • VSD import │  │ • LLM inference  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │           │
│         └─────────────────┼────────────────────┘           │
│                           │                                │
│                           ▼                                │
│  ┌────────────────────────────────────────────────────┐    │
│  │               Fusion & Scoring                     │    │
│  │  • Deduplicate across sources                      │    │
│  │  • Compute confidence, materiality, novelty        │    │
│  │  • Apply thresholds                                │    │
│  └──────────────────────┬─────────────────────────────┘    │
│                         │                                  │
│                         ▼                                  │
│  ┌────────────────────────────────────────────────────┐    │
│  │               Persistence Layer                    │    │
│  │  • Write to raw graph (CYPHER MERGE)              │    │
│  │  • Write to temporal graph (Graphiti episode)     │    │
│  │  • Update discovery_meta (for scheduling)         │    │
│  └────────────────────────────────────────────────────┘    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Incremental Updates

Full recomputation is expensive. Design for incremental updates:

```
For each discovery type, maintain a watermark:
  cross_shareholding_last_run: timestamp
  news_articles_processed: cursor
  price_data_last_date: date

On each run:
  1. Identify what has changed since last watermark
  2. Only recompute affected relationships
  3. Update watermark

Example — news-based discovery:
  new_articles = fetch_articles_since(last_processed_id)
  for article in new_articles:
    entities = extract_entities(article)
    for pair in pairs(entities):
      update_relationship_confidence(pair, article.impact)
  last_processed_id = max(article.id)
```

### 7.3 Hybrid Temporal Graph Integration

Discovered relationships should feed into Graphiti:

```
type_mapping = {
    "cross_shareholding": "Công ty A và B sở hữu chéo cổ phần: A nắm X%, B nắm Y%",
    "shared_insider": "Ông/Bà {person} giữ chức vụ tại {companies}: {roles}",
    "supply_chain": "Công ty A ({industry}) có thể là nhà cung cấp của B ({industry})",
    "price_correlation": "Giá cổ phiếu A và B có tương quan {r:.2f} trong 90 ngày qua",
}

# Each discovered relationship becomes a Graphiti episode
# → Queryable via natural language: "Which companies supply HPG?"
# → Temporal: "Did HPG's suppliers change in 2023?"
```

### 7.4 Confidence Escalation

Discovered relationships should follow a confidence lifecycle:

```
Discovered (confidence 0.2-0.5) 
    → Indicated by proxy (price correlation, industry adjacency)
    → Stored in discovery_meta, NOT added to main graph
    
Corroborated (confidence 0.5-0.8)
    → Multiple independent signals
    → Added to main graph with {discovered: true, confidence: 0.7}
    
Confirmed (confidence 0.8-1.0)
    → External data source or official disclosure
    → Promote to full relationship with {discovered: false, confidence: 1.0}
    → Update source relationship if it already existed in discovered state
```

---

## 8. Research Frontier

### 8.1 Temporal Knowledge Graph Completion

Use TKG (Temporal Knowledge Graph) embedding models to predict missing edges:

```
Model: TGN (Temporal Graph Network) or RE-NET (Recurrent Event Network)

Training data:
  - Existing edges with timestamps
  - Split: train on years 2018-2022, validate on 2023, test on 2024

Predicted edges:
  - (Company A, HOLDS_STAKE_IN, Company B, 2024) with probability P
  - (Person X, IS_BOARD_MEMBER, Company C, 2024) with probability P

If P > threshold and edge doesn't exist in graph:
  → Flag as "model-predicted relationship"
```

### 8.2 Anomaly Detection on Graph

Use graph neural networks (GNNs) to detect anomalous edges or missing edges:

```
Graph Isomorphism: Learn the "normal" pattern of ownership edges
Anomalous patterns:
  - Missing expected edge (company with all characteristics of a subsidiary 
    but no SUBSIDIARY_OF edge)
  - Unexpected edge weight (stake percentage far from the norm for that 
    relationship type)
  - Structural hole (person who should be connected based on profile but 
    has no edges)
```

### 8.3 Network Alignment for Multi-Graph Integration

If you have graphs from different sources (e.g., our internal graph, a government registry graph, a news-derived graph):

```
Network alignment: Find which nodes across graphs represent the same entity
Then: Transfer edges from one graph to another
  → e.g., Government graph has "board member of" edges not in our graph
  → Align, then import missing edges
```

### 8.4 Causal Discovery

Beyond correlation, identify causal relationships in the stock market:

```
Granger causality test on price/volume time series:
  Does the history of company A's price predict company B's price?
  If A Granger-causes B but not vice versa:
    → A may be a bellwether or A has undisclosed influence over B

Causal graph discovery (PC algorithm):
  Learn a directed acyclic graph of causal relationships between 
  company returns, accounting for:
    - Market-wide factors (VNIndex)
    - Sector factors
    - Company-specific shocks
  Residual edges after conditioning on known factors:
    → Hidden relationships driving correlated returns
```

---

## Summary of Implementation Priority

| Approach | Difficulty | Impact | Data Needed | Priority |
|----------|-----------|--------|-------------|----------|
| UBO detection | Medium | High | Existing graph | ★★★★★ |
| Board interlock centrality | Low | High | Existing graph | ★★★★★ |
| Price correlation regimes | Medium | Medium | Existing price data | ★★★★☆ |
| News co-mention tracking | High | High | News source | ★★★★☆ |
| Annual report NLP | High | Very High | PDF source | ★★★☆☆ |
| Supply chain product-level | Medium | Medium | HS codes | ★★★☆☆ |
| TKG completion | Very High | Very High | Labeled training data | ★★☆☆☆ |
| GNN anomaly detection | Very High | High | Labeled training data | ★☆☆☆☆ |
| Causal discovery | Very High | Medium | Clean time series | ★☆☆☆☆ |

The highest-leverage next step is **UBO detection** + **board interlock centrality** — both use only existing graph data and provide immediate, high-value insights for Vietnamese stock analysis.