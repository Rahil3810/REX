"""Tests for session manager."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from core.session_manager import SessionManager, TradingSession
from backtests.results import SignalOutcome

IST = ZoneInfo("Asia/Kolkata")


class SessionManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = SessionManager()

    def test_london_session_ist(self) -> None:
        # 15:00 IST = 09:30 UTC → London session active
        ist_time = datetime(2026, 6, 20, 15, 0, 0, tzinfo=IST)
        info = self.manager.get_current_session(ist_time)

        self.assertEqual(info.session, TradingSession.LONDON)
        self.assertIn(TradingSession.LONDON, info.active_sessions)

    def test_london_new_york_overlap_high_liquidity(self) -> None:
        # 19:30 IST = 14:00 UTC → London + New York overlap
        ist_time = datetime(2026, 6, 20, 19, 30, 0, tzinfo=IST)
        info = self.manager.get_current_session(ist_time)

        self.assertTrue(info.overlap)
        self.assertTrue(info.high_liquidity)
        self.assertIn(TradingSession.LONDON, info.active_sessions)
        self.assertIn(TradingSession.NEW_YORK, info.active_sessions)

    def test_session_info_to_dict(self) -> None:
        ist_time = datetime(2026, 6, 20, 19, 30, 0, tzinfo=IST)
        info = self.manager.get_current_session(ist_time)
        payload = info.to_dict()

        self.assertIn("session", payload)
        self.assertIn("overlap", payload)
        self.assertIn("high_liquidity", payload)
        self.assertIn("ist_time", payload)
        self.assertIsInstance(payload["overlap"], bool)
        self.assertIsInstance(payload["high_liquidity"], bool)

    def test_ist_time_reporting(self) -> None:
        ist_time = datetime(2026, 6, 20, 19, 30, 0, tzinfo=IST)
        info = self.manager.get_current_session(ist_time)

        self.assertEqual(info.ist_time.tzinfo, IST)

    def test_session_research_reporting(self) -> None:
        london = datetime(2026, 6, 20, 15, 0, 0, tzinfo=IST)
        overlap = datetime(2026, 6, 20, 19, 30, 0, tzinfo=IST)
        records = [
            SignalOutcome("EURUSD", london, "test", 1, 1.1, 2.0),
            SignalOutcome("EURUSD", overlap, "test", 1, 1.1, -1.0),
            SignalOutcome("EURUSD", overlap, "test", 1, 1.1, 1.0),
        ]

        counts = self.manager.signals_per_session(records)
        rates = self.manager.win_rate_per_session(records)

        self.assertEqual(counts["LONDON"], 1)
        self.assertEqual(counts["LONDON_NEW_YORK_OVERLAP"], 2)
        self.assertEqual(rates["LONDON"], 100.0)
        self.assertEqual(rates["LONDON_NEW_YORK_OVERLAP"], 50.0)
        self.assertEqual(self.manager.best_session(records), "LONDON")
        self.assertEqual(
            self.manager.worst_session(records),
            "LONDON_NEW_YORK_OVERLAP",
        )


if __name__ == "__main__":
    unittest.main()
