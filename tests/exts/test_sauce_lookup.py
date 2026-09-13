import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from saucebot.budget import DailyBudget
from saucebot.engines.base import EngineError, SourceHit
from saucebot.exts.sauce import lookup_source


@dataclass
class StubEngine:
    hits: list[SourceHit] | None = None
    error: Exception | None = None
    calls: int = 0

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.hits or [])


def budget(tmp_path: Path, max_per_day: int = 5) -> DailyBudget:
    return DailyBudget(path=tmp_path / "budget.json", max_per_day=max_per_day)


EXCLUDED = frozenset({"cdn.discordapp.com"})


async def test_returns_the_first_hit(tmp_path: Path) -> None:
    engine = StubEngine(hits=[SourceHit("https://a.example/x", "A", "A site")])
    result = await lookup_source(engine, budget(tmp_path), EXCLUDED, "https://cdn/x.png", b"")
    assert result.hit is not None
    assert result.hit.url == "https://a.example/x"
    assert result.status == "found"


async def test_excluded_domains_are_dropped_before_choosing(tmp_path: Path) -> None:
    engine = StubEngine(
        hits=[
            SourceHit("https://cdn.discordapp.com/attachments/1/2/a.png", "", ""),
            SourceHit("https://real.example/post", "Real", "Real"),
        ]
    )
    result = await lookup_source(engine, budget(tmp_path), EXCLUDED, "https://cdn/x.png", b"")
    assert result.hit is not None
    assert result.hit.url == "https://real.example/post"


async def test_no_hits_reports_not_found(tmp_path: Path) -> None:
    result = await lookup_source(
        StubEngine(hits=[]), budget(tmp_path), EXCLUDED, "https://cdn/x.png", b""
    )
    assert result.status == "not_found"
    assert result.hit is None


async def test_only_excluded_hits_reports_not_found(tmp_path: Path) -> None:
    engine = StubEngine(hits=[SourceHit("https://cdn.discordapp.com/a.png", "", "")])
    result = await lookup_source(engine, budget(tmp_path), EXCLUDED, "https://cdn/x.png", b"")
    assert result.status == "not_found"


async def test_exhausted_budget_skips_engine_and_logs_once_per_day(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    engine = StubEngine(hits=[SourceHit("https://a.example/x", "A", "A")])
    limit = budget(tmp_path, max_per_day=1)
    await lookup_source(engine, limit, EXCLUDED, "https://cdn/x.png", b"")
    with caplog.at_level(logging.INFO):
        results = [
            await lookup_source(engine, limit, EXCLUDED, "https://cdn/x.png", b"") for _ in range(3)
        ]
    assert [result.status for result in results] == ["over_budget"] * 3
    assert engine.calls == 1
    assert sum("daily search budget exhausted" in record.message for record in caplog.records) == 1


async def test_engine_failure_is_reported_not_raised(tmp_path: Path) -> None:
    engine = StubEngine(error=EngineError("boom"))
    result = await lookup_source(engine, budget(tmp_path), EXCLUDED, "https://cdn/x.png", b"")
    assert result.status == "error"
    assert result.hit is None
