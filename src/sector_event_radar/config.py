"""
Configuration and constants for RS screening backtest.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# ============================================================
# GICS11 Sector ETFs (US)
# ============================================================
US_MARKET_ETF = "SPY"

US_SECTOR_ETFS: Dict[str, str] = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

# ============================================================
# TOPIX-17 Sector ETFs (Japan)
# ============================================================
JP_MARKET_ETF = "1306.T"

JP_SECTOR_ETFS: Dict[str, str] = {
    "TOPIX-17 FOODS": "1617.T",
    "TOPIX-17 ENERGY RESOURCES": "1618.T",
    "TOPIX-17 CONSTRUCTION & MATERIALS": "1619.T",
    "TOPIX-17 RAW MATERIALS & CHEMICALS": "1620.T",
    "TOPIX-17 PHARMACEUTICAL": "1621.T",
    "TOPIX-17 AUTOMOBILES & TRANSPORTATION EQUIPMENT": "1622.T",
    "TOPIX-17 STEEL & NONFERROUS METALS": "1623.T",
    "TOPIX-17 MACHINERY": "1624.T",
    "TOPIX-17 ELECTRIC APPLIANCES & PRECISION INSTRUMENTS": "1625.T",
    "TOPIX-17 IT & SERVICES, OTHERS": "1626.T",
    "TOPIX-17 ELECTRIC POWER & GAS": "1627.T",
    "TOPIX-17 TRANSPORTATION & LOGISTICS": "1628.T",
    "TOPIX-17 COMMERCIAL & WHOLESALE TRADE": "1629.T",
    "TOPIX-17 RETAIL TRADE": "1630.T",
    "TOPIX-17 BANKS": "1631.T",
    "TOPIX-17 FINANCIALS (EX BANKS)": "1632.T",
    "TOPIX-17 REAL ESTATE": "1633.T",
}

# 33業種→TOPIX-17変換テーブル
TOPIX33_TO_TOPIX17: Dict[str, str] = {
    "Fishery, Agriculture & Forestry": "TOPIX-17 FOODS",
    "Foods": "TOPIX-17 FOODS",
    "Mining": "TOPIX-17 ENERGY RESOURCES",
    "Oil and Coal Products": "TOPIX-17 ENERGY RESOURCES",
    "Construction": "TOPIX-17 CONSTRUCTION & MATERIALS",
    "Metal Products": "TOPIX-17 CONSTRUCTION & MATERIALS",
    "Glass and Ceramics Products": "TOPIX-17 CONSTRUCTION & MATERIALS",
    "Textiles and Apparels": "TOPIX-17 RAW MATERIALS & CHEMICALS",
    "Pulp and Paper": "TOPIX-17 RAW MATERIALS & CHEMICALS",
    "Chemicals": "TOPIX-17 RAW MATERIALS & CHEMICALS",
    "Pharmaceutical": "TOPIX-17 PHARMACEUTICAL",
    "Rubber Products": "TOPIX-17 AUTOMOBILES & TRANSPORTATION EQUIPMENT",
    "Transportation Equipment": "TOPIX-17 AUTOMOBILES & TRANSPORTATION EQUIPMENT",
    "Iron and Steel": "TOPIX-17 STEEL & NONFERROUS METALS",
    "Nonferrous Metals": "TOPIX-17 STEEL & NONFERROUS METALS",
    "Machinery": "TOPIX-17 MACHINERY",
    "Electric Appliances": "TOPIX-17 ELECTRIC APPLIANCES & PRECISION INSTRUMENTS",
    "Precision Instruments": "TOPIX-17 ELECTRIC APPLIANCES & PRECISION INSTRUMENTS",
    "Other Products": "TOPIX-17 IT & SERVICES, OTHERS",
    "Information & Communication": "TOPIX-17 IT & SERVICES, OTHERS",
    "Services": "TOPIX-17 IT & SERVICES, OTHERS",
    "Electric Power and Gas": "TOPIX-17 ELECTRIC POWER & GAS",
    "Land Transportation": "TOPIX-17 TRANSPORTATION & LOGISTICS",
    "Marine Transportation": "TOPIX-17 TRANSPORTATION & LOGISTICS",
    "Air Transportation": "TOPIX-17 TRANSPORTATION & LOGISTICS",
    "Warehousing and Harbor Transportation Service": "TOPIX-17 TRANSPORTATION & LOGISTICS",
    "Wholesale Trade": "TOPIX-17 COMMERCIAL & WHOLESALE TRADE",
    "Retail Trade": "TOPIX-17 RETAIL TRADE",
    "Banks": "TOPIX-17 BANKS",
    "Securities and Commodities Futures": "TOPIX-17 FINANCIALS (EX BANKS)",
    "Insurance": "TOPIX-17 FINANCIALS (EX BANKS)",
    "Other Financing Business": "TOPIX-17 FINANCIALS (EX BANKS)",
    "Real Estate": "TOPIX-17 REAL ESTATE",
}


# ============================================================
# Backtest parameters
# ============================================================
@dataclass
class BacktestConfig:
    """All tunable parameters in one place."""

    # --- Market ---
    market: str = "US"  # "US" or "JP"
    backtest_start: str = "2019-01-01"
    data_fetch_start: str = "2017-06-01"  # extra history for warmup

    # --- Warmup ---
    warmup_weeks: int = 62  # 52 + 10 (for SMA10w)

    # --- Gate thresholds ---
    epsilon: float = 0.02       # Gate E: sector headwind tolerance
    sigma_exclude_pct: float = 0.20  # Gate D: top 20% σrel excluded
    adv_multiplier: int = 20    # Gate C: ADV20 >= position * multiplier
    position_size: float = 1e7  # Gate C: assumed position size (JPY or USD)

    # --- Score weights ---
    w52: float = 0.50
    w26: float = 0.30
    w13: float = 0.20

    # --- Selection ---
    p_select: float = 0.20
    n_min: int = 10
    n_max: int = 50  # also serves as N_ref for evaluation

    # --- Evaluation ---
    forward_horizons: Tuple[int, ...] = (1, 4, 13)  # K weeks

    # --- σ floor ---
    # σ_floor = median of σrel in base universe (computed dynamically)

    # --- F bonus ---
    f_bonus_pct: float = 0.01  # alpha = f_bonus_pct * IQR(Score_rate)

    # ==========================================================
    # MR-LS daily parameters (used by mr_random_baseline.py)
    # ==========================================================
    warmup_days: int = 252

    # SMA lookbacks
    sma200_lookback: int = 200
    sma200_min_valid: int = 200
    sma20_lookback: int = 20
    sma20_min_valid: int = 20

    # Sigma rel
    sigma_rel_window: int = 63
    sigma_rel_min_valid: int = 60

    # Z-score thresholds
    z5_threshold: float = -1.5
    z5_extreme_floor: float = -3.0
    s2_enabled: bool = True

    # Absolute 5-day return threshold
    abs_5d_threshold: float = -0.02

    # Gap detection
    gap_lookback: int = 3
    gap_threshold: float = 0.12

    # MR-LS selection (override n_min/n_max for daily if needed)
    n_ref: int = 50  # reference portfolio size for evaluation


# ============================================================
# Gate ON/OFF case definitions
# ============================================================
@dataclass
class GateCase:
    """Which gates to enable/disable.

    RS weekly gates: A1-F
    MR-LS daily gates: L1, L2, T1, T2, S1, S3, P1, P2, C1, E1
    """
    name: str
    # --- RS weekly gates ---
    A1: bool = True
    A2: bool = True
    A3: bool = True
    B: bool = True
    C: bool = True
    D: bool = True
    E: bool = True
    F: bool = True  # F is bonus, ON=apply bonus, OFF=skip bonus
    # --- MR-LS daily gates ---
    L1: bool = True   # Rel252_21 > 0
    L2: bool = True   # Rel126_21 > 0
    T1: bool = True   # Price > SMA200
    T2: bool = True   # SMA200 rising (vs 20d ago)
    S1: bool = True   # z5 <= threshold (oversold)
    S3: bool = True   # abs_5d <= threshold
    P1: bool = True   # Price < SMA20 (pullback)
    P2: bool = True   # Price > SMA200 (redundant with T1, safety check)
    C1: bool = True   # Liquidity (ADV20)
    E1: bool = True   # No large gaps


def build_cases() -> List[GateCase]:
    """Build all evaluation cases: Full, single-OFF, pair-OFF."""
    cases = [
        GateCase(name="Full"),
        GateCase(name="A1_OFF", A1=False),
        GateCase(name="A2_OFF", A2=False),
        GateCase(name="A3_OFF", A3=False),
        GateCase(name="B_OFF", B=False),
        GateCase(name="C_OFF", C=False),
        GateCase(name="D_OFF", D=False),
        GateCase(name="E_OFF", E=False),
        GateCase(name="F_OFF", F=False),
        # Pair OFF (redundancy check)
        GateCase(name="BA3_OFF", B=False, A3=False),
        GateCase(name="EF_OFF", E=False, F=False),
    ]
    return cases


# ============================================================
# Sensitivity analysis parameter grids
# ============================================================
SENSITIVITY_EPSILON = [0.0, 0.01, 0.02, 0.03, 0.05]

SENSITIVITY_SIGMA_PCT = [0.10, 0.15, 0.20, 0.30]

SENSITIVITY_WEIGHTS = [
    ("precision", 0.58, 0.27, 0.15),
    ("stable",    0.60, 0.30, 0.10),
    ("balance",   0.50, 0.30, 0.20),
    ("reactive",  0.40, 0.30, 0.30),
    ("equal",     0.34, 0.33, 0.33),
]
