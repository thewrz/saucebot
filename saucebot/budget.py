"""A daily search cap the bot enforces itself.

SerpApi reports no remaining balance on a search response, so the bot counts its
own spend and persists the tally, keeping a container restart from resetting it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _utc_today() -> date:
    return datetime.now(UTC).date()


class DailyBudget:
    """Grants at most ``max_per_day`` searches per UTC day, persisted to disk."""

    def __init__(
        self,
        path: Path,
        max_per_day: int,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._path = Path(path)
        self._max_per_day = max_per_day
        self._today = today
        self._lock = asyncio.Lock()
        self._exhaustion_logged_day: date | None = None
        self._day, self._count = self._load()

    @property
    def remaining(self) -> int:
        if self._day != self._today():
            return self._max_per_day
        return max(0, self._max_per_day - self._count)

    async def acquire(self) -> bool:
        """Take one search; False means exhausted or persistence failed."""
        async with self._lock:
            today = self._today()
            day, count = self._day, self._count
            if day != today:
                day, count = today, 0
            if count >= self._max_per_day:
                if self._exhaustion_logged_day != today:
                    log.info("daily search budget exhausted for %s", self._path)
                    self._exhaustion_logged_day = today
                return False
            previous = self._day, self._count
            self._day, self._count = day, count + 1
            if not self._save():
                self._day, self._count = previous
                return False
            return True

    def _load(self) -> tuple[date, int]:
        try:
            saved = json.loads(self._path.read_text())
            if not isinstance(saved, dict):
                raise TypeError("budget state must be an object")
            count = saved["count"]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError("budget count must be a non-negative integer")
            return date.fromisoformat(saved["date"]), count
        except FileNotFoundError:
            return self._today(), 0
        except (ValueError, KeyError, TypeError, OSError):
            log.warning("budget file %s is unreadable; starting today's count at zero", self._path)
            return self._today(), 0

    def _save(self) -> bool:
        temporary: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"date": self._day.isoformat(), "count": self._count}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
            temporary = None
            return True
        except OSError:
            log.exception("could not persist the search budget to %s", self._path)
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    log.exception("could not clean up temporary budget file %s", temporary)
