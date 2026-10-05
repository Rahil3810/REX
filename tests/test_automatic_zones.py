"""Automatic Zone Generation V1 — focused regression tests."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone

from core.features import FeatureRepository, PACK_PRICE, PACK_ZONES
from core.features.config import SwingDetectionConfig
from core.features.generators.swings import (
    SwingEvent,
    SwingGenerator,
    SwingKind,
    make_swing_id,
)
from core.market_state import MarketStateBuilder, SectionStatus
from core.zones import (
    AutomaticZoneGenerator,
    AutomaticZoneProvider,
    CompositeZoneProvider,
    ManualZoneProvider,
    ZoneEngine,
    ZoneKind,
    ZoneLifecycleStatus,
    ZoneSource,
)
from core.zones.auto import AutomaticZone, SwingClusterZoneConfig
from models.bar import Bar
from models.zone import Zone, ZoneBook


def _ts(minute: int) -> datetime:
    return datetime(2024, 1, 2, tzinfo=timezone.utc) + timedelta(minutes=minute)


def _bar(
    minute: int,
    *,
    high: float,
    low: float,
    close: float | None = None,
    open_: float | None = None,
) -> Bar:
    mid = (high + low) / 2
    return Bar(
        symbol="EURUSD",
        timestamp=_ts(minute),
        open=open_ if open_ is not None else mid,
        high=high,
        low=low,
        close=close if close is not None else mid,
        volume=1.0,
    )


def _swing(
    kind: SwingKind,
    *,
    index: int,
    price: float,
    confirmation_index: int,
    timeframe: str = "M15",
) -> SwingEvent:
    return SwingEvent(
        id=make_swing_id(timeframe, kind, index),
        timeframe=timeframe,
        kind=kind,
        price=price,
        index=index,
        timestamp=_ts(index),
        confirmation_index=confirmation_index,
        confirmation_time=_ts(confirmation_index),
    )


def _flat_bars(count: int, price: float = 1.10) -> list[Bar]:
    return [
        _bar(i, high=price + 0.0002, low=price - 0.0002, close=price)
        for i in range(count)
    ]


def _config(**overrides: object) -> SwingClusterZoneConfig:
    payload = dict(
        atr_period=10_000,  # force absolute tolerance path in most unit tests
        absolute_price_tolerance=0.0010,
        single_swing_half_width_absolute=0.0005,
        cluster_atr_multiple=0.35,
        min_contributing_swings=1,
        departure_lookback_bars=5,
    )
    payload.update(overrides)
    return SwingClusterZoneConfig(**payload)  # type: ignore[arg-type]


class AutomaticZoneGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = AutomaticZoneGenerator(cluster_config=_config())

    def test_single_swing_high_creates_supply_candidate(self) -> None:
        bars = _flat_bars(20)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=10, swings=[high]
        )
        self.assertEqual(len(zones), 1)
        zone = zones[0].zone
        self.assertEqual(zone.kind, ZoneKind.SUPPLY)
        self.assertEqual(zone.source, ZoneSource.AUTOMATIC)
        self.assertAlmostEqual(zone.low, 1.1050 - 0.0005)
        self.assertAlmostEqual(zone.high, 1.1050 + 0.0005)
        self.assertEqual(zones[0].evidence.origin_swing_id, high.id)

    def test_single_swing_low_creates_demand_candidate(self) -> None:
        bars = _flat_bars(20)
        low = _swing(SwingKind.LOW, index=5, price=1.0950, confirmation_index=7)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=10, swings=[low]
        )
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].zone.kind, ZoneKind.DEMAND)
        self.assertEqual(zones[0].zone.source, ZoneSource.AUTOMATIC)

    def test_nearby_highs_cluster_into_one_supply_zone(self) -> None:
        bars = _flat_bars(30)
        swings = [
            _swing(SwingKind.HIGH, index=5, price=1.1000, confirmation_index=7),
            _swing(SwingKind.HIGH, index=12, price=1.1008, confirmation_index=14),
        ]
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=20, swings=swings
        )
        supply = [z for z in zones if z.zone.kind is ZoneKind.SUPPLY]
        self.assertEqual(len(supply), 1)
        self.assertEqual(supply[0].evidence.contributing_swing_count, 2)
        self.assertAlmostEqual(supply[0].zone.low, 1.1000)
        self.assertAlmostEqual(supply[0].zone.high, 1.1008)

    def test_nearby_lows_cluster_into_one_demand_zone(self) -> None:
        bars = _flat_bars(30)
        swings = [
            _swing(SwingKind.LOW, index=5, price=1.0900, confirmation_index=7),
            _swing(SwingKind.LOW, index=12, price=1.0907, confirmation_index=14),
        ]
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=20, swings=swings
        )
        demand = [z for z in zones if z.zone.kind is ZoneKind.DEMAND]
        self.assertEqual(len(demand), 1)
        self.assertEqual(demand[0].evidence.contributing_swing_count, 2)

    def test_distant_swings_remain_separate(self) -> None:
        bars = _flat_bars(40)
        swings = [
            _swing(SwingKind.HIGH, index=5, price=1.1000, confirmation_index=7),
            _swing(SwingKind.HIGH, index=20, price=1.1050, confirmation_index=22),
        ]
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=30, swings=swings
        )
        supply = [z for z in zones if z.zone.kind is ZoneKind.SUPPLY]
        self.assertEqual(len(supply), 2)

    def test_exact_boundary_behavior_close_equal_not_broken(self) -> None:
        bars = _flat_bars(20, price=1.10)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        # After confirmation, close exactly at upper bound — not broken for supply
        bars[12] = _bar(12, high=1.1060, low=1.1040, close=1.1050 + 0.0005)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=[high]
        )
        self.assertEqual(zones[0].evidence.status, ZoneLifecycleStatus.TESTED)
        self.assertGreaterEqual(zones[0].evidence.mitigation_count, 1)

    def test_deterministic_zone_ids_and_repeated_generation(self) -> None:
        bars = _flat_bars(25)
        swings = [_swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)]
        a = self.generator.generate(bars, timeframe="M15", asof_index=15, swings=swings)
        b = self.generator.generate(bars, timeframe="M15", asof_index=15, swings=swings)
        self.assertEqual(a, b)
        self.assertEqual(a[0].zone.id, b[0].zone.id)
        self.assertGreater(a[0].zone.id, 0)

    def test_future_bars_do_not_change_earlier_asof_result(self) -> None:
        bars = _flat_bars(20)
        swings = [_swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)]
        first = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=swings
        )
        snapshot = copy.deepcopy(first)
        bars.extend(_flat_bars(10, price=1.20))
        # mutate future prices dramatically
        for i in range(20, 30):
            bars[i] = _bar(i, high=2.0, low=1.9, close=1.95)
        second = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=swings
        )
        self.assertEqual(second, snapshot)

    def test_unconfirmed_future_swings_cannot_create_historical_zones(self) -> None:
        bars = _flat_bars(15)
        future = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=20)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=10, swings=[future]
        )
        self.assertEqual(zones, ())

    def test_supply_demand_classification(self) -> None:
        bars = _flat_bars(30)
        swings = [
            _swing(SwingKind.HIGH, index=5, price=1.1100, confirmation_index=7),
            _swing(SwingKind.LOW, index=10, price=1.0900, confirmation_index=12),
        ]
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=20, swings=swings
        )
        kinds = {z.zone.kind for z in zones}
        self.assertEqual(kinds, {ZoneKind.SUPPLY, ZoneKind.DEMAND})

    def test_touch_counting_uses_wick_overlap(self) -> None:
        bars = _flat_bars(20, price=1.10)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        # Wick into band, close outside below — touch but not mitigation/break
        upper = 1.1050 + 0.0005
        lower = 1.1050 - 0.0005
        bars[10] = _bar(10, high=upper - 0.0001, low=1.1000, close=1.1010)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=10, swings=[high]
        )
        self.assertGreaterEqual(zones[0].evidence.touch_count, 1)
        self.assertEqual(zones[0].evidence.mitigation_count, 0)
        self.assertEqual(zones[0].evidence.status, ZoneLifecycleStatus.FRESH)
        self.assertTrue(lower <= upper)

    def test_mitigation_lifecycle_tested(self) -> None:
        bars = _flat_bars(20, price=1.10)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        bars[11] = _bar(11, high=1.1060, low=1.1040, close=1.1050)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=11, swings=[high]
        )
        self.assertEqual(zones[0].evidence.status, ZoneLifecycleStatus.TESTED)
        self.assertGreaterEqual(zones[0].evidence.mitigation_count, 1)

    def test_broken_zone_requires_close_beyond_band(self) -> None:
        bars = _flat_bars(20, price=1.10)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        upper = 1.1050 + 0.0005
        # Wick above, close still inside/at — not broken
        bars[11] = _bar(11, high=upper + 0.0010, low=1.1040, close=upper)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=11, swings=[high]
        )
        self.assertNotEqual(zones[0].evidence.status, ZoneLifecycleStatus.BROKEN)
        # Close strictly above — broken
        bars[12] = _bar(12, high=upper + 0.0020, low=1.1040, close=upper + 0.0001)
        zones2 = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=[high]
        )
        self.assertEqual(zones2[0].evidence.status, ZoneLifecycleStatus.BROKEN)

    def test_automatic_provenance_survives_serialization(self) -> None:
        bars = _flat_bars(20)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=[high]
        )
        payload = zones[0].to_dict()
        restored = AutomaticZone.from_dict(payload)
        self.assertEqual(restored, zones[0])
        self.assertEqual(restored.zone.source, ZoneSource.AUTOMATIC)
        self.assertEqual(restored.zone.to_dict()["source"], "automatic")

    def test_manual_zones_remain_unchanged(self) -> None:
        manual = Zone(
            id=1,
            name="weekly_demand",
            low=1.14,
            high=1.145,
            timeframe="weekly",
            strength=8,
            kind=ZoneKind.DEMAND,
            source=ZoneSource.MANUAL,
        )
        provider = ManualZoneProvider.from_zone_book(
            ZoneBook(symbol="EURUSD", zones=(manual,))
        )
        self.assertEqual(provider.zones_for("EURUSD"), (manual,))
        self.assertEqual(manual.source, ZoneSource.MANUAL)

    def test_provider_can_swap_between_manual_and_automatic(self) -> None:
        bars = _flat_bars(20)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        auto_zones = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=[high]
        )
        auto_provider = AutomaticZoneProvider.from_zones(
            "EURUSD", [z.zone for z in auto_zones]
        )
        manual = Zone(
            id=99,
            name="manual",
            low=1.0,
            high=1.01,
            timeframe="daily",
            strength=5,
            kind=ZoneKind.SUPPLY,
        )
        manual_provider = ManualZoneProvider.from_zone_book(
            ZoneBook(symbol="EURUSD", zones=(manual,))
        )
        engine_auto = ZoneEngine(auto_provider)
        engine_manual = ZoneEngine(manual_provider)
        self.assertTrue(all(z.source is ZoneSource.AUTOMATIC for z in engine_auto.zones("EURUSD", htf_only=False)))
        self.assertTrue(all(z.source is ZoneSource.MANUAL for z in engine_manual.zones("EURUSD", htf_only=False)))

        composite = CompositeZoneProvider((manual_provider, auto_provider))
        sources = {z.source for z in composite.zones_for("EURUSD")}
        self.assertEqual(sources, {ZoneSource.MANUAL, ZoneSource.AUTOMATIC})

    def test_empty_and_invalid_inputs(self) -> None:
        self.assertEqual(
            self.generator.generate([], timeframe="M15"),
            (),
        )
        bars = _flat_bars(5)
        self.assertEqual(
            self.generator.generate(bars, timeframe="M15", asof_index=99),
            (),
        )
        self.assertEqual(
            self.generator.generate(bars, timeframe="M15", asof_index=4, swings=[]),
            (),
        )

    def test_strength_is_ranking_not_confidence(self) -> None:
        bars = _flat_bars(20)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        zones = self.generator.generate(
            bars, timeframe="M15", asof_index=12, swings=[high]
        )
        strength = zones[0].zone.strength
        self.assertIsInstance(strength, int)
        self.assertTrue(0 <= strength <= 10)
        # Evidence remains the explanatory record
        self.assertGreaterEqual(zones[0].evidence.contributing_swing_count, 1)


class AutomaticZoneMarketStateIntegrationTests(unittest.TestCase):
    def test_feature_repository_and_market_state_consume_automatic_zones(self) -> None:
        bars = _flat_bars(30)
        high = _swing(SwingKind.HIGH, index=5, price=1.1050, confirmation_index=7)
        generated = AutomaticZoneGenerator(cluster_config=_config()).generate(
            bars, timeframe="daily", asof_index=20, swings=[
                _swing(
                    SwingKind.HIGH,
                    index=5,
                    price=1.1050,
                    confirmation_index=7,
                    timeframe="daily",
                )
            ]
        )
        provider = AutomaticZoneProvider.from_zones(
            "EURUSD", [item.zone for item in generated]
        )
        engine = ZoneEngine(provider)
        # Price inside auto band
        mid = (generated[0].zone.low + generated[0].zone.high) / 2
        for i, bar in enumerate(bars):
            bars[i] = _bar(
                i,
                high=mid + 0.0002,
                low=mid - 0.0002,
                close=mid,
            )
        context = FeatureRepository(zone_engine=engine).materialize(
            "EURUSD",
            {"M15": bars},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE, PACK_ZONES),
            asof=bars[-1].timestamp,
        )
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.zones.status, SectionStatus.AVAILABLE)
        self.assertTrue(state.zones.inside_zone)
        self.assertGreaterEqual(len(state.zones.active_zones), 1)
        self.assertEqual(state.zones.active_zones[0]["source"], "automatic")


class AutomaticZoneSwingPipelineE2ETests(unittest.TestCase):
    def test_dukascopy_style_bars_to_swings_to_automatic_zones(self) -> None:
        # Fixture bars shaped so fractal L=R=2 yields known swings (no network).
        highs = [10, 11, 15, 12, 11, 10, 14, 13, 12, 16, 15]
        lows = [9, 8, 7, 8, 9, 6, 7, 8, 9, 10, 9]
        bars = [
            _bar(i, high=float(h), low=float(l), close=(h + l) / 2)
            for i, (h, l) in enumerate(zip(highs, lows, strict=True))
        ]
        # Use absolute clustering scaled to these price units
        config = SwingClusterZoneConfig(
            atr_period=10_000,
            absolute_price_tolerance=0.5,
            single_swing_half_width_absolute=0.25,
        )
        generator = AutomaticZoneGenerator(
            swing_config=SwingDetectionConfig(2, 2, 2),
            cluster_config=config,
        )
        zones = generator.generate(bars, timeframe="M15", asof_index=len(bars) - 1)
        self.assertGreaterEqual(len(zones), 1)
        self.assertTrue(all(z.zone.source is ZoneSource.AUTOMATIC for z in zones))
        kinds = {z.zone.kind for z in zones}
        self.assertTrue(kinds <= {ZoneKind.SUPPLY, ZoneKind.DEMAND})

        # Confirm swings themselves match golden vector
        swings = SwingGenerator(SwingDetectionConfig(2, 2, 2)).generate(
            {"M15": bars},
            __import__("core.market", fromlist=["require_instrument"]).require_instrument(
                "EURUSD"
            ),
            entry_timeframe="M15",
            asof=bars[-1].timestamp,
        ).by_timeframe["M15"]
        self.assertEqual(swings.swing_highs, (15.0, 14.0))
        self.assertEqual(swings.swing_lows, (7.0, 6.0))

        provider = AutomaticZoneProvider.from_zones(
            "EURUSD", [z.zone for z in zones]
        )
        engine = ZoneEngine(provider)
        self.assertGreater(len(engine.zones("EURUSD", htf_only=False)), 0)


if __name__ == "__main__":
    unittest.main()
