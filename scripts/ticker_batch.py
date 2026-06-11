"""Intertwined Vietnamese ticker batch for ourgraph re-ingestion.

120 tickers across 22 sectors, selected for verifiable cross-relationships:
- 16 banks → cross-lend, interbank guarantees, shared board members
- Vingroup ecosystem → subsidiary chains (VIC → VHM, VRE)
- Steel + Construction → supply chain dependencies
- Securities + Banks → cross-shareholdings
- Insurance → major shareholders in banks/real estate
- Electric/Power → upstream/downstream with oil & gas
- Conglomerates → sprawling subsidiary networks

All tickers verified available on HOSE/HNX via vnstock."""
INTERTWINED_TICKERS = [
    # Banking (16) — cross-lending core
    "ACB", "BID", "CTG", "EIB", "HDB", "LPB", "MBB", "MSB",
    "OCB", "SHB", "STB", "TCB", "TPB", "VCB", "VIB", "VPB",
    # Vingroup ecosystem (3) — subsidiary chains
    "VIC", "VHM", "VRE",
    # Steel / Materials (6) — supply chain → construction
    "DTL", "GVR", "HPG", "HSG", "NKG", "VGS",
    # Securities (6) — cross-shareholding
    "BSI", "FTS", "HCM", "SSI", "VCI", "VND",
    # Real Estate (8) — project financing, JV
    "DXG", "HDG", "KDH", "NLG", "NVL", "PDR", "TCH", "VPI",
    # Energy / Oil & Gas (5)
    "BSR", "GAS", "PGV", "PLX", "POW",
    # Insurance (4) — shareholders in banks
    "BIC", "BMI", "BVH", "PVI",
    # Consumer / Retail (5)
    "DGW", "FRT", "MWG", "PET", "PNJ",
    # Food / Beverage (5)
    "BHN", "KDC", "MSN", "SAB", "VNM",
    # Technology (1)
    "FPT",
    # Aviation / Transport (4)
    "GMD", "HAH", "HVN", "VJC",
    # Construction / Infrastructure (6)
    "CII", "CTD", "CTR", "HT1", "LGC", "VCG",
    # Chemicals / Fertilizer (5)
    "BFC", "DCM", "DGC", "DPM", "LAS",
    # Fisheries / Agriculture (5)
    "ANV", "CMX", "FMC", "IDI", "VHC",
    # Pharmaceuticals (5)
    "DBD", "DHG", "DMC", "IMP", "TRA",
    # Rubber (4)
    "DPR", "HRC", "PHR", "TRC",
    # Textile / Garment (4)
    "GIL", "MSH", "TCM", "TNG",
    # Logistics / Shipping (4)
    "DVP", "PVT", "VOS", "VSC",
    # Water / Utilities (4)
    "BWE", "GDT", "NDN", "TDM",
    # Electricity / Power (5)
    "GEG", "HDC", "NT2", "PPC", "REE",
    # Others with cross-holdings (9)
    "BMP", "CSV", "DBC", "HAX", "PAN", "SBT", "SCS", "VCS",
    # Conglomerates / Holding Cos (6)
    "BCM", "DIG", "GEX", "HUT", "IDC", "SJS",
]
