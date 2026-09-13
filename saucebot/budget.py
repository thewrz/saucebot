"""A daily search cap the bot enforces itself.

SerpApi reports no remaining balance on a search response, so the bot counts its
own spend and persists the tally, keeping a container restart from resetting it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


class DailyBudget:
    """Grants at most ``max_per_day`` searches per UTC day, persisted to disk."""

    def __init__(
        self,
        path: Path,
        max_per_day: int,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._path = Path(path)
        self._max_per_day = max_per_day
        self._today = today
        self._lock = asyncio.Lock()
        self._day, self._count = self._load()

    @property
    def remaining(self) -> int:
        if self._day != self._today():
            return self._max_per_day
        return max(0, self._max_per_day - self._count)

    async def acquire(self) -> bool:
        """Take one search from today's budget. False means the budget is spent."""
        async with self._lock:
            today = self._today()
            if self._day != today:
                self._day, self._count = today, 0
            if self._count >= self._max_per_day:
                return False
            self._count += 1
            self._save()
            return True

    def _load(self) -> tuple[date, int]:
        try:
            saved = json.loads(self._path.read_text())
            return date.fromisoformat(saved["date"]), int(saved["count"])
        except FileNotFoundError:
            return self._today(), 0
        except (ValueError, KeyError, TypeError, OSError):
            log.warning("budget file %s is unreadable; starting today's count at zero", self._path)
            return self._today(), 0

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"date": self._day.isoformat(), "count": self._count}))
        except OSError:
            log.exception("could not persist the search budget to %s", self._path)
