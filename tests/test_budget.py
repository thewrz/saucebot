import json
from datetime import date
from pathlib import Path

from saucebot.budget import DailyBudget


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
