"""REX market-engine verification suite (read-only vs production).

These tests independently calculate expected results and compare them to
the live implementations. They do not modify production code.
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

from core.chart_analyzer import ChartAnalyzer
from core.features.config import (
    FeatureConfig,
    IndicatorPackConfig,
    PhaseHeuristicConfig,
    RangeExpansionConfig,
    ScoreValueConfig,
    SwingDetectionConfig,
    TrendStrengthConfig,
    default_feature_config,
)
from core.features.context import FeatureContext
from core.features.generators.range_expansion import RangeExpansionGenerator
from core.features.generators.returns import ReturnsGenerator
from core.features.generators.swings import SwingGenerator, TimeframeSwings
from core.features.packs.base import (
    IndicatorPack,
    PricePack,
    SessionPack,
    StructurePack,
    VolatilityPack,
    ZonePack,
)
from core.features.generators.range_expansion import RangeExpansionFeatures
from core.features.generators.returns import ReturnFeatures, TimeframeReturns
from core.features.generators.swings import SwingFeatures
from core.features.repository import FeatureRepository
from core.features.types import (
    METHOD_MOMENTUM_TS_MOM_V1,
    METHOD_PHASE_HEURISTIC_V1,
    METHOD_TREND_MARKET_STRUCTURE_V1,
    METHOD_VOLATILITY_RANGE_EXPANSION_V1,
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
    PACK_ZONES,
)
from core.features.views.momentum import MomentumDirection, MomentumView
from core.features.views.phase import PhaseView
from core.features.views.trend import (
    TimeframeTrendProjection,
    TrendView,
    _classify_swings,
    _multi_timeframe_agreement,
    _structure_score,
)
from core.features.views.volatility import VolatilityView
from core.indicators import IndicatorEngine, PandasTAProvider
from core.market import require_instrument
from core.market.calendar import AlwaysOpenCalendar
from core.market_state import MarketStateBuilder, SectionStatus
from core.session_manager import SessionBucket, SessionManager, TradingSession
from core.zones import ManualZoneProvider, ZoneEngine, ZoneKind
from historical.parser import HistoricalDataParser
from historical.exceptions import HistoricalParseError
from historical.storage import HistoricalStorage
from models.bar import Bar
from models.market_structure import MarketPhase, MarketTrend, RangeExpansionState
from models.zone import Zone, ZoneBook
from strategies.rules.lookback_breakout_rule import LookbackBreakoutRule


def _bar(
    index: int,
    *,
    high: float,
    low: float,
    close: float | None = None,
    open_: float | None = None,
    volume: float | None = 100.0,
    symbol: str = "EURUSD",
    start: datetime | None = None,
) -> Bar:
    base = start or datetime(2026, 1, 1, 0, 0, 0)
    mid = (high + low) / 2.0
    return Bar(
        symbol=symbol,
        timestamp=base + timedelta(minutes=index),
        open=open_ if open_ is not None else mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=volume,
    )


def _ohlc_flat(
    values: list[tuple[float, float, float, float]],
    *,
    volumes: list[float | None] | None = None,
    symbol: str = "EURUSD",
) -> list[Bar]:
    start = datetime(2026, 1, 1, 12, 0, 0)
    out: list[Bar] = []
    for i, (o, h, l, c) in enumerate(values):
        vol = 100.0 if volumes is None else volumes[i]
        out.append(
            Bar(
                symbol=symbol,
                timestamp=start + timedelta(minutes=i),
                open=o,
                high=h,
                low=l,
                close=c,
                volume=vol,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Independently derived golden vector for swings (left=2, right=2)
#
# Index: 0   1   2   3   4   5   6   7   8   9  10
# High: 10  11  15  12  11  10  14  13  12  16  15
# Low:   9   8   7   8   9   6   7   8   9  10   9
#
# Candidates i in [2, 8]:
# i=2 high 15 > {10,11,12,11} → SH; low 7 < {9,8,8,9} → SL
# i=5 low 6 < {8,9,7,8} → SL
# i=6 high 14 > {11,10,13,12} → SH
# Expected highs (chronological): 15, 14
# Expected lows (chronological): 7, 6
# ---------------------------------------------------------------------------
GOLDEN_SWING_HIGHS = (15.0, 14.0)
GOLDEN_SWING_LOWS = (7.0, 6.0)


def _golden_swing_bars() -> list[Bar]:
    highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
    lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
    return [
        _bar(i, high=float(h), low=float(l), close=(h + l) / 2.0)
        for i, (h, l) in enumerate(zip(highs, lows, strict=True))
    ]


class SwingDetectionVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.config = SwingDetectionConfig(left_bars=2, right_bars=2, minimum_swings=2)
        self.gen = SwingGenerator(self.config)
        self.instrument = require_instrument("EURUSD")

    def test_golden_vector_exact_swing_prices(self) -> None:
        features = self.gen.generate(
            {"M15": _golden_swing_bars()},
            self.instrument,
            entry_timeframe="M15",
        )
        swings = features.by_timeframe["M15"]
        self.assertEqual(swings.swing_highs, GOLDEN_SWING_HIGHS)
        self.assertEqual(swings.swing_lows, GOLDEN_SWING_LOWS)

    def test_equal_highs_are_not_swings_under_strict_inequality(self) -> None:
        # Peak at i=2 and i=3 both high=15 — neither strictly greater than other.
        highs = [10, 11, 15, 15, 11, 10, 9]
        lows = [9, 8, 7, 7, 8, 9, 8]
        bars = [
            _bar(i, high=float(h), low=float(l))
            for i, (h, l) in enumerate(zip(highs, lows, strict=True))
        ]
        features = self.gen.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        self.assertEqual(features.by_timeframe["M15"].swing_highs, ())

    def test_right_bars_not_confirmed_as_swings(self) -> None:
        # Highest bar is at the end — within right_bars, must not confirm.
        bars = [
            _bar(0, high=10, low=9),
            _bar(1, high=11, low=8),
            _bar(2, high=12, low=7),
            _bar(3, high=13, low=8),
            _bar(4, high=20, low=9),  # max high, but unconfirmed
        ]
        features = self.gen.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        self.assertNotIn(20.0, features.by_timeframe["M15"].swing_highs)

    def test_left_bars_boundary_not_candidate(self) -> None:
        bars = [
            _bar(0, high=20, low=5),  # leftmost — cannot be candidate for left=2
            _bar(1, high=11, low=8),
            _bar(2, high=12, low=7),
            _bar(3, high=13, low=8),
            _bar(4, high=14, low=9),
        ]
        features = self.gen.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        self.assertNotIn(20.0, features.by_timeframe["M15"].swing_highs)

    def test_left_right_config_respected(self) -> None:
        bars = _golden_swing_bars()
        narrow = SwingGenerator(
            SwingDetectionConfig(left_bars=1, right_bars=1, minimum_swings=2)
        )
        wide = SwingGenerator(
            SwingDetectionConfig(left_bars=3, right_bars=3, minimum_swings=2)
        )
        n = narrow.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        w = wide.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        # Wider window is stricter → fewer or equal swings
        self.assertGreaterEqual(
            len(n.by_timeframe["M15"].swing_highs),
            len(w.by_timeframe["M15"].swing_highs),
        )
        # left=1,right=1 should include index-2 high=15 (left=[11], right=[12])
        self.assertIn(15.0, n.by_timeframe["M15"].swing_highs)

    def test_insufficient_bars_return_empty(self) -> None:
        bars = [_bar(i, high=10 + i, low=9) for i in range(4)]  # need 5 for L=2,R=2
        features = self.gen.generate({"M15": bars}, self.instrument, entry_timeframe="M15")
        self.assertEqual(features.by_timeframe["M15"].swing_highs, ())
        self.assertEqual(features.by_timeframe["M15"].swing_lows, ())

    def test_output_order_is_chronological(self) -> None:
        features = self.gen.generate(
            {"M15": _golden_swing_bars()},
            self.instrument,
            entry_timeframe="M15",
        )
        highs = features.by_timeframe["M15"].swing_highs
        # Chronological detection order: 15 then 14 (not sorted by price)
        self.assertEqual(highs, (15.0, 14.0))


class SwingModelCompletenessVerification(unittest.TestCase):
    def test_timeframe_swings_carry_event_identity_and_timing(self) -> None:
        from core.features.generators.swings import SwingEvent

        fields = set(TimeframeSwings.__dataclass_fields__)
        self.assertEqual(fields, {"timeframe", "swings"})
        event_fields = set(SwingEvent.__dataclass_fields__)
        for required in {
            "id",
            "kind",
            "price",
            "index",
            "timestamp",
            "confirmation_index",
            "confirmation_time",
            "timeframe",
        }:
            self.assertIn(required, event_fields)


class HHHLRepresentationVerification(unittest.TestCase):
    def test_no_explicit_hh_hl_lh_ll_types_in_trend_projection(self) -> None:
        fields = set(TimeframeTrendProjection.__dataclass_fields__)
        self.assertNotIn("hh", fields)
        self.assertNotIn("hl", fields)
        self.assertNotIn("lh", fields)
        self.assertNotIn("ll", fields)
        self.assertNotIn("structure_events", fields)

    def test_hh_hl_only_appear_in_reason_string(self) -> None:
        swings = TimeframeSwings.from_prices(
            "M15",
            swing_highs=(10.0, 12.0),
            swing_lows=(8.0, 9.0),
        )
        projection = _classify_swings(swings, minimum_swings=2)
        self.assertEqual(projection.trend, MarketTrend.BULLISH)
        self.assertIn("higher highs", projection.reason)
        self.assertIn("higher lows", projection.reason)
        # No structured HH/HL objects — only prose
        self.assertIsInstance(projection.reason, str)

    def test_mixed_sequence_is_ranging_not_partial_hh_hl(self) -> None:
        # Rising highs but falling lows → not bullish, not bearish
        swings = TimeframeSwings.from_prices(
            "M15",
            swing_highs=(10.0, 12.0),
            swing_lows=(9.0, 8.0),
        )
        projection = _classify_swings(swings, minimum_swings=2)
        self.assertEqual(projection.trend, MarketTrend.RANGING)


class LookbackBreakoutVerification(unittest.TestCase):
    """Legacy lookback max/min breakout (explicitly NOT structural BOS)."""

    def test_bullish_close_above_lookback_max_high(self) -> None:
        candles = [
            _bar(i, high=1.10 + 0.001 * i, low=1.09, close=1.095)
            for i in range(10)
        ]
        candles.append(_bar(10, high=1.20, low=1.10, close=1.19, open_=1.11))
        result = LookbackBreakoutRule(lookback=10).detect(
            candles, bullish=True, bearish=False
        )
        self.assertTrue(result.detected)
        self.assertTrue(result.bullish)
        self.assertEqual(result.broken_swing_price, max(c.high for c in candles[:-1]))

    def test_wick_only_break_without_close_is_not_breakout(self) -> None:
        prior = [_bar(i, high=1.10, low=1.09, close=1.095) for i in range(10)]
        prior.append(_bar(10, high=1.25, low=1.09, close=1.094, open_=1.093))
        result = LookbackBreakoutRule(lookback=10).detect(
            prior, bullish=True, bearish=False
        )
        self.assertFalse(result.detected)

    def test_lookback_breakout_uses_extremum_not_fractal_swing(self) -> None:
        bars = list(_golden_swing_bars())
        bars.append(_bar(11, high=17, low=10, close=16.5, open_=15))
        result = LookbackBreakoutRule(lookback=10).detect(
            bars, bullish=True, bearish=False
        )
        self.assertTrue(result.detected)
        self.assertEqual(result.broken_swing_price, 16.0)

    def test_requires_caller_direction_flag(self) -> None:
        candles = [_bar(i, high=1.1, low=1.0, close=1.05) for i in range(11)]
        candles[-1] = _bar(10, high=2.0, low=1.0, close=1.9)
        result = LookbackBreakoutRule(lookback=10).detect(
            candles, bullish=False, bearish=False
        )
        self.assertFalse(result.detected)


class CHOCHVerification(unittest.TestCase):
    def test_no_choch_module_in_working_tree(self) -> None:
        root = Path(__file__).resolve().parents[1]
        choch_paths = list(root.glob("**/choch*.py"))
        # Ignore .venv
        choch_paths = [p for p in choch_paths if ".venv" not in p.parts]
        self.assertEqual(choch_paths, [])

    def test_structure_pack_has_no_choch_field(self) -> None:
        fields = set(StructurePack.__dataclass_fields__)
        self.assertEqual(fields, {"pack_id", "swings"})


class StructureScoreVerification(unittest.TestCase):
    def test_structure_score_is_config_lookup_not_calculated(self) -> None:
        config = default_feature_config()
        self.assertEqual(
            _structure_score(MarketTrend.BULLISH, config),
            config.trend_strength.aligned_structure_score,
        )
        self.assertEqual(
            _structure_score(MarketTrend.BEARISH, config),
            config.trend_strength.aligned_structure_score,
        )
        self.assertEqual(
            _structure_score(MarketTrend.RANGING, config),
            config.trend_strength.ranging_score,
        )
        self.assertEqual(
            _structure_score(MarketTrend.UNKNOWN, config),
            config.trend_strength.unknown_score,
        )
        # Prove it's a constant for all bullish cases — not magnitude-based
        self.assertEqual(_structure_score(MarketTrend.BULLISH, config), 85)

    def test_insufficient_swings_unknown_structure_score_zero(self) -> None:
        swings = TimeframeSwings.from_prices(
            "M15", swing_highs=(10.0,), swing_lows=(8.0,)
        )
        projection = _classify_swings(swings, minimum_swings=2)
        self.assertEqual(projection.trend, MarketTrend.UNKNOWN)
        score = _structure_score(projection.trend, default_feature_config())
        self.assertEqual(score, 0)


class MultiTimeframeVerification(unittest.TestCase):
    def _proj(self, tf: str, trend: MarketTrend) -> TimeframeTrendProjection:
        return TimeframeTrendProjection(
            timeframe=tf,
            trend=trend,
            reason="test",
            swing_highs=(1.0, 2.0),
            swing_lows=(0.5, 1.0),
        )

    def test_conflicting_timeframes_are_not_full_alignment(self) -> None:
        config = default_feature_config()
        by_tf = {
            "M15": self._proj("M15", MarketTrend.BULLISH),
            "M30": self._proj("M30", MarketTrend.BEARISH),
            "H1": self._proj("H1", MarketTrend.BULLISH),
            "H4": self._proj("H4", MarketTrend.BULLISH),
        }
        mtf = _multi_timeframe_agreement(
            entry_timeframe="M15",
            entry_trend=MarketTrend.BULLISH,
            by_timeframe=by_tf,
            mapping=dict(config.multi_timeframe_mapping),
            config=config,
        )
        # M30 disagree → not aligned; H1+H4 agree → partial
        self.assertEqual(mtf.score, config.score_values.partial)
        self.assertIn("Some higher timeframes agree", mtf.reason)
        self.assertNotIn("All configured higher timeframes agree", mtf.reason)

    def test_all_disagree_is_neutral(self) -> None:
        config = default_feature_config()
        by_tf = {
            "M15": self._proj("M15", MarketTrend.BULLISH),
            "M30": self._proj("M30", MarketTrend.BEARISH),
            "H1": self._proj("H1", MarketTrend.BEARISH),
            "H4": self._proj("H4", MarketTrend.RANGING),
        }
        mtf = _multi_timeframe_agreement(
            entry_timeframe="M15",
            entry_trend=MarketTrend.BULLISH,
            by_timeframe=by_tf,
            mapping=dict(config.multi_timeframe_mapping),
            config=config,
        )
        self.assertEqual(mtf.score, config.score_values.neutral)

    def test_missing_htf_prevents_full_alignment(self) -> None:
        config = default_feature_config()
        by_tf = {
            "M15": self._proj("M15", MarketTrend.BULLISH),
            "M30": self._proj("M30", MarketTrend.BULLISH),
            # H1, H4 missing
        }
        mtf = _multi_timeframe_agreement(
            entry_timeframe="M15",
            entry_trend=MarketTrend.BULLISH,
            by_timeframe=by_tf,
            mapping=dict(config.multi_timeframe_mapping),
            config=config,
        )
        self.assertEqual(mtf.score, config.score_values.partial)
        self.assertIn("Missing", mtf.reason)

    def test_feature_repository_causally_builds_htf_from_entry(self) -> None:
        # Enough M15 history for completed M30/H1 (H4 may or may not complete).
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [
            Bar(
                symbol="EURUSD",
                timestamp=start + timedelta(minutes=15 * index),
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.15,
                volume=1.0,
            )
            for index in range(40)
        ]
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": bars},
            entry_timeframe="M15",
            asof=start + timedelta(minutes=15 * 39),
            pack_ids=(PACK_STRUCTURE,),
        )
        structure = context.require_pack(PACK_STRUCTURE, StructurePack)
        assert isinstance(structure, StructurePack)
        self.assertIn("M15", structure.swings.by_timeframe)
        self.assertIn("M30", context.bars_by_timeframe)
        self.assertIn("H1", context.bars_by_timeframe)
        # Every HTF bar must be completed by asof.
        asof = context.asof
        for timeframe in ("M30", "H1", "H4"):
            for bar in context.bars_by_timeframe.get(timeframe, ()):
                completion = bar.timestamp + timedelta(
                    minutes={"M30": 30, "H1": 60, "H4": 240}[timeframe]
                )
                self.assertLessEqual(completion, asof)


class MomentumVerification(unittest.TestCase):
    def test_ts_mom_cumulative_return_matches_independent_calc(self) -> None:
        closes = [100.0, 101.0, 102.0, 103.0]
        # Independent expected simple returns
        expected_returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))
        ]
        expected_cum = sum(expected_returns)
        bars = [
            Bar(
                symbol="EURUSD",
                timestamp=datetime(2026, 1, 1) + timedelta(minutes=i),
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1.0,
            )
            for i, c in enumerate(closes)
        ]
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": bars},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE,),
        )
        projection = MomentumView().project(context, METHOD_MOMENTUM_TS_MOM_V1)
        self.assertEqual(projection.direction, MomentumDirection.BULLISH)
        self.assertAlmostEqual(projection.strength, abs(expected_cum), places=12)
        self.assertAlmostEqual(projection.strength, expected_cum, places=12)

    def test_lookback_hardcoded_to_20(self) -> None:
        # Build >20 returns; strength must equal abs(sum(last 20)), not all
        closes = [100.0 + i for i in range(30)]
        all_returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))
        ]
        expected = abs(sum(all_returns[-20:]))
        not_all = abs(sum(all_returns))
        self.assertNotAlmostEqual(expected, not_all)
        bars = [
            Bar(
                symbol="EURUSD",
                timestamp=datetime(2026, 1, 1) + timedelta(minutes=i),
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1.0,
            )
            for i, c in enumerate(closes)
        ]
        context = FeatureRepository().materialize(
            "EURUSD", {"M15": bars}, entry_timeframe="M15", pack_ids=(PACK_PRICE,)
        )
        projection = MomentumView().project(context, METHOD_MOMENTUM_TS_MOM_V1)
        self.assertAlmostEqual(projection.strength, expected, places=12)

    def test_empty_returns_unknown(self) -> None:
        bars = [
            Bar(
                symbol="EURUSD",
                timestamp=datetime(2026, 1, 1),
                open=1.0,
                high=1.0,
                low=1.0,
                close=1.0,
            )
        ]
        context = FeatureRepository().materialize(
            "EURUSD", {"M15": bars}, entry_timeframe="M15", pack_ids=(PACK_PRICE,)
        )
        projection = MomentumView().project(context, METHOD_MOMENTUM_TS_MOM_V1)
        self.assertEqual(projection.direction, MomentumDirection.UNKNOWN)
        self.assertEqual(projection.strength, 0.0)

    def test_zero_price_return_coerced_to_zero(self) -> None:
        returns = ReturnsGenerator().generate(
            {
                "M15": [
                    Bar(
                        symbol="EURUSD",
                        timestamp=datetime(2026, 1, 1, 0, 0),
                        open=0,
                        high=0,
                        low=0,
                        close=0,
                    ),
                    Bar(
                        symbol="EURUSD",
                        timestamp=datetime(2026, 1, 1, 0, 1),
                        open=1,
                        high=1,
                        low=1,
                        close=1,
                    ),
                ]
            },
            require_instrument("EURUSD"),
            entry_timeframe="M15",
        )
        self.assertEqual(returns.by_timeframe["M15"].simple_returns, (0.0,))


class IndicatorVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PandasTAProvider()
        self.engine = IndicatorEngine(self.provider)

    def test_sma_exact_known_value(self) -> None:
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        bars = _ohlc_flat([(c, c, c, c) for c in closes])
        series = self.provider.sma(bars, length=3)
        # Independent: avg(1,2,3)=2, avg(2,3,4)=3, avg(3,4,5)=4
        self.assertTrue(math.isnan(series.iloc[0]))
        self.assertTrue(math.isnan(series.iloc[1]))
        self.assertAlmostEqual(float(series.iloc[2]), 2.0)
        self.assertAlmostEqual(float(series.iloc[3]), 3.0)
        self.assertAlmostEqual(float(series.iloc[4]), 4.0)

    def test_rsi_monotonic_up_near_100_after_warmup(self) -> None:
        closes = [float(i) for i in range(1, 40)]
        bars = _ohlc_flat([(c, c + 0.1, c - 0.1, c) for c in closes])
        series = self.provider.rsi(bars, length=14)
        self.assertTrue(series.iloc[:14].isna().all() or series.isna().any())
        last = float(series.dropna().iloc[-1])
        self.assertGreaterEqual(last, 70.0)
        self.assertLessEqual(last, 100.0)

    def test_macd_histogram_equals_macd_minus_signal(self) -> None:
        closes = [float(i) for i in range(1, 60)]
        bars = _ohlc_flat([(c, c + 0.1, c - 0.1, c) for c in closes])
        result = self.provider.macd(bars, fast=12, slow=26, signal=9)
        for i in range(len(bars)):
            m = result.macd.iloc[i]
            s = result.signal.iloc[i]
            h = result.histogram.iloc[i]
            if math.isnan(m) or math.isnan(s) or math.isnan(h):
                continue
            self.assertAlmostEqual(float(h), float(m) - float(s), places=10)

    def test_atr_positive_after_warmup(self) -> None:
        bars = _ohlc_flat(
            [(1.0, 1.2, 0.8, 1.0)] * 30
        )
        series = self.provider.atr(bars, length=14)
        self.assertGreater(float(series.dropna().iloc[-1]), 0.0)

    def test_rvol_exact_ratio_and_excludes_current(self) -> None:
        volumes: list[float | None] = [10.0] * 20 + [25.0]
        bars = _ohlc_flat([(1, 1, 1, 1)] * 21, volumes=volumes)
        series = self.provider.relative_volume(bars, length=20)
        # Independent: 25 / mean(10*20) = 2.5
        self.assertAlmostEqual(float(series.iloc[-1]), 2.5)
        # If current were included: mean=(10*19+25)/20=10.75 → 25/10.75≈2.325
        self.assertNotAlmostEqual(float(series.iloc[-1]), 25.0 / 10.75, places=3)

    def test_rvol_nan_insufficient_and_missing(self) -> None:
        bars = _ohlc_flat([(1, 1, 1, 1)] * 20, volumes=[10.0] * 20)
        series = self.provider.relative_volume(bars, length=20)
        self.assertTrue(math.isnan(float(series.iloc[-1])))
        bars2 = _ohlc_flat([(1, 1, 1, 1)] * 21, volumes=[10.0] * 20 + [None])
        series2 = self.provider.relative_volume(bars2, length=20)
        self.assertTrue(math.isnan(float(series2.iloc[-1])))

    def test_empty_bars_raise(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.sma((), length=5)


class RangeExpansionVerification(unittest.TestCase):
    def test_ratio_with_known_bodies_and_overlap(self) -> None:
        # bodies: 1,1,1,1,4  historical_window=5 recent_window=2
        # hist avg = (1+1+1+1+4)/5 = 1.6
        # recent avg = (1+4)/2 = 2.5
        # ratio = 2.5/1.6 = 1.5625
        config = RangeExpansionConfig(
            recent_window=2, historical_window=5, low_ratio=0.7, high_ratio=1.3
        )
        values = [
            (0, 1, 0, 1),  # body 1
            (0, 1, 0, 1),
            (0, 1, 0, 1),
            (0, 1, 0, 1),
            (0, 4, 0, 4),  # body 4
        ]
        bars = _ohlc_flat([(o, h, l, c) for o, h, l, c in values])
        result = RangeExpansionGenerator(config).generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        self.assertAlmostEqual(result.ratio or 0.0, 2.5 / 1.6, places=10)
        self.assertEqual(result.state, RangeExpansionState.HIGH)
        # Prove overlap: recent bars are last 2 of historical 5
        self.assertIs(bars[-2], bars[-config.historical_window :][-2])

    def test_insufficient_history_is_unavailable_not_normal(self) -> None:
        config = RangeExpansionConfig(
            recent_window=2, historical_window=5, low_ratio=0.7, high_ratio=1.3
        )
        bars = _ohlc_flat([(0, 1, 0, 1)] * 4)
        result = RangeExpansionGenerator(config).generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        self.assertEqual(result.state, RangeExpansionState.UNAVAILABLE)
        self.assertIsNone(result.ratio)
        self.assertIn("unavailable", result.reason.lower())
        self.assertNotEqual(result.state, RangeExpansionState.NORMAL)

    def test_zero_historical_average_is_unavailable_not_low(self) -> None:
        config = RangeExpansionConfig(
            recent_window=2, historical_window=4, low_ratio=0.7, high_ratio=1.3
        )
        bars = _ohlc_flat([(1, 1, 1, 1)] * 4)  # body 0
        result = RangeExpansionGenerator(config).generate(
            {"M15": bars}, require_instrument("EURUSD"), entry_timeframe="M15"
        )
        self.assertEqual(result.state, RangeExpansionState.UNAVAILABLE)
        self.assertIsNone(result.ratio)
        self.assertNotEqual(result.state, RangeExpansionState.LOW)


class PhaseVerification(unittest.TestCase):
    def test_reversal_is_residual_fallback(self) -> None:
        # Read source contract: else branch reason
        import inspect

        source = inspect.getsource(PhaseView.project)
        self.assertIn('phase = MarketPhase.REVERSAL', source)
        self.assertIn(
            "Directional structure without strong-trend structure score", source
        )

    def test_compression_when_range_expansion_low(self) -> None:
        # Build config where LOW score triggers compression, then verify via
        # score mapping (independent of full materialization path).
        config = default_feature_config()
        from core.features.views.phase import _range_expansion_score

        score = _range_expansion_score(RangeExpansionState.LOW, config)
        self.assertEqual(score, config.score_values.range_expansion_low)
        self.assertLessEqual(
            score, config.phase.compression_range_expansion_score_max
        )


class ZoneVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.book = ZoneBook(
            symbol="EURUSD",
            zones=(
                Zone(1, "weak_inside", 1.10, 1.12, "daily", 3, ZoneKind.DEMAND),
                Zone(2, "strong_inside", 1.10, 1.12, "daily", 9, ZoneKind.DEMAND),
                Zone(3, "above", 1.20, 1.22, "weekly", 5, ZoneKind.SUPPLY),
            ),
        )
        self.engine = ZoneEngine(ManualZoneProvider.from_zone_book(self.book))

    def test_zones_are_manual_not_market_derived(self) -> None:
        self.assertTrue(hasattr(ManualZoneProvider, "from_zone_book"))
        # Engine has no detect/generate method
        self.assertFalse(hasattr(self.engine, "detect"))
        self.assertFalse(hasattr(self.engine, "generate"))

    def test_zone_engine_prefers_strongest_inside(self) -> None:
        nearest = self.engine.distance_to_nearest_zone("EURUSD", 1.11)
        assert nearest is not None
        self.assertEqual(nearest.zone.id, 2)
        self.assertEqual(nearest.side, "inside")

    def test_chart_analyzer_prefers_strongest_inside(self) -> None:
        context = ChartAnalyzer().analyze(self.book, 1.11)
        self.assertTrue(context.inside_zone)
        self.assertEqual(context.active_zone_id, 2)  # strongest, not first
        self.assertEqual(context.active_zone_source, "manual")

    def test_chart_analyzer_and_zone_engine_agree_on_preferred_inside(self) -> None:
        engine_zone = self.engine.distance_to_nearest_zone("EURUSD", 1.11)
        chart = ChartAnalyzer().analyze(self.book, 1.11)
        assert engine_zone is not None
        self.assertEqual(engine_zone.zone.id, chart.active_zone_id)
        self.assertEqual(engine_zone.zone.source.value, chart.active_zone_source)

    def test_nearest_zone_picks_closer_edge(self) -> None:
        # Price 1.15:
        #   below zone high 1.12 → 0.03 = 300 pips
        #   above zone low 1.20 → 0.05 = 500 pips
        # Independent expectation: nearest is BELOW at 300 pips.
        nearest = self.engine.distance_to_nearest_zone("EURUSD", 1.15)
        assert nearest is not None
        self.assertEqual(nearest.side, "below")
        self.assertEqual(nearest.zone.id, 2)
        self.assertAlmostEqual(nearest.distance_pips, 300.0)

    def test_nearest_above_when_only_above_is_closer(self) -> None:
        nearest = self.engine.distance_to_nearest_zone("EURUSD", 1.18)
        assert nearest is not None
        self.assertEqual(nearest.side, "above")
        self.assertEqual(nearest.zone.id, 3)
        self.assertAlmostEqual(nearest.distance_pips, 200.0)


class SessionVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SessionManager()

    def test_london_ny_overlap_high_liquidity(self) -> None:
        # 14:00 UTC = London + New York
        at = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        info = self.manager.get_current_session(at)
        self.assertIn(TradingSession.LONDON, info.active_sessions)
        self.assertIn(TradingSession.NEW_YORK, info.active_sessions)
        self.assertTrue(info.overlap)
        self.assertTrue(info.high_liquidity)
        self.assertEqual(info.session, TradingSession.LONDON)  # priority

    def test_boundary_start_inclusive_end_exclusive(self) -> None:
        # London 08:00–17:00 UTC
        start = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
        end = datetime(2026, 6, 15, 17, 0, tzinfo=timezone.utc)
        self.assertIn(
            TradingSession.LONDON, self.manager.get_current_session(start).active_sessions
        )
        self.assertNotIn(
            TradingSession.LONDON, self.manager.get_current_session(end).active_sessions
        )

    def test_research_bucket_overlap(self) -> None:
        at = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        self.assertEqual(
            self.manager.classify_for_research(at),
            SessionBucket.LONDON_NEW_YORK_OVERLAP,
        )

    def test_calendar_is_always_open_stub(self) -> None:
        cal = AlwaysOpenCalendar()
        at = datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc)
        self.assertTrue(cal.is_trading(at))

    def test_naive_datetime_is_silently_accepted(self) -> None:
        # Research risk: naive datetimes do NOT raise; astimezone() treats them
        # as local system time. This is unsafe for research integrity.
        info = self.manager.get_current_session(datetime(2026, 6, 15, 14, 0))
        self.assertIsNotNone(info.session)


class MarketStateFidelityVerification(unittest.TestCase):
    def test_indicator_scalars_match_pack(self) -> None:
        engine = IndicatorEngine(PandasTAProvider())
        volumes = [10.0] * 40 + [20.0]
        closes = [float(i) for i in range(1, 42)]
        bars = [
            Bar(
                symbol="EURUSD",
                timestamp=datetime(2026, 1, 1) + timedelta(minutes=i),
                open=c,
                high=c + 0.1,
                low=c - 0.1,
                close=c,
                volume=v,
            )
            for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
        ]
        repo = FeatureRepository(indicator_engine=engine)
        context = repo.materialize("EURUSD", {"M15": bars}, entry_timeframe="M15")
        pack = context.require_pack(PACK_INDICATORS, IndicatorPack)
        assert isinstance(pack, IndicatorPack)
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.indicators.rsi, pack.rsi_last)
        self.assertEqual(state.indicators.macd, pack.macd_last)
        self.assertEqual(state.indicators.relative_volume, pack.relative_volume_last)
        self.assertAlmostEqual(state.indicators.relative_volume or 0.0, 2.0)

    def test_liquidity_always_unsupported(self) -> None:
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": _golden_swing_bars()},
            entry_timeframe="M15",
        )
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.liquidity.status, SectionStatus.UNSUPPORTED)

    def test_structure_score_85_is_preserved_as_config_constant(self) -> None:
        # Build bullish structure via golden swings repeated for enough swings
        bars = _golden_swing_bars() * 5
        context = FeatureRepository().materialize(
            "EURUSD",
            {"M15": bars, "M30": bars, "H1": bars, "H4": bars},
            entry_timeframe="M15",
        )
        trend = TrendView().project(context, METHOD_TREND_MARKET_STRUCTURE_V1)
        state = MarketStateBuilder().build(context)
        if trend.trend == MarketTrend.BULLISH:
            self.assertEqual(trend.structure_score, 85)
            self.assertEqual(state.structure.structure_score, 85)
            payload = state.to_dict()
            self.assertIn("structure_score", payload["structure"])
            self.assertNotIn("strength", payload["structure"])
            self.assertNotIn("confidence", payload["structure"])


class DataQualityVerification(unittest.TestCase):
    def test_parser_rejects_duplicates(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00Z,1,1.1,0.9,1,1\n"
                "2024-01-01T00:00:00Z,1,1.1,0.9,1,1\n",
                encoding="utf-8",
            )
            with self.assertRaises(HistoricalParseError):
                HistoricalDataParser().parse_file(path, "EURUSD")

    def test_parser_rejects_invalid_ohlc(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00Z,1,0.5,0.9,1,1\n",  # high < open
                encoding="utf-8",
            )
            with self.assertRaises(HistoricalParseError):
                HistoricalDataParser().parse_file(path, "EURUSD")

    def test_has_coverage_false_when_metadata_missing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            storage = HistoricalStorage(root)
            year_path = storage.year_path("EURUSD", "M1", 2024)
            year_path.parent.mkdir(parents=True)
            year_path.write_text(
                "timestamp,open,high,low,close,volume\n"
                "2024-01-01T00:00:00Z,1,1.1,0.9,1,1\n",
                encoding="utf-8",
            )
            # No .meta.json — fail closed (must not invent coverage from CSV).
            from datetime import date

            self.assertFalse(
                storage.has_coverage("EURUSD", "M1", date(2024, 1, 1), date(2024, 12, 31))
            )


class CausalityVerification(unittest.TestCase):
    def test_adding_future_bars_can_confirm_new_swings_only_with_right_window(self) -> None:
        # Up to T: peak candidate without right confirmation
        prefix = [
            _bar(0, high=10, low=9),
            _bar(1, high=11, low=8),
            _bar(2, high=15, low=7),  # candidate — needs 2 right bars
        ]
        gen = SwingGenerator(
            SwingDetectionConfig(left_bars=2, right_bars=2, minimum_swings=1)
        )
        instrument = require_instrument("EURUSD")
        before = gen.generate({"M15": prefix}, instrument, entry_timeframe="M15")
        self.assertEqual(before.by_timeframe["M15"].swing_highs, ())

        confirmed = prefix + [
            _bar(3, high=12, low=8),
            _bar(4, high=11, low=9),
        ]
        after = gen.generate({"M15": confirmed}, instrument, entry_timeframe="M15")
        self.assertEqual(after.by_timeframe["M15"].swing_highs, (15.0,))

    def test_indicator_prefix_recomputation_is_stable(self) -> None:
        # Causality for closed-bar evaluation: compute on data[:T] only.
        closes = [10.0 + ((-1) ** i) * (i % 5) + i * 0.1 for i in range(50)]
        bars = _ohlc_flat([(c, c + 0.1, c - 0.1, c) for c in closes])
        provider = PandasTAProvider()
        t = 30
        rsi_t = float(provider.rsi(bars[:t], length=14).iloc[-1])
        rsi_t_again = float(provider.rsi(bars[:t], length=14).iloc[-1])
        self.assertEqual(rsi_t, rsi_t_again)
        rsi_full_last = float(provider.rsi(bars, length=14).iloc[-1])
        self.assertNotEqual(rsi_t, rsi_full_last)
        # Document whether full-series[t-1] equals prefix evaluation (causal safety).
        rsi_at_t_on_full = float(provider.rsi(bars, length=14).iloc[t - 1])
        # For recursive RSI, these may match or differ depending on library path;
        # prefix recompute must always be stable (asserted above).
        self.assertTrue(math.isfinite(rsi_t))
        self.assertTrue(math.isfinite(rsi_at_t_on_full))


if __name__ == "__main__":
    unittest.main()
