"""Forex session detection with IST reporting."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from core.logger import setup_logger

logger = setup_logger("session_manager")

IST = ZoneInfo("Asia/Kolkata")


class TradingSession(StrEnum):
    """Major forex trading sessions."""

    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OFF_HOURS = "OFF_HOURS"


class SessionBucket(StrEnum):
    """Mutually exclusive buckets used by strategy research reports."""

    SYDNEY = "SYDNEY"
    TOKYO = "TOKYO"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    LONDON_NEW_YORK_OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    OFF_HOURS = "OFF_HOURS"


class SessionRecord(Protocol):
    """Minimum record shape accepted by session reporting functions."""

    timestamp: datetime
    outcome: float | None


# Session windows defined in UTC (standard forex session boundaries).
_SESSION_WINDOWS: dict[TradingSession, tuple[time, time]] = {
    TradingSession.SYDNEY: (time(22, 0), time(7, 0)),
    TradingSession.TOKYO: (time(0, 0), time(9, 0)),
    TradingSession.LONDON: (time(8, 0), time(17, 0)),
    TradingSession.NEW_YORK: (time(13, 0), time(22, 0)),
}

# Pairs of sessions that overlap (high-liquidity windows).
_OVERLAP_PAIRS: frozenset[frozenset[TradingSession]] = frozenset(
    {
        frozenset({TradingSession.SYDNEY, TradingSession.TOKYO}),
        frozenset({TradingSession.TOKYO, TradingSession.LONDON}),
        frozenset({TradingSession.LONDON, TradingSession.NEW_YORK}),
    }
)

# London–New York overlap is the primary high-liquidity window.
_HIGH_LIQUIDITY_SESSIONS: frozenset[TradingSession] = frozenset(
    {TradingSession.LONDON, TradingSession.NEW_YORK}
)


@dataclass(frozen=True)
class SessionInfo:
    """Current session state reported in IST."""

    session: TradingSession
    overlap: bool
    high_liquidity: bool
    ist_time: datetime
    active_sessions: tuple[TradingSession, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "session": self.session.value,
            "overlap": self.overlap,
            "high_liquidity": self.high_liquidity,
            "ist_time": self.ist_time.isoformat(),
            "active_sessions": [session.value for session in self.active_sessions],
        }


class SessionManager:
    """
    Detect active forex sessions and liquidity conditions.

    All reporting timestamps use IST (Asia/Kolkata) internally.
    """

    def get_current_session(self, at_time: datetime | None = None) -> SessionInfo:
        """
        Return the dominant session and liquidity context for a given moment.

        Args:
            at_time: Optional datetime (any timezone). Defaults to now.
        """
        if at_time is None:
            ist_now = datetime.now(IST)
        else:
            ist_now = at_time.astimezone(IST)

        utc_now = ist_now.astimezone(timezone.utc)
        active = self._active_sessions(utc_now)

        overlap = len(active) > 1
        high_liquidity = _HIGH_LIQUIDITY_SESSIONS.issubset(active)

        dominant = self._dominant_session(active)

        info = SessionInfo(
            session=dominant,
            overlap=overlap,
            high_liquidity=high_liquidity,
            ist_time=ist_now,
            active_sessions=tuple(active),
        )
        logger.debug("Session info (IST): %s", info.to_dict())
        return info

    def _active_sessions(self, utc_now: datetime) -> list[TradingSession]:
        active: list[TradingSession] = []
        for session, (start, end) in _SESSION_WINDOWS.items():
            if self._is_within_window(utc_now, start, end):
                active.append(session)
        return active

    def _is_within_window(self, utc_now: datetime, start: time, end: time) -> bool:
        """Check if a UTC datetime falls within a session window (may cross midnight)."""
        current = utc_now.time()
        if start <= end:
            return start <= current < end
        return current >= start or current < end

    def _dominant_session(self, active: list[TradingSession]) -> TradingSession:
        if not active:
            return TradingSession.OFF_HOURS

        priority = [
            TradingSession.LONDON,
            TradingSession.NEW_YORK,
            TradingSession.TOKYO,
            TradingSession.SYDNEY,
        ]
        for session in priority:
            if session in active:
                return session
        return active[0]

    def sessions_overlap(
        self,
        session_a: TradingSession,
        session_b: TradingSession,
        at_time: datetime | None = None,
    ) -> bool:
        """Return True when two named sessions are simultaneously active."""
        info = self.get_current_session(at_time)
        return session_a in info.active_sessions and session_b in info.active_sessions

    def classify_for_research(self, at_time: datetime) -> SessionBucket:
        """Return one mutually exclusive session bucket for reporting."""
        info = self.get_current_session(at_time)
        active = set(info.active_sessions)
        if {
            TradingSession.LONDON,
            TradingSession.NEW_YORK,
        }.issubset(active):
            return SessionBucket.LONDON_NEW_YORK_OVERLAP
        if info.session == TradingSession.OFF_HOURS:
            return SessionBucket.OFF_HOURS
        return SessionBucket(info.session.value)

    def signals_per_session(
        self, records: Iterable[SessionRecord]
    ) -> dict[str, int]:
        """Count generated signals by research session bucket."""
        counts = {bucket.value: 0 for bucket in SessionBucket}
        for record in records:
            bucket = self.classify_for_research(record.timestamp)
            counts[bucket.value] += 1
        return counts

    def win_rate_per_session(
        self, records: Iterable[SessionRecord]
    ) -> dict[str, float]:
        """Calculate decided-outcome win rates by session."""
        wins = {bucket.value: 0 for bucket in SessionBucket}
        decided = {bucket.value: 0 for bucket in SessionBucket}
        for record in records:
            if record.outcome is None or record.outcome == 0:
                continue
            bucket = self.classify_for_research(record.timestamp).value
            decided[bucket] += 1
            if record.outcome > 0:
                wins[bucket] += 1
        return {
            bucket.value: (
                wins[bucket.value] / decided[bucket.value] * 100.0
                if decided[bucket.value]
                else 0.0
            )
            for bucket in SessionBucket
        }

    def best_session(self, records: Iterable[SessionRecord]) -> str | None:
        """Return the session with the highest decided-outcome win rate."""
        materialized = tuple(records)
        rates = self.win_rate_per_session(materialized)
        active = sorted(self._sessions_with_decided_outcomes(materialized))
        return max(active, key=lambda name: rates[name], default=None)

    def worst_session(self, records: Iterable[SessionRecord]) -> str | None:
        """Return the session with the lowest decided-outcome win rate."""
        materialized = tuple(records)
        rates = self.win_rate_per_session(materialized)
        active = sorted(self._sessions_with_decided_outcomes(materialized))
        return min(active, key=lambda name: rates[name], default=None)

    def _sessions_with_decided_outcomes(
        self, records: Iterable[SessionRecord]
    ) -> set[str]:
        return {
            self.classify_for_research(record.timestamp).value
            for record in records
            if record.outcome is not None and record.outcome != 0
        }
