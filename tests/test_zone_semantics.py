"""P1-7: canonical zone semantics, provenance, and identity regression tests."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.chart_analyzer import ChartAnalyzer
from core.features import (
    FeatureRepository,
    PACK_PRICE,
    PACK_ZONES,
)
from core.market_state import MarketStateBuilder, SectionStatus
from core.zone_loader import load_zones
from core.zones import (
    ManualZoneProvider,
    ZoneEngine,
    ZoneKind,
    ZoneSource,
    select_preferred_inside_zone,
)
from models.bar import Bar
from models.zone import Zone, ZoneBook


def _manual_zone(**overrides: object) -> Zone:
    payload: dict[str, object] = {
        "id": 1,
        "name": "weekly_demand",
        "low": 1.1400,
        "high": 1.1450,
        "timeframe": "weekly",
        "strength": 8,
        "kind": ZoneKind.DEMAND,
        "source": ZoneSource.MANUAL,
    }
    payload.update(overrides)
    return Zone(**payload)  # type: ignore[arg-type]


class CanonicalZoneContractTests(unittest.TestCase):
    def test_canonical_fields_have_stable_meanings(self) -> None:
        zone = _manual_zone()
        self.assertEqual(zone.id, 1)
        self.assertEqual(zone.low, 1.1400)
        self.assertEqual(zone.high, 1.1450)
        self.assertEqual(zone.timeframe, "weekly")
        self.assertEqual(zone.strength, 8)
        self.assertEqual(zone.source, ZoneSource.MANUAL)
        self.assertEqual(zone.kind, ZoneKind.DEMAND)
        # strength is a 0–10 manual rating, not a probability
        self.assertIsInstance(zone.strength, int)
        self.assertTrue(0 <= zone.strength <= 10)
        self.assertNotIsInstance(zone.strength, float)

    def test_manual_provenance_survives_construction(self) -> None:
        zone = _manual_zone()
        self.assertEqual(zone.source, ZoneSource.MANUAL)
        self.assertEqual(zone.source.value, "manual")

    def test_no_algorithmic_zone_producer_exists_in_repository(self) -> None:
        # Providers available: manual + research automatic snapshot + composite.
        from core.zones import providers as providers_mod

        names = [name for name in dir(providers_mod) if name.endswith("Provider")]
        self.assertEqual(
            sorted(names),
            [
                "AutomaticZoneProvider",
                "CompositeZoneProvider",
                "ManualZoneProvider",
                "ZoneProvider",
            ],
        )

    def test_identity_deterministic_across_repeated_construction(self) -> None:
        a = _manual_zone()
        b = _manual_zone()
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.identity_key("EURUSD"), b.identity_key("EURUSD"))
        self.assertEqual(a.identity_key("EURUSD"), "EURUSD:1")
        self.assertEqual(a, b)

    def test_bounds_and_timeframe_preserved(self) -> None:
        zone = _manual_zone(low=1.2, high=1.21, timeframe="daily")
        self.assertEqual(zone.low, 1.2)
        self.assertEqual(zone.high, 1.21)
        self.assertEqual(zone.timeframe, "daily")
        self.assertTrue(zone.contains_price(1.205))
        self.assertFalse(zone.contains_price(1.199))

    def test_strength_is_zone_specific_manual_rating_not_confidence(self) -> None:
        weak = _manual_zone(id=1, strength=2)
        strong = _manual_zone(id=2, strength=9)
        # Ranking uses strength as preference weight, not as probability
        preferred = select_preferred_inside_zone((weak, strong), 1.1425)
        self.assertIs(preferred, strong)
        self.assertEqual(preferred.strength, 9)
        # Explicit: values are discrete ratings, not [0,1] confidence
        self.assertGreater(strong.strength, 1)


class ZoneSerializationProvenanceTests(unittest.TestCase):
    def test_provenance_survives_to_dict_from_dict(self) -> None:
        zone = _manual_zone()
        payload = zone.to_dict()
        self.assertEqual(payload["source"], "manual")
        restored = Zone.from_dict(payload)
        self.assertEqual(restored, zone)
        self.assertEqual(restored.source, ZoneSource.MANUAL)

    def test_legacy_payload_without_source_defaults_to_manual(self) -> None:
        payload = {
            "id": 3,
            "name": "legacy",
            "low": 1.0,
            "high": 1.1,
            "timeframe": "H1",
            "strength": 5,
            "kind": None,
        }
        restored = Zone.from_dict(payload)
        self.assertEqual(restored.source, ZoneSource.MANUAL)

    def test_config_loader_tags_manual_source(self) -> None:
        payload = """
        {
          "EURUSD": {
            "zones": [
              {
                "id": 1,
                "name": "weekly_supply",
                "low": 1.2,
                "high": 1.21,
                "timeframe": "weekly",
                "strength": 9,
                "kind": "supply"
              }
            ]
          }
        }
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "zones.json"
            path.write_text(payload, encoding="utf-8")
            books = load_zones(path)
            zone = books["EURUSD"].zones[0]
            self.assertEqual(zone.source, ZoneSource.MANUAL)
            self.assertEqual(zone.to_dict()["source"], "manual")


class ZoneMarketStatePipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.book = ZoneBook(
            symbol="EURUSD",
            zones=(
                _manual_zone(
                    id=4,
                    name="daily_supply",
                    low=1.1100,
                    high=1.1120,
                    timeframe="daily",
                    strength=7,
                    kind=ZoneKind.SUPPLY,
                ),
            ),
        )
        self.engine = ZoneEngine(ManualZoneProvider.from_zone_book(self.book))
        self.repo = FeatureRepository(zone_engine=self.engine)
        timestamp = datetime(2026, 6, 20, tzinfo=timezone.utc)
        # Price inside daily_supply
        self.bars = [
            Bar(
                symbol="EURUSD",
                timestamp=timestamp + timedelta(minutes=15 * i),
                open=1.1110,
                high=1.1115,
                low=1.1105,
                close=1.1110,
                volume=100.0,
            )
            for i in range(5)
        ]

    def test_market_state_preserves_provenance_and_bounds(self) -> None:
        context = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE, PACK_ZONES),
            asof=self.bars[-1].timestamp,
        )
        state = MarketStateBuilder().build(context)
        self.assertEqual(state.zones.status, SectionStatus.AVAILABLE)
        self.assertTrue(state.zones.inside_zone)
        self.assertGreaterEqual(len(state.zones.active_zones), 1)
        active = state.zones.active_zones[0]
        self.assertEqual(active["source"], "manual")
        self.assertEqual(active["low"], 1.1100)
        self.assertEqual(active["high"], 1.1120)
        self.assertEqual(active["timeframe"], "daily")
        self.assertEqual(active["strength"], 7)
        assert state.zones.nearest is not None
        self.assertEqual(state.zones.nearest.source, "manual")
        # Round-trip active zone dict → Zone
        restored = Zone.from_dict(active)
        self.assertEqual(restored.source, ZoneSource.MANUAL)
        self.assertEqual(restored.identity_key("EURUSD"), "EURUSD:4")

    def test_asof_is_not_confused_with_zone_origin(self) -> None:
        # Manual zones have no origin/detection timestamp; asof is MarketState metadata only.
        context = self.repo.materialize(
            "EURUSD",
            {"M15": self.bars},
            entry_timeframe="M15",
            pack_ids=(PACK_PRICE, PACK_ZONES),
            asof=self.bars[-1].timestamp,
        )
        state = MarketStateBuilder().build(context)
        active = state.zones.active_zones[0]
        self.assertNotIn("asof", active)
        self.assertNotIn("origin_time", active)
        self.assertNotIn("confirmation_time", active)
        self.assertNotIn("detected_at", active)
        # asof lives on metadata, not on the zone annotation
        self.assertEqual(state.metadata.asof, self.bars[-1].timestamp)

    def test_repeated_materialization_is_deterministic(self) -> None:
        def snapshot() -> tuple[object, ...]:
            context = self.repo.materialize(
                "EURUSD",
                {"M15": self.bars},
                entry_timeframe="M15",
                pack_ids=(PACK_PRICE, PACK_ZONES),
                asof=self.bars[-1].timestamp,
            )
            state = MarketStateBuilder().build(context)
            return (
                state.zones.active_zones,
                state.zones.nearest.to_dict() if state.zones.nearest else None,
                state.zones.inside_zone,
            )

        self.assertEqual(snapshot(), snapshot())


class UnifiedActiveZoneSelectionTests(unittest.TestCase):
    def test_chart_analyzer_and_engine_agree_and_keep_manual_source(self) -> None:
        book = ZoneBook(
            symbol="EURUSD",
            zones=(
                Zone(1, "weak", 1.10, 1.12, "daily", 3, ZoneKind.DEMAND),
                Zone(2, "strong", 1.10, 1.12, "daily", 9, ZoneKind.DEMAND),
            ),
        )
        engine = ZoneEngine(ManualZoneProvider.from_zone_book(book))
        nearest = engine.distance_to_nearest_zone("EURUSD", 1.11, htf_only=False)
        chart = ChartAnalyzer().analyze(book, 1.11)
        assert nearest is not None
        self.assertEqual(nearest.zone.id, 2)
        self.assertEqual(chart.active_zone_id, 2)
        self.assertEqual(nearest.zone.source, ZoneSource.MANUAL)
        self.assertEqual(chart.active_zone_source, "manual")


class GoldenZoneBehaviorPreservedTests(unittest.TestCase):
    def test_htf_filter_and_distance_behavior_unchanged(self) -> None:
        book = ZoneBook(
            symbol="EURUSD",
            zones=(
                Zone(1, "h1_noise", 1.1000, 1.1010, "H1", 5),
                Zone(
                    2,
                    "weekly_supply",
                    1.1200,
                    1.1250,
                    "weekly",
                    9,
                    ZoneKind.SUPPLY,
                ),
                Zone(
                    4,
                    "daily_supply",
                    1.1100,
                    1.1120,
                    "daily",
                    7,
                    ZoneKind.SUPPLY,
                ),
            ),
        )
        engine = ZoneEngine(ManualZoneProvider.from_zone_book(book))
        self.assertEqual({z.id for z in engine.zones("EURUSD", htf_only=True)}, {2, 4})
        nearest = engine.distance_to_nearest_zone("EURUSD", 1.1050)
        assert nearest is not None
        self.assertEqual(nearest.side, "above")
        self.assertEqual(nearest.zone.id, 4)
        self.assertAlmostEqual(nearest.distance_pips, 50.0)
        self.assertEqual(nearest.zone.source, ZoneSource.MANUAL)


if __name__ == "__main__":
    unittest.main()
