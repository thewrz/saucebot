import json
import logging
from datetime import date
from datetime import datetime as real_datetime
from pathlib import Path

import saucebot.budget as budget_module
from saucebot.budget import DailyBudget


def temporary_budget_files(path: Path) -> list[Path]:
    return list(path.glob(".budget.json.*.tmp"))


def budget(tmp_path: Path, max_per_day: int = 3, day: str = "2026-09-12") -> DailyBudget:
    current = {"value": date.fromisoformat(day)}
    instance = DailyBudget(
        path=tmp_path / "budget.json", max_per_day=max_per_day, today=lambda: current["value"]
    )
    instance.set_day = lambda iso: current.__setitem__("value", date.fromisoformat(iso))  # type: ignore[attr-defined]
    return instance


async def test_grants_up_to_the_cap_then_refuses(tmp_path: Path) -> None:
    limit = budget(tmp_path, max_per_day=3)
    assert [await limit.acquire() for _ in range(4)] == [True, True, True, False]


async def test_remaining_counts_down(tmp_path: Path) -> None:
    limit = budget(tmp_path, max_per_day=2)
    assert limit.remaining == 2
    await limit.acquire()
    assert limit.remaining == 1
    await limit.acquire()
    assert limit.remaining == 0


async def test_rolls_over_on_a_new_day(tmp_path: Path) -> None:
    limit = budget(tmp_path, max_per_day=1)
    assert await limit.acquire() is True
    assert await limit.acquire() is False
    limit.set_day("2026-09-13")
    assert await limit.acquire() is True


async def test_state_survives_a_restart(tmp_path: Path) -> None:
    first = budget(tmp_path, max_per_day=2)
    await first.acquire()
    second = budget(tmp_path, max_per_day=2)
    assert second.remaining == 1
    assert await second.acquire() is True
    assert await second.acquire() is False


async def test_persisted_file_is_readable_json(tmp_path: Path) -> None:
    limit = budget(tmp_path)
    await limit.acquire()
    saved = json.loads((tmp_path / "budget.json").read_text())
    assert saved == {"date": "2026-09-12", "count": 1}


async def test_a_corrupt_state_file_resets_instead_of_crashing(tmp_path: Path) -> None:
    (tmp_path / "budget.json").write_text("{not json")
    limit = budget(tmp_path, max_per_day=1)
    assert await limit.acquire() is True


async def test_creates_a_missing_parent_directory(tmp_path: Path) -> None:
    limit = DailyBudget(path=tmp_path / "data" / "budget.json", max_per_day=1)
    assert await limit.acquire() is True
    assert (tmp_path / "data" / "budget.json").exists()


async def test_failed_persistence_keeps_last_valid_state_and_does_not_grant(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    limit = budget(tmp_path, max_per_day=2)
    assert await limit.acquire() is True
    original = (tmp_path / "budget.json").read_text()

    def fail_replace(source, destination) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(budget_module.os, "replace", fail_replace)
    caplog.set_level(logging.ERROR, logger="saucebot.budget")
    assert await limit.acquire() is False
    assert (tmp_path / "budget.json").read_text() == original
    assert json.loads(original) == {"date": "2026-09-12", "count": 1}
    assert limit.remaining == 1
    assert not temporary_budget_files(tmp_path)
    assert any("could not persist the search budget" in record.message for record in caplog.records)

    monkeypatch.undo()
    restarted = budget(tmp_path, max_per_day=2)
    assert restarted.remaining == 1
    assert await restarted.acquire() is True
    assert await restarted.acquire() is False


async def test_default_today_uses_utc_date(tmp_path: Path, monkeypatch) -> None:
    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            assert tz is budget_module.UTC
            return real_datetime(2026, 9, 13, 0, 30, tzinfo=tz)

    monkeypatch.setattr(budget_module, "datetime", FixedDateTime)
    limit = DailyBudget(path=tmp_path / "budget.json", max_per_day=1)
    assert await limit.acquire() is True
    saved = json.loads((tmp_path / "budget.json").read_text())
    assert saved["date"] == "2026-09-13"


async def test_logs_exhaustion_once_per_day(tmp_path: Path, caplog) -> None:
    limit = budget(tmp_path, max_per_day=1)
    caplog.set_level(logging.INFO, logger="saucebot.budget")
    assert await limit.acquire() is True
    assert await limit.acquire() is False
    assert await limit.acquire() is False
    exhaustion = [
        record for record in caplog.records if "daily search budget exhausted" in record.message
    ]
    assert len(exhaustion) == 1

    limit.set_day("2026-09-13")
    assert await limit.acquire() is True
    assert await limit.acquire() is False
    exhaustion = [
        record for record in caplog.records if "daily search budget exhausted" in record.message
    ]
    assert len(exhaustion) == 2


async def test_negative_persisted_count_is_treated_as_corrupt(tmp_path: Path) -> None:
    (tmp_path / "budget.json").write_text('{"date": "2026-09-12", "count": -1}')
    limit = budget(tmp_path, max_per_day=1)
    assert limit.remaining == 1
    assert await limit.acquire() is True
