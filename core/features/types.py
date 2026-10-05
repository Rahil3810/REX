"""Shared identifiers for the in-memory feature architecture."""

from typing import NewType

PackId = NewType("PackId", str)
MethodId = NewType("MethodId", str)

PACK_PRICE = PackId("price")
PACK_VOLATILITY = PackId("volatility")
PACK_INDICATORS = PackId("indicators")
PACK_ZONES = PackId("zones")
PACK_SESSION = PackId("session")
PACK_STRUCTURE = PackId("structure")

DEFAULT_PACK_IDS: tuple[PackId, ...] = (
    PACK_PRICE,
    PACK_VOLATILITY,
    PACK_INDICATORS,
    PACK_ZONES,
    PACK_SESSION,
    PACK_STRUCTURE,
)

METHOD_TREND_MARKET_STRUCTURE_V1 = MethodId("market_structure_v1")
METHOD_TREND_DRIFT_V1 = MethodId("drift_v1")
METHOD_MOMENTUM_TS_MOM_V1 = MethodId("ts_mom_v1")
METHOD_VOLATILITY_RANGE_EXPANSION_V1 = MethodId("range_expansion_v1")
METHOD_PHASE_HEURISTIC_V1 = MethodId("heuristic_v1")
METHOD_LIQUIDITY_UNSUPPORTED = MethodId("unsupported")
METHOD_STRUCTURE_SWING_BOS_V1 = MethodId("swing_bos_v1")
