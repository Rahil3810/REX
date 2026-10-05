"""Tests for deterministic MarketState builder and serialization."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone

from core.features import (
    FeatureRepository,
    PACK_INDICATORS,
    PACK_PRICE,
    PACK_SESSION,
    PACK_STRUCTURE,
    PACK_VOLATILITY,
    PACK_ZONES,
)
from core.indicators import IndicatorEngine, PandasTAProvider
from core.market_state import (
    MARKET_STATE_SCHEMA_VERSION,
    MarketStateBuilder,
    SectionStatus,
)
from core.zones import ManualZoneProvider, ZoneEngine, ZoneKind
from models.bar import Bar
from models.market_structure import MarketTrend, RangeExpansionState
from models.zone import Zone, ZoneBook


def _trend_bars(
    symbol: str,
    direction: str,
    count: int = 70,
    start: float = 1.1000,
    small_body: float = 0.0004,
    large_recent_body: bool = False,
    *,
    volume: float | None = 100.0,
) -> list[Bar]:
    bars: list[Bar] = []
    slope = 0.0010 if direction == "up" else -0.0010
    timestamp = datetime(2026, 6, 20, 0, 0, 0)

    for index in range(count):
        close = start + slope * index
        body = 0.0020 if large_recent_body and index >= count - 5 else small_body
        open_price = close - body if direction == "up" else close + body
        high = max(open_price, close) + 0.0006
        low = min(open_price, close) - 0.0006

        if index % 6 == 2:
            high += 0.0030
        if index % 6 == 5:
            low -= 0.0030

        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp + timedelta(minutes=15 * index),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return bars


def _volume_bars(symbol: str, volumes: list[float | None]) -> list[Bar]:
    timestamp = datetime(2026, 6, 20, 0, 0, 0)
    bars: list[Bar] = []
    for index, volume in enumerate(volumes):
        close = 1.1000 + 0.0005 * index
        bars.append(
            Bar(
                symbol=symbol,
                timestamp=timestamp + timedelta(minutes=15 * index),
                open=close - 0.0003,
                high=close + 0.0006,
                low=close - 0.0006,
                close=close,
                volume=volume,
            )
        )
    return bars


def _htf_book() -> ZoneBook:
    return ZoneBook(
        symbol="EURUSD",
        zones=(
            Zone(
                id=4,
                name="daily_supply",
                low=1.1100,
                high=1.1120,
                timeframe="daily",
                strength=7,
                kind=ZoneKind.SUPPLY,
            ),
            Zone(
                id=5,
                name="daily_demand",
                low=1.0900,
                high=1.0920,
                timeframe="D1",
                strength=7,
                kind=ZoneKind.DEMAND,
            ),
        ),
    )


class MarketStateBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = IndicatorEngine(PandasTAProvider())
        self.zone_engine = ZoneEngine(ManualZoneProvider.from_zone_book(_htf_book()))
        self.repo = FeatureRepository(
            zone_engine=self.zone_engine,
            indicator_engine=self.engine,
        )
        self.bars = {
            "M15": _trend_bars("EURUSD", "up", count=200),
            "M30": _trend_bars("EURUSD", "up", count=200),
            "H1": _trend_bars("EURUSD", "up", count=200),
            "H4": _trend_bars("EURUSD", "up", count=200),
        }
        self.context = self.repo.materialize(
            "EURUSD",
            self.bars,
            entry_timeframe="M15",
            asof=datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc),
        )
        self.builder = MarketStateBuilder()

    def test_complete_context_produces_valid_market_state(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.metadata.instrument, "EURUSD")
        self.assertEqual(state.metadata.entry_timeframe, "M15")
        self.assertEqual(state.price.status, SectionStatus.AVAILABLE)
        self.assertIsNotNone(state.price.current)
        self.assertEqual(state.structure.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.momentum.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.indicators.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.volatility.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.zones.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.session.status, SectionStatus.AVAILABLE)

    def test_market_state_is_immutable(self) -> None:
        state = self.builder.build(self.context)
        with self.assertRaises(Exception):
            state.price.current = 1.9999  # type: ignore[misc]

    def test_serializes_to_json(self) -> None:
        state = self.builder.build(self.context)
        payload = json.loads(state.to_json())
        self.assertIn("metadata", payload)
        self.assertIn("indicators", payload)
        self.assertIn("structure", payload)

    def test_json_contains_schema_version(self) -> None:
        state = self.builder.build(self.context)
        payload = json.loads(state.to_json())
        self.assertEqual(
            payload["metadata"]["schema_version"],
            MARKET_STATE_SCHEMA_VERSION,
        )
        self.assertTrue(payload["metadata"]["schema_hash"])
        self.assertEqual(
            payload["metadata"]["context_schema_hash"],
            self.context.schema_hash,
        )

    def test_rsi_appears_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.indicators.status, SectionStatus.AVAILABLE)
        self.assertIsNotNone(state.indicators.rsi)
        self.assertGreaterEqual(state.indicators.rsi or 0.0, 0.0)
        self.assertLessEqual(state.indicators.rsi or 100.0, 100.0)

    def test_macd_components_appear_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertIsNotNone(state.indicators.macd)
        self.assertIsNotNone(state.indicators.macd_signal)
        self.assertIsNotNone(state.indicators.macd_histogram)

    def test_relative_volume_appears_correctly(self) -> None:
        volumes: list[float | None] = [10.0] * 40 + [20.0]
        context = self.repo.materialize(
            "EURUSD",
            {"M15": _volume_bars("EURUSD", volumes)},
            entry_timeframe="M15",
        )
        state = self.builder.build(context)
        self.assertAlmostEqual(state.indicators.relative_volume or 0.0, 2.0)

    def test_ema_and_atr_appear_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertIsNotNone(state.indicators.ema_fast)
        self.assertIsNotNone(state.indicators.ema_slow)
        self.assertIsNotNone(state.indicators.atr)
        self.assertIsNotNone(state.volatility.atr)

    def test_trend_and_method_id_appear_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.structure.method_id, "market_structure_v1")
        self.assertEqual(state.structure.trend, MarketTrend.BULLISH.value)
        self.assertGreater(state.structure.structure_score or 0, 0)
        self.assertIn("higher highs", state.structure.reason or "")

    def test_multi_timeframe_agreement_appears_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertIsNotNone(state.structure.multi_timeframe)
        assert state.structure.multi_timeframe is not None
        # Score is always defined; full alignment is not guaranteed under causal
        # HTF rebuild from a single trending LTF series.
        self.assertIsNotNone(state.structure.multi_timeframe.score)
        self.assertIsNotNone(state.structure.multi_timeframe.reason)
        self.assertGreaterEqual(len(state.structure.by_timeframe), 1)

    def test_zones_appear_correctly(self) -> None:
        inside_price = 1.1110
        context = self.repo.materialize(
            "EURUSD",
            {
                "M15": [
                    Bar(
                        symbol="EURUSD",
                        timestamp=datetime(2026, 6, 20, 12, 0, 0),
                        open=inside_price,
                        high=inside_price + 0.0005,
                        low=inside_price - 0.0005,
                        close=inside_price,
                        volume=100.0,
                    )
                ]
            },
            entry_timeframe="M15",
        )
        state = self.builder.build(context)
        self.assertEqual(state.zones.status, SectionStatus.AVAILABLE)
        self.assertTrue(state.zones.inside_zone)
        self.assertGreaterEqual(len(state.zones.active_zones), 1)
        self.assertIsNotNone(state.zones.nearest)
        assert state.zones.nearest is not None
        self.assertEqual(state.zones.nearest.side, "inside")

    def test_session_information_appears_correctly(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.session.status, SectionStatus.AVAILABLE)
        self.assertIsNotNone(state.session.session)
        self.assertIsInstance(state.session.overlap, bool)
        self.assertIsInstance(state.session.high_liquidity, bool)
        self.assertGreater(len(state.session.active_sessions), 0)

    def test_missing_indicator_pack_is_explicitly_unavailable(self) -> None:
        context = self.repo.materialize(
            "EURUSD",
            self.bars,
            entry_timeframe="M15",
            pack_ids=(
                PACK_PRICE,
                PACK_STRUCTURE,
                PACK_VOLATILITY,
                PACK_ZONES,
                PACK_SESSION,
            ),
        )
        state = self.builder.build(context)
        self.assertEqual(state.indicators.status, SectionStatus.UNAVAILABLE)
        self.assertIsNone(state.indicators.rsi)
        self.assertIn("not materialized", state.indicators.reason or "")

    def test_missing_volume_yields_none_relative_volume(self) -> None:
        context = self.repo.materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up", volume=None)},
            entry_timeframe="M15",
        )
        state = self.builder.build(context)
        self.assertIsNone(state.indicators.relative_volume)

    def test_liquidity_is_unsupported_not_fabricated(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.liquidity.status, SectionStatus.UNSUPPORTED)
        self.assertEqual(state.liquidity.method_id, "unsupported")
        self.assertIn("not implemented", state.liquidity.reason.lower())

    def test_same_context_produces_identical_output(self) -> None:
        first = self.builder.build(self.context)
        second = self.builder.build(self.context)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_json(), second.to_json())

    def test_phase_section_available_with_default_method(self) -> None:
        state = self.builder.build(self.context)
        self.assertEqual(state.phase.status, SectionStatus.AVAILABLE)
        self.assertEqual(state.phase.method_id, "heuristic_v1")
        self.assertIsNotNone(state.phase.phase)

    def test_entry_timeframe_swing_snapshot_present(self) -> None:
        state = self.builder.build(self.context)
        self.assertIsNotNone(state.structure.entry_timeframe)
        assert state.structure.entry_timeframe is not None
        self.assertEqual(state.structure.entry_timeframe.timeframe, "M15")
        self.assertGreater(len(state.structure.entry_timeframe.swing_highs), 0)
        self.assertGreater(len(state.structure.entry_timeframe.swing_lows), 0)


class MarketStateVolatilityTests(unittest.TestCase):
    def test_range_expansion_state_in_market_state(self) -> None:
        repo = FeatureRepository()
        context = repo.materialize(
            "EURUSD",
            {"M15": _trend_bars("EURUSD", "up", large_recent_body=True)},
            entry_timeframe="M15",
        )
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.volatility.status, SectionStatus.AVAILABLE)
        self.assertEqual(
            state.volatility.range_expansion_state,
            RangeExpansionState.HIGH.value,
        )
        self.assertIsNotNone(state.volatility.range_expansion_ratio)


if __name__ == "__main__":
    unittest.main()
