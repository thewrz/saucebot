# Saucebot Watcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the saucebot fork into a passive Discord watcher that reverse-image-searches images posted by targeted users in targeted channels and calls out reposts with a configurable line and source link, staying silent when nothing is found or when the poster is the author.

**Architecture:** One installable package `saucebot/` started with `python -m saucebot`. A tiny engine interface (`SourceHit` list in, nothing Discord-aware) fronts SerpApi Google Lens; a daily budget gates every search; a pure fuzzy matcher suppresses self-posts; a template renderer produces the call-out; two discord.py 2.x extensions (`watcher`, `sauce`) glue it to Discord. Config is validated TOML, secrets are `.env`, deployment is Docker on the wrz-droplet VPS.

**Tech Stack:** Python ≥ 3.12, uv, discord.py 2.7, aiohttp, python-dotenv, pydantic 2, rapidfuzz, ruff, pytest + pytest-asyncio, GitHub Actions, Docker.

**Spec:** `docs/superpowers/specs/2026-09-12-saucebot-watcher-design.md`

## Global Constraints

- Python floor `>=3.12` (stdlib `tomllib`); `.python-version` pins `3.12`.
- Runtime deps limited to `discord.py`, `aiohttp`, `python-dotenv`, `pydantic`, `rapidfuzz`; dev deps `ruff`, `pytest`, `pytest-asyncio`. All MIT/Apache/BSD. No `saucenao-api`, no Pillow.
- Secrets only in `.env`: `DISCORD_TOKEN`, `SERPAPI_API_KEY`. Never committed. Never echoed into Discord.
- Behaviour only in `config.toml` (gitignored; `config.example.toml` tracked). `config.py` is the only module that reads TOML.
- Allowed template placeholders, exactly: `user`, `source_url`, `title`, `author`, `site`.
- Built-in excluded domains, exactly: `cdn.discordapp.com`, `media.discordapp.net`.
- Default `max_searches_per_day` = 8; default `min_seconds_between_callouts` = 60; default `self_match_threshold` = 80; default `max_attachments_per_message` = 3.
- SerpApi call: `GET https://serpapi.com/search` with `engine=google_lens`, `type=exact_matches`, `url`, `api_key`. Never request `visual_matches`. **`type` must be sent explicitly** — omitting it returns an `ai_overview` object and no match buckets at all.
- **SerpApi response facts, verified against the live API on 2026-09-12 (these drive Task 8):**
  - Success with matches: HTTP 200, top-level `exact_matches` array. Per-result fields always present: `position`, `title`, `source`, `link`, `thumbnail`, `actual_image_width`, `actual_image_height`. Sometimes present: `source_icon` (386 of 400 results), `date` (123 of 400), `price`, `extracted_price`, `in_stock`.
  - **Success with no matches: HTTP 200, NO `exact_matches` key at all, plus a top-level `error` string `"Google Lens hasn't returned any results for this query."` and `search_information.images_results_state == "Fully empty"`.** This is the ordinary "no source found" outcome and MUST map to an empty list, never to an exception. Getting this wrong makes the bot raise on every unsourced image.
  - Invalid key: HTTP 401, body `{"error": "Invalid API key. Your API key should be here: https://serpapi.com/manage-api-key"}`.
  - Malformed request: HTTP 400, body `{"error": "Missing query `url` parameter."}`.
  - Free plan: 250 searches/month, rate limit 250/hour. Only successful searches count.
  - **A Lens search takes 5-12 seconds.** The client uses a 60-second total timeout and the watcher must never block the event loop waiting on it.
- No error text from SerpApi or Discord is ever sent to chat.
- Every PR < 500 LOC of real change, opened as a **draft**, issue-first, attribution banner on issue and PR bodies.
- **Attribution:** every commit ends with a `Co-Authored-By` trailer naming the agent that actually wrote it. Substitute your own identity for `<YOUR-AGENT> <noreply@<provider>>` throughout this plan: a Claude Code session writes `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` (use your real model name), a Codex session writes `Co-Authored-By: Codex <noreply@openai.com>`. Never credit an agent that did not do the work.
- **Staging:** never `git add -A` or `git add .` in this repo. The untracked `.agent/` directory holds session state that must not be committed. Stage explicit paths.
- Never commit to `main`. Never run `@coderabbitai` triggers.
- GitHub API: REST (`gh api`) for issues/PR data; GraphQL only for Projects.
- Lint every shell script with `shellcheck` before committing.

---

## File structure (end state)

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock`, `.python-version` | Package metadata, pinned deps, tool config |
| `saucebot/__init__.py` | Package marker, `__version__` |
| `saucebot/__main__.py` | Entry point: logging, `.env`, config, session, engine, budget, bot |
| `saucebot/bot.py` | `SauceBot(commands.Bot)`; intents; loads extensions in `setup_hook` |
| `saucebot/errors.py` | `ConfigError` |
| `saucebot/secrets.py` | `Secrets`, `load_secrets(env)` |
| `saucebot/config.py` | pydantic models, `load_config(path)`, `parse_config(dict)` |
| `saucebot/budget.py` | `DailyBudget` persisted to `data/budget.json` |
| `saucebot/matching.py` | `normalize`, `handle_from_url`, `is_self_post`, `first_non_self_hit` |
| `saucebot/responses.py` | `author_label`, `render` |
| `saucebot/engines/__init__.py` | Package marker |
| `saucebot/engines/base.py` | `SourceHit`, `ImageSearchEngine`, `NullEngine`, error family, domain filter |
| `saucebot/engines/serpapi_lens.py` | `SerpApiLensEngine`, `parse_exact_matches`, `raise_for_status` |
| `saucebot/exts/__init__.py` | Package marker |
| `saucebot/exts/sauce.py` | `?sauce` command cog |
| `saucebot/exts/watcher.py` | Passive `on_message` cog |
| `scripts/verify.sh` | Canonical local verification (lint, format, tests, audit); CI calls it |
| `scripts/capture_serpapi_fixture.py` | Captures a real SerpApi response into `tests/fixtures/` |
| `tests/…` | Boundary tests per module; `tests/fixtures/` holds captured JSON and `IMG_5524.jpg` |
| `.github/workflows/ci.yml` | Runs `scripts/verify.sh` on PRs and `main` |
| `Dockerfile`, `compose.yml`, `.dockerignore` | Deployment |
| `config.example.toml`, `.env.example`, `README.md`, `LICENSE` | Operator docs |

Deleted from upstream: `cogs/`, `saucebot/logger.py`, `build_linux.sh`, `build_macos.sh`, `build_windows.sh`, `.vscode/`, `res/icon.ico`, `requirements.txt`.

One deviation from the spec: `BudgetExhausted` is not defined. `DailyBudget.acquire()` returns `bool`, and both callers branch on it; an exception would add nothing.

---

## PR ritual (used by every PR below)

Run these exact commands with the values each PR section supplies. `OWNER_REPO=thewrz/saucebot`.

**R1. Create the issue (once per PR, before code).** Write the body to a temp file, then:

```bash
cat > /tmp/issue-body.md <<'MD'
This was written agentically; verify its assertions:

## Why
<one paragraph from the PR section>

## What
<bullets from the PR section>

Spec: docs/superpowers/specs/2026-09-12-saucebot-watcher-design.md

🤖 Co-authored by <YOUR-AGENT>.
MD
gh api repos/thewrz/saucebot/issues -f title="<PR title>" -F body=@/tmp/issue-body.md \
  -f 'labels[]=<type label>' -f 'labels[]=<area label>' -f 'labels[]=priority:p2' --jq .number
```

Record the returned issue number as `ISSUE`.

**R2. Branch.** Stacked on the previous PR's branch so work never waits on a merge:

```bash
git fetch origin
git checkout -b <branch> <previous-branch>     # first PR: git checkout -b <branch> docs/spec
```

**R3. Board move (no-op if there is no board):** `gh-project-move $ISSUE "In progress"`.

**R4. Commit format:** `type(scope): description`, body explains intent, trailer `Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>`. Sign-off style: `git commit -m "<title>" -m "<body>" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"`.

**R5. Verify before push:** `scripts/verify.sh` must exit 0. Report its output; skipped is not passed.

**R6. Open the draft PR:**

```bash
git push -u origin <branch>
cat > /tmp/pr-body.md <<'MD'
This was written agentically; verify its assertions:

## Why
<from the PR section>

## What
<from the PR section>

## Testing
- [ ] `scripts/verify.sh` passes locally
- [ ] CI green
- [ ] Manual verification: <from the PR section>

🤖 Co-authored by <YOUR-AGENT>. Closes #ISSUE.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
MD
gh pr create --draft --base <previous-branch> --title "<PR title>" --body-file /tmp/pr-body.md
gh-project-move $ISSUE "In review"
```

When the previous PR merges, GitHub retargets the stacked PR to `main` automatically.

---

## Task 0: Repository labels and the docs PR

**Files:**
- Create: none (GitHub state only)

**Interfaces:**
- Produces: labels `type:feature`, `type:chore`, `type:docs`, `area:bot`, `area:engine`, `area:config`, `area:deploy`, `priority:p2`; the `docs/spec` branch pushed with spec and this plan.

- [ ] **Step 1: Create labels via REST (idempotent — a 422 means it already exists)**

```bash
for spec in "type:feature 0e8a16" "type:chore c5def5" "type:docs 0075ca" "area:bot 1d76db" "area:engine 5319e7" "area:config fbca04" "area:deploy d93f0b" "priority:p2 e99695"; do
  set -- $spec
  gh api repos/thewrz/saucebot/labels -f name="$1" -f color="$2" >/dev/null 2>&1 && echo "created $1" || echo "exists $1"
done
```

- [ ] **Step 2: Commit the plan on `docs/spec`**

```bash
git checkout docs/spec
git add docs/superpowers/plans/2026-09-12-saucebot-watcher.md
git commit -m "docs: implementation plan for the passive watcher" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

- [ ] **Step 3: Open the docs PR (ritual R1 then R6 with `--base main`)**

Issue title: `docs: design spec and plan for the passive reverse-image watcher`. Labels `type:docs`, `area:bot`. Why: record the approved design so implementation PRs argue from one document. What: spec + plan under `docs/superpowers/`. Manual verification: "read both documents; no placeholders".

```bash
git push -u origin docs/spec
gh pr create --draft --base main --title "docs: design spec and plan for the passive reverse-image watcher" --body-file /tmp/pr-body.md
```

---

# PR 1 — `chore: repackage as installable module with uv, ruff, pytest, CI`

Branch `chore/repackage`, base `docs/spec`. Labels `type:chore`, `area:bot`.
Why: upstream is an unpackaged 2021 script on EOL discord.py 1.7.3 with CVE-stale pins and a cross-guild message read; nothing new can be built on it safely.
What: installable package, discord.py 2.x port of `?sauce` with the cross-guild fix, stub engine, secrets loader, verify script, CI, MIT license, README.
Manual verification: `uv run python -m saucebot` with a valid `.env` connects and `?sauce` on an image replies "No source found."

## Task 1: Package scaffolding and legacy removal

**Files:**
- Create: `pyproject.toml`, `.python-version`, `saucebot/__init__.py`, `saucebot/engines/__init__.py`, `saucebot/exts/__init__.py`, `tests/__init__.py`, `LICENSE`, `.env.example`
- Modify: `.gitignore`
- Delete: `cogs/sauce.py`, `saucebot/bot.py` (rewritten in Task 4), `saucebot/logger.py`, `build_linux.sh`, `build_macos.sh`, `build_windows.sh`, `.vscode/launch.json`, `res/icon.ico`, `requirements.txt`

**Interfaces:**
- Produces: importable `saucebot` package; `uv run pytest` runs (zero tests is fine here).

- [ ] **Step 1: Ritual R1–R3 for PR 1, then remove the legacy files**

```bash
git rm -r cogs saucebot/logger.py saucebot/bot.py build_linux.sh build_macos.sh build_windows.sh .vscode res requirements.txt
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "saucebot"
version = "1.0.0"
description = "Discord bot that reverse-image-searches posted images and calls out reposts"
readme = "README.md"
license = "MIT"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["saucebot"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF", "ASYNC", "S", "T20"]
ignore = ["S311"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "S105", "S106"]
"scripts/*" = ["T20"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
testpaths = ["tests"]
```

- [ ] **Step 3: Pin Python and add dependencies (uv writes the constraints and the lockfile)**

```bash
uv python pin 3.12
uv add "discord.py" aiohttp python-dotenv pydantic rapidfuzz
uv add --dev ruff pytest pytest-asyncio
```

Expected: `uv.lock` created; `pyproject.toml` dependencies filled with `>=` constraints. Check `uv tree --depth 1` shows exactly those eight packages.

- [ ] **Step 4: Package markers**

`saucebot/__init__.py`:
```python
"""Discord bot that reverse-image-searches posted images and calls out reposts."""

__version__ = "1.0.0"
```

`saucebot/engines/__init__.py`, `saucebot/exts/__init__.py`, `tests/__init__.py`: empty files.

- [ ] **Step 5: `.gitignore` additions (append)**

```
# saucebot runtime
config.toml
data/
.env
```

(`.env` and `.venv` are already listed; keep the file otherwise as-is.)

- [ ] **Step 6: `.env.example`**

```
DISCORD_TOKEN=
SERPAPI_API_KEY=
```

- [ ] **Step 7: `LICENSE`**

```
MIT License

Copyright (c) 2026 thewrz

This fork's changes are licensed under the MIT License below. The upstream
project (https://github.com/sowwic/saucebot) was published without a license
file; its original files have been rewritten or removed in this fork.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 8: Verify the package imports and the empty suite runs**

Run: `uv run python -c "import saucebot; print(saucebot.__version__)" && uv run pytest`
Expected: `1.0.0`, then pytest reports `no tests ran` with exit code 5 (acceptable only for this step).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock .python-version .gitignore .env.example LICENSE \
        saucebot/__init__.py saucebot/engines/__init__.py saucebot/exts/__init__.py tests/__init__.py
git add -u   # stages the legacy deletions only
git commit -m "chore: repackage saucebot as a uv-managed module" -m "Removes the PyInstaller scripts, Windows lock file, custom logger and 2021 pins so the bot can be rebuilt on discord.py 2.x with a lockfile and CI." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 2: Engine contract and domain filter

**Files:**
- Create: `saucebot/engines/base.py`
- Test: `tests/engines/__init__.py` (empty), `tests/engines/test_base.py`

**Interfaces:**
- Produces:
  - `SourceHit(url: str, title: str, site: str)` frozen dataclass
  - `EngineError(Exception)`, `BadKeyError(EngineError)`, `QuotaError(EngineError)`
  - `ImageSearchEngine` Protocol: `async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]`
  - `NullEngine` implementing it, always `[]`
  - `DEFAULT_EXCLUDED_DOMAINS: frozenset[str]`
  - `filter_excluded_domains(hits: list[SourceHit], excluded: frozenset[str]) -> list[SourceHit]`

- [ ] **Step 1: Write the failing tests**

`tests/engines/test_base.py`:
```python
from saucebot.engines.base import (
    DEFAULT_EXCLUDED_DOMAINS,
    NullEngine,
    SourceHit,
    filter_excluded_domains,
)


def hit(url: str) -> SourceHit:
    return SourceHit(url=url, title="t", site="s")


def test_default_exclusions_cover_discord_cdn_hosts() -> None:
    assert DEFAULT_EXCLUDED_DOMAINS == frozenset({"cdn.discordapp.com", "media.discordapp.net"})


def test_filter_drops_exact_and_subdomain_matches_only() -> None:
    hits = [
        hit("https://cdn.discordapp.com/attachments/1/2/a.png"),
        hit("https://images.media.discordapp.net/x.png"),
        hit("https://notdiscordapp.com/a.png"),
        hit("https://example.com/meme"),
    ]
    kept = filter_excluded_domains(hits, DEFAULT_EXCLUDED_DOMAINS)
    assert [h.url for h in kept] == ["https://notdiscordapp.com/a.png", "https://example.com/meme"]


def test_filter_is_case_insensitive_and_tolerates_bad_urls() -> None:
    hits = [hit("HTTPS://CDN.DISCORDAPP.COM/a"), hit("not a url")]
    assert filter_excluded_domains(hits, DEFAULT_EXCLUDED_DOMAINS) == [hit("not a url")]


async def test_null_engine_never_finds_anything() -> None:
    assert await NullEngine().search("https://x/y.png", b"bytes") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/engines/test_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.engines.base'`

- [ ] **Step 3: Implement `saucebot/engines/base.py`**

```python
"""Engine contract shared by every reverse-image backend.

Nothing in this module knows about Discord. An engine turns an image into a
list of ``SourceHit``; everything downstream consumes only that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

DEFAULT_EXCLUDED_DOMAINS: frozenset[str] = frozenset({"cdn.discordapp.com", "media.discordapp.net"})


@dataclass(frozen=True)
class SourceHit:
    """One page on which the searched image was found."""

    url: str
    title: str
    site: str


class EngineError(Exception):
    """The engine could not complete a search."""


class BadKeyError(EngineError):
    """The API rejected the configured key."""


class QuotaError(EngineError):
    """The API's own quota is exhausted."""


class ImageSearchEngine(Protocol):
    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        """Return pages where the image appears, best first. Empty means no source."""
        ...


class NullEngine:
    """Engine that never finds anything. Placeholder until a real engine is wired."""

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        return []


def hostname_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_excluded(url: str, excluded: frozenset[str]) -> bool:
    host = hostname_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in excluded)


def filter_excluded_domains(hits: list[SourceHit], excluded: frozenset[str]) -> list[SourceHit]:
    """Drop hits whose host is an excluded domain or a subdomain of one."""
    return [hit for hit in hits if not is_excluded(hit.url, excluded)]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/engines/test_base.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add saucebot/engines/base.py tests/engines
git commit -m "feat(engine): define the SourceHit engine contract and domain filter" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 3: Errors and secrets loader

**Files:**
- Create: `saucebot/errors.py`, `saucebot/secrets.py`
- Test: `tests/test_secrets.py`

**Interfaces:**
- Produces: `ConfigError(Exception)`; `Secrets(discord_token: str, serpapi_api_key: str)`; `load_secrets(env: Mapping[str, str]) -> Secrets` raising `ConfigError` naming every missing variable.

- [ ] **Step 1: Write the failing tests**

`tests/test_secrets.py`:
```python
import pytest

from saucebot.errors import ConfigError
from saucebot.secrets import Secrets, load_secrets


def test_loads_both_secrets() -> None:
    env = {"DISCORD_TOKEN": "d", "SERPAPI_API_KEY": "s", "OTHER": "x"}
    assert load_secrets(env) == Secrets(discord_token="d", serpapi_api_key="s")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "DISCORD_TOKEN, SERPAPI_API_KEY"),
        ({"DISCORD_TOKEN": "d"}, "SERPAPI_API_KEY"),
        ({"DISCORD_TOKEN": "", "SERPAPI_API_KEY": "s"}, "DISCORD_TOKEN"),
    ],
)
def test_missing_or_empty_secrets_are_named(env: dict[str, str], expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_secrets(env)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

`saucebot/errors.py`:
```python
"""Errors raised before the bot connects."""


class ConfigError(Exception):
    """Configuration or secrets are missing or invalid. The message names the key."""
```

`saucebot/secrets.py`:
```python
"""Secrets come from the process environment (loaded from .env by the entry point)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from saucebot.errors import ConfigError

REQUIRED_VARIABLES: tuple[str, ...] = ("DISCORD_TOKEN", "SERPAPI_API_KEY")


@dataclass(frozen=True)
class Secrets:
    discord_token: str
    serpapi_api_key: str


def load_secrets(env: Mapping[str, str]) -> Secrets:
    missing = [name for name in REQUIRED_VARIABLES if not env.get(name)]
    if missing:
        raise ConfigError(f"missing required environment variable(s): {', '.join(missing)}")
    return Secrets(discord_token=env["DISCORD_TOKEN"], serpapi_api_key=env["SERPAPI_API_KEY"])
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_secrets.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add saucebot/errors.py saucebot/secrets.py tests/test_secrets.py
git commit -m "feat: load Discord and SerpApi secrets from the environment, failing loud when missing" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 4: Bot class and entry point

**Files:**
- Create: `saucebot/bot.py`, `saucebot/__main__.py`
- Test: `tests/test_bot.py`

**Interfaces:**
- Consumes: `ImageSearchEngine`, `NullEngine` (Task 2); `load_secrets`, `ConfigError` (Task 3).
- Produces: `build_intents() -> discord.Intents`; `SauceBot(command_prefix: str, engine: ImageSearchEngine)` with attribute `engine` and `EXTENSIONS: tuple[str, ...]`; `main() -> int`.

- [ ] **Step 1: Write the failing tests**

`tests/test_bot.py`:
```python
from saucebot.bot import EXTENSIONS, SauceBot, build_intents
from saucebot.engines.base import NullEngine


def test_intents_are_default_plus_message_content_only() -> None:
    intents = build_intents()
    expected = build_intents().__class__.default()
    expected.message_content = True
    assert intents == expected


async def test_setup_hook_loads_every_declared_extension() -> None:
    bot = SauceBot(command_prefix="?", engine=NullEngine())
    await bot.setup_hook()
    assert set(bot.extensions) == set(EXTENSIONS)
    assert bot.get_cog("Sauce") is not None
    await bot.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_bot.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.bot'` (the file was deleted in Task 1).

- [ ] **Step 3: Implement `saucebot/bot.py`**

```python
"""The bot object: intents, shared services, and extension loading."""

from __future__ import annotations

import discord
from discord.ext import commands

from saucebot.engines.base import ImageSearchEngine

EXTENSIONS: tuple[str, ...] = ("saucebot.exts.sauce",)


def build_intents() -> discord.Intents:
    """Default intents plus the privileged message-content intent (needed for attachments)."""
    intents = discord.Intents.default()
    intents.message_content = True
    return intents


class SauceBot(commands.Bot):
    def __init__(self, *, command_prefix: str, engine: ImageSearchEngine) -> None:
        super().__init__(command_prefix=command_prefix, intents=build_intents())
        self.engine = engine

    async def setup_hook(self) -> None:
        for name in EXTENSIONS:
            await self.load_extension(name)
```

- [ ] **Step 4: Implement `saucebot/__main__.py`**

```python
"""Entry point: ``python -m saucebot``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from saucebot.bot import SauceBot
from saucebot.engines.base import NullEngine
from saucebot.errors import ConfigError
from saucebot.secrets import load_secrets

log = logging.getLogger("saucebot")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    load_dotenv()
    secrets = load_secrets(os.environ)
    bot = SauceBot(command_prefix="?", engine=NullEngine())
    async with bot:
        await bot.start(secrets.discord_token)


def main() -> int:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigError as exc:
        log.error("startup failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run the bot tests (they still fail until Task 5 provides the extension)**

Run: `uv run pytest tests/test_bot.py -v`
Expected: `test_intents…` PASS; `test_setup_hook…` FAIL with `ExtensionNotFound: saucebot.exts.sauce`. That is the red state Task 5 turns green.

- [ ] **Step 6: Commit**

```bash
git add saucebot/bot.py saucebot/__main__.py tests/test_bot.py
git commit -m "feat(bot): discord.py 2.x bot class with explicit intents and module entry point" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 5: Port the `?sauce` command with the cross-guild fix

**Files:**
- Create: `saucebot/exts/sauce.py`
- Test: `tests/exts/__init__.py` (empty), `tests/exts/test_sauce.py`

**Interfaces:**
- Consumes: `SauceBot.engine`; `EngineError`, `filter_excluded_domains`, `DEFAULT_EXCLUDED_DOMAINS` (Task 2).
- Produces: `MessageRef(guild_id, channel_id, message_id)`; `parse_message_link(text: str) -> MessageRef | None`; `first_image_attachment(message) -> discord.Attachment | None`; cog class `Sauce`; `async def setup(bot)`.

- [ ] **Step 1: Write the failing tests**

`tests/exts/test_sauce.py`:
```python
from types import SimpleNamespace

import pytest

from saucebot.exts.sauce import MessageRef, first_image_attachment, parse_message_link


@pytest.mark.parametrize(
    "link",
    [
        "https://discord.com/channels/1/2/3",
        "https://ptb.discord.com/channels/1/2/3",
        "https://canary.discord.com/channels/1/2/3/",
        "https://discordapp.com/channels/1/2/3",
        "  https://discord.com/channels/1/2/3  ",
    ],
)
def test_parses_every_discord_host_variant(link: str) -> None:
    assert parse_message_link(link) == MessageRef(guild_id=1, channel_id=2, message_id=3)


@pytest.mark.parametrize(
    "link",
    [
        "http://discord.com/channels/1/2/3",
        "https://evil.com/channels/1/2/3",
        "https://discord.com/channels/1/2",
        "https://discord.com/channels/a/b/c",
        "3",
    ],
)
def test_rejects_non_message_links(link: str) -> None:
    assert parse_message_link(link) is None


def attachment(content_type: str | None) -> SimpleNamespace:
    return SimpleNamespace(content_type=content_type, url="https://cdn/x")


def test_first_image_attachment_skips_video_and_unknown_types() -> None:
    message = SimpleNamespace(
        attachments=[attachment("video/mp4"), attachment(None), attachment("image/png")]
    )
    assert first_image_attachment(message) is message.attachments[2]


def test_first_image_attachment_returns_none_without_images() -> None:
    assert first_image_attachment(SimpleNamespace(attachments=[attachment("text/plain")])) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/exts/test_sauce.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.exts.sauce'`

- [ ] **Step 3: Implement `saucebot/exts/sauce.py`**

```python
"""The manual ``?sauce`` command: search an attached image or a linked message's image."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from saucebot.engines.base import DEFAULT_EXCLUDED_DOMAINS, EngineError, filter_excluded_domains

if TYPE_CHECKING:
    from saucebot.bot import SauceBot

log = logging.getLogger(__name__)

MESSAGE_LINK = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?$"
)


@dataclass(frozen=True)
class MessageRef:
    guild_id: int
    channel_id: int
    message_id: int


def parse_message_link(text: str) -> MessageRef | None:
    match = MESSAGE_LINK.match(text.strip())
    if match is None:
        return None
    guild_id, channel_id, message_id = (int(group) for group in match.groups())
    return MessageRef(guild_id=guild_id, channel_id=channel_id, message_id=message_id)


def first_image_attachment(message: discord.Message) -> discord.Attachment | None:
    for attachment in message.attachments:
        if (attachment.content_type or "").startswith("image/"):
            return attachment
    return None


class Sauce(commands.Cog):
    def __init__(self, bot: SauceBot) -> None:
        self.bot = bot

    @commands.command(name="sauce")
    @commands.guild_only()
    async def sauce(self, ctx: commands.Context, ref_url: str | None = None) -> None:
        target = ctx.message
        if ref_url is not None:
            ref = parse_message_link(ref_url)
            if ref is None or ctx.guild is None or ref.guild_id != ctx.guild.id:
                await ctx.reply("That isn't a message link from this server.")
                return
            fetched = await self._fetch_message(ctx.guild, ref)
            if fetched is None:
                await ctx.reply("I can't see that message.")
                return
            target = fetched
        attachment = first_image_attachment(target)
        if attachment is None:
            await ctx.reply("Attach an image or link a message that has one.")
            return
        await self._lookup(ctx, attachment)

    async def _fetch_message(self, guild: discord.Guild, ref: MessageRef) -> discord.Message | None:
        channel = guild.get_channel_or_thread(ref.channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return None
        try:
            return await channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return None

    async def _lookup(self, ctx: commands.Context, attachment: discord.Attachment) -> None:
        try:
            image_bytes = await attachment.read()
            hits = await self.bot.engine.search(attachment.url, image_bytes)
        except (EngineError, discord.HTTPException):
            log.exception("sauce lookup failed for message %s", ctx.message.id)
            await ctx.reply("Search failed. Check the logs.")
            return
        hits = filter_excluded_domains(hits, DEFAULT_EXCLUDED_DOMAINS)
        if not hits:
            await ctx.reply("No source found.")
            return
        await ctx.reply(f"Source: {hits[0].url}")


async def setup(bot: SauceBot) -> None:
    await bot.add_cog(Sauce(bot))
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -v`
Expected: all tests pass, including `tests/test_bot.py::test_setup_hook_loads_every_declared_extension`.

- [ ] **Step 5: Commit**

```bash
git add saucebot/exts/sauce.py tests/exts
git commit -m "feat(sauce): port the ?sauce command to discord.py 2.x and refuse cross-guild message links" -m "Upstream fetched any message link from any guild the bot could see, leaking images across servers. Links are now honoured only inside the invoking guild." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 6: Verify script, CI, README, and the draft PR

**Files:**
- Create: `scripts/verify.sh`, `.github/workflows/ci.yml`
- Modify: `README.md` (full rewrite)

**Interfaces:**
- Produces: `scripts/verify.sh` (exit 0 = all gates pass) used locally and by CI.

- [ ] **Step 1: `scripts/verify.sh`**

```bash
#!/usr/bin/env bash
# Canonical local verification. CI runs exactly this.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== ruff check";        uv run ruff check .
echo "== ruff format";       uv run ruff format --check .
echo "== pytest";            uv run pytest -q
echo "== uv audit";          uv audit
echo "== all gates passed"
```

Then: `chmod +x scripts/verify.sh && shellcheck scripts/verify.sh` — expected: no output.

- [ ] **Step 2: `.github/workflows/ci.yml`** (this path is protected by the repo contract; it is a deliberate, reviewed addition)

```yaml
name: ci

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - uses: astral-sh/setup-uv@bec219d24cd3e171d82865faccec33120bb574f4 # v10.1.0
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: scripts/verify.sh
```

- [ ] **Step 3: Rewrite `README.md`**

```markdown
# saucebot

Discord bot that reverse-image-searches images posted in a channel and, when it
finds where the image came from, calls the poster out with the source. Fork of
[sowwic/saucebot](https://github.com/sowwic/saucebot), rebuilt on discord.py 2.x.

## Setup

1. Create a bot at https://discord.com/developers/applications, enable the
   **Message Content Intent** under *Bot → Privileged Gateway Intents*, and invite
   it with the *Read Messages*, *Send Messages*, and *Read Message History*
   permissions.
2. Get a SerpApi key at https://serpapi.com (the free plan is 250 searches a month).
3. `cp .env.example .env` and fill in `DISCORD_TOKEN` and `SERPAPI_API_KEY`.
4. `uv sync` then `uv run python -m saucebot`.

## Commands

- `?sauce` with an image attached — search that image.
- `?sauce <message link>` — search the first image on a message in this server.

## Development

`scripts/verify.sh` runs lint, format check, tests, and a dependency audit; CI
runs the same script.

## License

MIT for this fork's changes (see `LICENSE`). Upstream carried no license.
```

- [ ] **Step 4: Run the full verification and fix anything it reports**

Run: `scripts/verify.sh`
Expected: every gate prints and the script ends with `== all gates passed`. If `ruff format --check` fails, run `uv run ruff format .` and re-run. If `uv audit` reports an advisory, upgrade the package (`uv lock --upgrade-package <name>`) rather than ignoring it.

- [ ] **Step 5: Commit and open the draft PR (ritual R5–R6)**

```bash
git add scripts/verify.sh .github/workflows/ci.yml README.md
git commit -m "ci: repo-owned verify script and SHA-pinned GitHub Actions workflow" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

Then ritual R6 with title `chore: repackage as installable module with uv, ruff, pytest, CI`, base `docs/spec`.


---

# PR 2 — `feat: TOML config with validation`

Branch `feat/config`, base `chore/repackage`. Labels `type:feature`, `area:config`.
Why: every behaviour the operator tunes (which channel, which users, what the bot says) needs one validated home; a typo in a template placeholder must fail at startup, not at 2am in a live channel.
What: pydantic models for the whole `config.toml`, a loader, a tracked `config.example.toml`, and tests for every rejection path.
Manual verification: `uv run python -c "from saucebot.config import load_config; print(load_config('config.example.toml'))"` prints a `Config`; deleting `channel_ids` from a copy makes it raise naming that key.

## Task 7: Config models, loader, and example file

**Files:**
- Create: `saucebot/config.py`, `config.example.toml`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `ConfigError` (Task 3).
- Produces:
  - `ResponseMode` str-enum with members `REPLY = "reply"`, `MENTION = "mention"`
  - `ALLOWED_PLACEHOLDERS: frozenset[str]` = `{"user", "source_url", "title", "author", "site"}`
  - `WatchConfig(channel_ids: frozenset[int], user_ids: frozenset[int], min_seconds_between_callouts: int)`
  - `SearchConfig(engine: str, max_searches_per_day: int, max_attachments_per_message: int, excluded_domains: frozenset[str])`
  - `MatchConfig(self_match_threshold: int)`
  - `ResponseConfig(mode: ResponseMode, templates: tuple[str, ...])`
  - `CommandConfig(prefix: str, allowed_channel_ids: frozenset[int])`
  - `Config(watch, search, match, response, command)`
  - `parse_config(raw: dict) -> Config` and `load_config(path: str | Path) -> Config`, both raising `ConfigError`
  - `Config.all_excluded_domains -> frozenset[str]` (configured ∪ `DEFAULT_EXCLUDED_DOMAINS`)

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import textwrap
from pathlib import Path

import pytest

from saucebot.config import Config, ResponseMode, load_config, parse_config
from saucebot.errors import ConfigError

VALID = {
    "watch": {"channel_ids": [111], "user_ids": [222], "min_seconds_between_callouts": 60},
    "search": {
        "engine": "serpapi_lens",
        "max_searches_per_day": 8,
        "max_attachments_per_message": 3,
        "excluded_domains": ["example.com"],
    },
    "match": {"self_match_threshold": 80},
    "response": {"mode": "reply", "templates": ["Stolen meme! {source_url}"]},
    "command": {"prefix": "?", "allowed_channel_ids": []},
}


def with_change(section: str, key: str, value: object) -> dict:
    raw = {name: dict(body) for name, body in VALID.items()}
    raw[section][key] = value
    return raw


def test_parses_a_valid_config() -> None:
    config = parse_config(VALID)
    assert config.watch.channel_ids == frozenset({111})
    assert config.response.mode is ResponseMode.REPLY
    assert config.response.templates == ("Stolen meme! {source_url}",)


def test_defaults_apply_to_a_minimal_config() -> None:
    config = parse_config(
        {"watch": {"channel_ids": [111]}, "response": {"templates": ["{source_url}"]}}
    )
    assert config.search.max_searches_per_day == 8
    assert config.watch.min_seconds_between_callouts == 60
    assert config.match.self_match_threshold == 80
    assert config.search.max_attachments_per_message == 3
    assert config.command.prefix == "?"
    assert config.watch.user_ids == frozenset()


def test_discord_cdn_is_always_excluded_even_when_unconfigured() -> None:
    config = parse_config(VALID)
    assert "cdn.discordapp.com" in config.all_excluded_domains
    assert "media.discordapp.net" in config.all_excluded_domains
    assert "example.com" in config.all_excluded_domains


@pytest.mark.parametrize(
    ("raw", "expected_key"),
    [
        (with_change("watch", "channel_ids", []), "channel_ids"),
        (with_change("match", "self_match_threshold", 101), "self_match_threshold"),
        (with_change("match", "self_match_threshold", -1), "self_match_threshold"),
        (with_change("response", "mode", "shout"), "mode"),
        (with_change("response", "templates", []), "templates"),
        (with_change("search", "max_searches_per_day", 0), "max_searches_per_day"),
        (with_change("search", "max_attachments_per_message", 0), "max_attachments_per_message"),
        (with_change("command", "prefix", ""), "prefix"),
        (with_change("search", "engine", "saucenao"), "engine"),
    ],
)
def test_invalid_values_raise_naming_the_key(raw: dict, expected_key: str) -> None:
    with pytest.raises(ConfigError, match=expected_key):
        parse_config(raw)


def test_unknown_placeholder_is_rejected_and_named() -> None:
    raw = with_change("response", "templates", ["{source_url} posted at {timestamp}"])
    with pytest.raises(ConfigError, match="timestamp"):
        parse_config(raw)


def test_every_allowed_placeholder_is_accepted() -> None:
    template = "{user} {source_url} {title} {author} {site}"
    config = parse_config(with_change("response", "templates", [template]))
    assert config.response.templates == (template,)


def test_mention_mode_requires_a_user_placeholder() -> None:
    raw = with_change("response", "mode", "mention")
    with pytest.raises(ConfigError, match="user"):
        parse_config(raw)


def test_mention_mode_accepts_templates_that_mention() -> None:
    raw = with_change("response", "mode", "mention")
    raw["response"]["templates"] = ["{user} stolen! {source_url}"]
    assert parse_config(raw).response.mode is ResponseMode.MENTION


def test_malformed_template_braces_are_rejected() -> None:
    with pytest.raises(ConfigError, match="template"):
        parse_config(with_change("response", "templates", ["{source_url"]))


def test_load_config_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            """
            [watch]
            channel_ids = [111]

            [response]
            templates = ["Stolen meme! {source_url}"]
            """
        )
    )
    assert isinstance(load_config(path), Config)


def test_load_config_names_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nope.toml"):
        load_config(tmp_path / "nope.toml")


def test_load_config_reports_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("[watch\n")
    with pytest.raises(ConfigError, match="bad.toml"):
        load_config(path)


def test_shipped_example_config_is_valid() -> None:
    assert isinstance(load_config(Path(__file__).parent.parent / "config.example.toml"), Config)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.config'`

- [ ] **Step 3: Implement `saucebot/config.py`**

```python
"""Operator-tunable behaviour, loaded from TOML and validated before the bot connects.

This is the only module that reads TOML. Everything else receives a ``Config``.
"""

from __future__ import annotations

import string
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from saucebot.engines.base import DEFAULT_EXCLUDED_DOMAINS
from saucebot.errors import ConfigError

ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset({"user", "source_url", "title", "author", "site"})
KNOWN_ENGINES: frozenset[str] = frozenset({"serpapi_lens"})

Snowflake = Annotated[int, Field(gt=0)]


class ResponseMode(StrEnum):
    REPLY = "reply"
    MENTION = "mention"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchConfig(_Section):
    channel_ids: frozenset[Snowflake] = Field(min_length=1)
    user_ids: frozenset[Snowflake] = frozenset()
    min_seconds_between_callouts: int = Field(default=60, ge=0)


class SearchConfig(_Section):
    engine: str = "serpapi_lens"
    max_searches_per_day: int = Field(default=8, ge=1)
    max_attachments_per_message: int = Field(default=3, ge=1)
    excluded_domains: frozenset[str] = frozenset()

    @field_validator("engine")
    @classmethod
    def engine_must_be_known(cls, value: str) -> str:
        if value not in KNOWN_ENGINES:
            raise ValueError(f"engine must be one of {sorted(KNOWN_ENGINES)}, got {value!r}")
        return value

    @field_validator("excluded_domains")
    @classmethod
    def normalise_domains(cls, value: frozenset[str]) -> frozenset[str]:
        return frozenset(
            domain.strip().lower().removeprefix("www.") for domain in value if domain.strip()
        )


class MatchConfig(_Section):
    self_match_threshold: int = Field(default=80, ge=0, le=100)


class ResponseConfig(_Section):
    mode: ResponseMode = ResponseMode.REPLY
    templates: tuple[str, ...] = Field(min_length=1)

    @field_validator("templates")
    @classmethod
    def templates_use_only_known_placeholders(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for template in value:
            try:
                fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
            except ValueError as exc:
                raise ValueError(f"template {template!r} is malformed: {exc}") from exc
            unknown = fields - ALLOWED_PLACEHOLDERS
            if unknown:
                raise ValueError(
                    f"template {template!r} uses unknown placeholder(s) "
                    f"{sorted(unknown)}; allowed: {sorted(ALLOWED_PLACEHOLDERS)}"
                )
        return value

    @model_validator(mode="after")
    def mention_mode_needs_the_user_placeholder(self) -> ResponseConfig:
        if self.mode is ResponseMode.MENTION and not all("{user}" in t for t in self.templates):
            raise ValueError(
                'mode = "mention" requires every template to contain the {user} placeholder, '
                "otherwise the poster is never notified"
            )
        return self


class CommandConfig(_Section):
    prefix: str = Field(default="?", min_length=1, max_length=5)
    allowed_channel_ids: frozenset[Snowflake] = frozenset()


class Config(_Section):
    watch: WatchConfig
    search: SearchConfig = SearchConfig()
    match: MatchConfig = MatchConfig()
    response: ResponseConfig
    command: CommandConfig = CommandConfig()

    @property
    def all_excluded_domains(self) -> frozenset[str]:
        return self.search.excluded_domains | DEFAULT_EXCLUDED_DOMAINS


def parse_config(raw: dict[str, Any]) -> Config:
    """Validate an already-parsed TOML mapping. Raises ConfigError naming the bad key."""
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from exc


def load_config(path: str | Path) -> Config:
    """Read and validate config.toml. Raises ConfigError naming the file or the bad key."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    try:
        return parse_config(raw)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _describe(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "config"
        problems.append(f"{location}: {error['msg']}")
    return "; ".join(problems)
```

Note on the `min_length=1` on `channel_ids`: pydantic reports the field name in `loc`, so the
`ConfigError` message contains `channel_ids`, which is what the test matches on.

- [ ] **Step 4: Write `config.example.toml`**

```toml
# Copy to config.toml and edit. config.toml is gitignored; this example is tracked.

[watch]
# Channels the bot watches. Required, and it refuses to start if this is empty.
channel_ids = [123456789012345678]
# Users to call out. Leave empty to watch everyone who posts in those channels.
user_ids = []
# Per-user quiet period after a call-out, in seconds.
min_seconds_between_callouts = 60

[search]
engine = "serpapi_lens"
# SerpApi's free plan is 250 searches a month; 8 a day stays inside it.
max_searches_per_day = 8
max_attachments_per_message = 3
# Never cite these domains as a source. The Discord CDN hosts are always excluded.
excluded_domains = []

[match]
# rapidfuzz score (0-100) at or above which the poster is treated as the original
# author, and the bot stays silent.
self_match_threshold = 80

[response]
# "reply" replies to the message (which pings the poster).
# "mention" posts a new message; every template must then contain {user}.
mode = "reply"
# One is picked at random. Placeholders: {user} {source_url} {title} {author} {site}
templates = [
  "Stolen meme! Source: {source_url}",
  "{user} that's from {author}: {source_url}",
]

[command]
prefix = "?"
# Where ?sauce may be used. Empty means anywhere the bot can see.
allowed_channel_ids = []
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all tests pass, including `test_shipped_example_config_is_valid`.

- [ ] **Step 6: Wire the config into the entry point**

Modify `saucebot/__main__.py` — replace the `run()` function body so config is loaded and the
prefix comes from it:

```python
async def run() -> None:
    load_dotenv()
    secrets = load_secrets(os.environ)
    config = load_config(os.environ.get("SAUCEBOT_CONFIG", "config.toml"))
    bot = SauceBot(command_prefix=config.command.prefix, engine=NullEngine())
    async with bot:
        await bot.start(secrets.discord_token)
```

Add the import `from saucebot.config import load_config` at the top.

- [ ] **Step 7: Run the full verification**

Run: `scripts/verify.sh`
Expected: `== all gates passed`

- [ ] **Step 8: Commit and open the draft PR (rituals R4–R6)**

```bash
git add saucebot/config.py config.example.toml tests/test_config.py saucebot/__main__.py
git commit -m "feat(config): validated TOML configuration" -m "Targeting, templates, thresholds and budget live in one file that is validated before the bot connects, so a bad placeholder or an empty channel list fails at startup with the offending key named." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

---

# PR 3 — `feat: SerpApi Google Lens engine and daily budget`

Branch `feat/serpapi-engine`, base `feat/config`. Labels `type:feature`, `area:engine`.
Why: the bot needs a real reverse-image backend and a hard spend limit; SerpApi's free plan is 250 searches a month and the API reports no remaining balance, so the bot must count for itself.
What: the Lens client with typed errors, real captured fixtures, a persisted daily budget, and `?sauce` wired to both.
Manual verification: with a real key in `.env`, `?sauce` on a widely-reposted image replies with a source URL; running it 9 times in a day gets the budget message on the 9th.

## Task 8: SerpApi Google Lens engine

**Files:**
- Create: `saucebot/engines/serpapi_lens.py`, `tests/fixtures/__init__.py` (empty), `tests/fixtures/serpapi_exact_matches.json`, `tests/fixtures/serpapi_no_results.json`, `scripts/capture_serpapi_fixture.py`
- Test: `tests/engines/test_serpapi_lens.py`

**Interfaces:**
- Consumes: `SourceHit`, `EngineError`, `BadKeyError`, `QuotaError` (Task 2).
- Produces:
  - `SERPAPI_ENDPOINT: str`, `SEARCH_TIMEOUT_SECONDS: int = 60`
  - `parse_exact_matches(payload: dict) -> list[SourceHit]`
  - `SerpApiLensEngine(session: aiohttp.ClientSession, api_key: str)` implementing `ImageSearchEngine`

- [ ] **Step 1: Save the captured fixtures**

`tests/fixtures/serpapi_exact_matches.json` — a real response captured from the live API on
2026-09-12, trimmed to the first five of 400 results with icon/thumbnail URLs shortened:

```json
{
  "search_metadata": {
    "id": "6aa5c78adc74d0792f5a55e4",
    "status": "Success",
    "created_at": "2026-09-12 21:43:38 UTC",
    "total_time_taken": 4.71
  },
  "search_parameters": {
    "engine": "google_lens",
    "url": "https://raw.githubusercontent.com/github/explore/main/topics/python/python.png",
    "type": "exact_matches"
  },
  "exact_matches": [
    {
      "position": 1,
      "title": "Python (@pythonlang) - Facebook",
      "source": "Facebook",
      "source_icon": "https://serpapi.com/images/i/TRIMMED",
      "link": "https://www.facebook.com/pythonlang/?locale=bs_BA",
      "thumbnail": "https://serpapi.com/images/url/TRIMMED",
      "actual_image_width": 532,
      "actual_image_height": 532
    },
    {
      "position": 2,
      "title": "Python User Group Graz - GitHub",
      "source": "GitHub",
      "source_icon": "https://serpapi.com/images/i/TRIMMED",
      "link": "https://github.com/pygraz",
      "thumbnail": "https://serpapi.com/images/url/TRIMMED",
      "actual_image_width": 200,
      "actual_image_height": 200
    },
    {
      "position": 3,
      "title": "Python is dead. Long live Python! | SOPHOS",
      "source": "Sophos",
      "source_icon": "https://serpapi.com/images/i/TRIMMED",
      "link": "https://www.sophos.com/en-us/blog/python-is-dead-long-live-python",
      "thumbnail": "https://serpapi.com/images/url/TRIMMED",
      "date": "Jan 3, 2020",
      "actual_image_width": 372,
      "actual_image_height": 194
    },
    {
      "position": 4,
      "title": "Python - Context BD",
      "source": "Context BD",
      "source_icon": "https://serpapi.com/images/i/TRIMMED",
      "link": "https://contextbd.com/python/",
      "thumbnail": "https://serpapi.com/images/url/TRIMMED",
      "date": "Apr 28, 2015",
      "actual_image_width": 400,
      "actual_image_height": 400
    },
    {
      "position": 5,
      "title": "Custom Software Development - SolDevelo",
      "source": "SolDevelo",
      "source_icon": "https://serpapi.com/images/i/TRIMMED",
      "link": "https://soldevelo.com/services/custom-software-development/",
      "thumbnail": "https://serpapi.com/images/url/TRIMMED",
      "actual_image_width": 454,
      "actual_image_height": 454
    }
  ]
}
```

`tests/fixtures/serpapi_no_results.json` — the real "nothing found" response. Note it is HTTP 200
with **no** `exact_matches` key and a top-level `error` string:

```json
{
  "search_metadata": {
    "id": "6aa5c742f6e9266efae862a0",
    "status": "Success",
    "created_at": "2026-09-12 21:42:26 UTC",
    "total_time_taken": 11.9
  },
  "search_parameters": {
    "engine": "google_lens",
    "url": "https://upload.wikimedia.org/wikipedia/en/c/cf/Distracted_boyfriend_meme.jpg",
    "type": "exact_matches"
  },
  "search_information": {
    "images_results_state": "Fully empty"
  },
  "error": "Google Lens hasn't returned any results for this query."
}
```

- [ ] **Step 2: Write the failing tests**

`tests/engines/test_serpapi_lens.py`:
```python
import json
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from saucebot.engines.base import BadKeyError, EngineError, QuotaError, SourceHit
from saucebot.engines.serpapi_lens import SerpApiLensEngine, parse_exact_matches

FIXTURES = Path(__file__).parent.parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_parses_captured_exact_matches() -> None:
    hits = parse_exact_matches(fixture("serpapi_exact_matches"))
    assert len(hits) == 5
    assert hits[0] == SourceHit(
        url="https://www.facebook.com/pythonlang/?locale=bs_BA",
        title="Python (@pythonlang) - Facebook",
        site="Facebook",
    )
    assert hits[1].url == "https://github.com/pygraz"


def test_no_results_response_is_empty_not_an_error() -> None:
    # HTTP 200 carrying a top-level `error` string means Lens found nothing.
    assert parse_exact_matches(fixture("serpapi_no_results")) == []


def test_missing_exact_matches_key_is_empty() -> None:
    assert parse_exact_matches({"search_metadata": {"status": "Success"}}) == []


def test_results_missing_a_link_are_skipped() -> None:
    payload = {
        "exact_matches": [{"position": 1, "title": "t", "source": "s"}, {"link": "https://ok"}]
    }
    assert [h.url for h in parse_exact_matches(payload)] == ["https://ok"]


def test_absent_optional_fields_become_empty_strings() -> None:
    hits = parse_exact_matches({"exact_matches": [{"link": "https://ok"}]})
    assert hits == [SourceHit(url="https://ok", title="", site="")]


@pytest.fixture
async def serpapi(aiohttp_server):
    """A stub SerpApi whose behaviour each test selects with a query flag."""
    state: dict[str, object] = {"status": 200, "payload": fixture("serpapi_exact_matches")}

    async def handler(request: web.Request) -> web.Response:
        state["last_query"] = dict(request.query)
        return web.json_response(state["payload"], status=state["status"])

    app = web.Application()
    app.router.add_get("/search", handler)
    server = await aiohttp_server(app)
    return server, state


async def make_engine(
    server, api_key: str = "test-key"
) -> tuple[SerpApiLensEngine, aiohttp.ClientSession]:
    session = aiohttp.ClientSession()
    engine = SerpApiLensEngine(
        session=session, api_key=api_key, endpoint=str(server.make_url("/search"))
    )
    return engine, session


async def test_search_sends_the_required_parameters(serpapi) -> None:
    server, state = serpapi
    engine, session = await make_engine(server)
    async with session:
        await engine.search("https://cdn.example/image.png", b"")
    assert state["last_query"] == {
        "engine": "google_lens",
        "type": "exact_matches",
        "url": "https://cdn.example/image.png",
        "api_key": "test-key",
    }


async def test_search_returns_hits(serpapi) -> None:
    server, _ = serpapi
    engine, session = await make_engine(server)
    async with session:
        hits = await engine.search("https://cdn.example/image.png", b"")
    assert hits[0].site == "Facebook"


async def test_search_returns_empty_for_the_no_results_response(serpapi) -> None:
    server, state = serpapi
    state["payload"] = fixture("serpapi_no_results")
    engine, session = await make_engine(server)
    async with session:
        assert await engine.search("https://cdn.example/image.png", b"") == []


async def test_unauthorised_raises_bad_key(serpapi) -> None:
    server, state = serpapi
    state["status"] = 401
    state["payload"] = {"error": "Invalid API key."}
    engine, session = await make_engine(server)
    async with session, pytest.raises(BadKeyError, match="Invalid API key"):
        await engine.search("https://cdn.example/image.png", b"")


async def test_rate_limited_raises_quota(serpapi) -> None:
    server, state = serpapi
    state["status"] = 429
    state["payload"] = {"error": "Your account has run out of searches."}
    engine, session = await make_engine(server)
    async with session, pytest.raises(QuotaError, match="run out of searches"):
        await engine.search("https://cdn.example/image.png", b"")


@pytest.mark.parametrize("status", [400, 500, 503])
async def test_other_failures_raise_engine_error(serpapi, status: int) -> None:
    server, state = serpapi
    state["status"] = status
    state["payload"] = {"error": "Missing query `url` parameter."}
    engine, session = await make_engine(server)
    async with session, pytest.raises(EngineError, match="Missing query"):
        await engine.search("https://cdn.example/image.png", b"")


async def test_non_json_body_raises_engine_error(aiohttp_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="<html>gateway error</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/search", handler)
    server = await aiohttp_server(app)
    engine, session = await make_engine(server)
    async with session, pytest.raises(EngineError):
        await engine.search("https://cdn.example/image.png", b"")
```

`aiohttp_server` comes from `pytest-aiohttp`. Add it as a dev dependency in Step 3.

- [ ] **Step 3: Add the test-server dependency**

Run: `uv add --dev pytest-aiohttp`
Expected: `pyproject.toml` dev group gains `pytest-aiohttp`, `uv.lock` updates. It brings the
`aiohttp_server` fixture used above.

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/engines/test_serpapi_lens.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.engines.serpapi_lens'`

- [ ] **Step 5: Implement `saucebot/engines/serpapi_lens.py`**

```python
"""SerpApi's Google Lens engine, restricted to exact matches.

Verified against the live API on 2026-09-12:

* Matches found -> HTTP 200 with a top-level ``exact_matches`` array.
* Nothing found -> HTTP 200, NO ``exact_matches`` key, and a top-level ``error``
  string ("Google Lens hasn't returned any results for this query."). That is an
  ordinary empty result, not a failure, so it maps to ``[]``.
* Bad key -> HTTP 401. Out of searches -> HTTP 429. Malformed request -> HTTP 400.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from saucebot.engines.base import BadKeyError, EngineError, QuotaError, SourceHit

log = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"
SEARCH_TIMEOUT_SECONDS = 60  # a Lens search takes 5-12s in practice


def parse_exact_matches(payload: dict[str, Any]) -> list[SourceHit]:
    """Turn a SerpApi Lens payload into hits. A payload with no matches yields []."""
    matches = payload.get("exact_matches") or []
    hits = []
    for match in matches:
        link = match.get("link")
        if not link:
            continue
        hits.append(
            SourceHit(url=link, title=match.get("title") or "", site=match.get("source") or "")
        )
    return hits


class SerpApiLensEngine:
    """Reverse-image search via SerpApi's Google Lens exact-match bucket."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: str = SERPAPI_ENDPOINT,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._endpoint = endpoint

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        """Return pages where this exact image appears. image_bytes is unused here."""
        params = {
            "engine": "google_lens",
            "type": "exact_matches",
            "url": image_url,
            "api_key": self._api_key,
        }
        timeout = aiohttp.ClientTimeout(total=SEARCH_TIMEOUT_SECONDS)
        try:
            async with self._session.get(
                self._endpoint, params=params, timeout=timeout
            ) as response:
                payload = await self._read_json(response)
                self._raise_for_status(response.status, payload)
        except aiohttp.ClientError as exc:
            raise EngineError(f"SerpApi request failed: {exc}") from exc
        except TimeoutError as exc:
            raise EngineError(f"SerpApi timed out after {SEARCH_TIMEOUT_SECONDS}s") from exc
        return parse_exact_matches(payload)

    async def _read_json(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload = await response.json(content_type=None)
        except (ValueError, aiohttp.ClientError) as exc:
            raise EngineError(f"SerpApi returned a non-JSON body (HTTP {response.status})") from exc
        if not isinstance(payload, dict):
            raise EngineError(f"SerpApi returned an unexpected body (HTTP {response.status})")
        return payload

    @staticmethod
    def _raise_for_status(status: int, payload: dict[str, Any]) -> None:
        if status == 200:
            return
        message = payload.get("error") or f"HTTP {status}"
        if status == 401:
            raise BadKeyError(f"SerpApi rejected the API key: {message}")
        if status == 429:
            raise QuotaError(f"SerpApi quota exhausted: {message}")
        raise EngineError(f"SerpApi error (HTTP {status}): {message}")
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/engines/test_serpapi_lens.py -v`
Expected: all tests pass.

- [ ] **Step 7: Write the fixture-capture script so fixtures can be refreshed**

`scripts/capture_serpapi_fixture.py`:
```python
"""Capture a real SerpApi Lens response into tests/fixtures/.

Usage:
    SERPAPI_API_KEY=... uv run python scripts/capture_serpapi_fixture.py <image-url> <fixture-name>

Trims the result list to five entries and shortens icon/thumbnail URLs so the
fixture stays readable. Refresh the fixtures with this rather than hand-editing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp

from saucebot.engines.serpapi_lens import SERPAPI_ENDPOINT

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
KEEP_METADATA = ("id", "status", "created_at", "total_time_taken")


async def capture(image_url: str, name: str) -> int:
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        print("SERPAPI_API_KEY is not set", file=sys.stderr)
        return 1
    params = {
        "engine": "google_lens",
        "type": "exact_matches",
        "url": image_url,
        "api_key": api_key,
    }
    async with (
        aiohttp.ClientSession() as session,
        session.get(SERPAPI_ENDPOINT, params=params) as response,
    ):
        payload = await response.json(content_type=None)
        print(f"HTTP {response.status}")

    payload["search_metadata"] = {
        key: value
        for key, value in payload.get("search_metadata", {}).items()
        if key in KEEP_METADATA
    }
    if "exact_matches" in payload:
        payload["exact_matches"] = payload["exact_matches"][:5]
        for match in payload["exact_matches"]:
            if "source_icon" in match:
                match["source_icon"] = "https://serpapi.com/images/i/TRIMMED"
            if "thumbnail" in match:
                match["thumbnail"] = "https://serpapi.com/images/url/TRIMMED"

    destination = FIXTURES / f"{name}.json"
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {destination} ({len(payload.get('exact_matches', []))} matches)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(capture(sys.argv[1], sys.argv[2])))
```

- [ ] **Step 8: Commit**

```bash
git add saucebot/engines/serpapi_lens.py tests/engines/test_serpapi_lens.py tests/fixtures \
        scripts/capture_serpapi_fixture.py pyproject.toml uv.lock
git commit -m "feat(engine): SerpApi Google Lens exact-match engine" -m "A 200 response carrying a top-level error string is Lens reporting no results, not a failure; it maps to an empty hit list so the bot simply stays quiet. Fixtures are captured from the live API." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 9: Daily search budget

**Files:**
- Create: `saucebot/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Produces: `DailyBudget(path: Path, max_per_day: int, today: Callable[[], date] = date.today)` with `async def acquire(self) -> bool` and a read-only `remaining` property.

- [ ] **Step 1: Write the failing tests**

`tests/test_budget.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.budget'`

- [ ] **Step 3: Implement `saucebot/budget.py`**

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_budget.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add saucebot/budget.py tests/test_budget.py
git commit -m "feat(budget): persisted daily search cap" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 10: Wire the engine and budget into `?sauce` and the entry point

**Files:**
- Modify: `saucebot/bot.py`, `saucebot/__main__.py`, `saucebot/exts/sauce.py`
- Test: `tests/exts/test_sauce_lookup.py`

**Interfaces:**
- Consumes: `SerpApiLensEngine` (Task 8); `DailyBudget` (Task 9); `Config` (Task 7).
- Produces:
  - `SauceBot(command_prefix: str, engine: ImageSearchEngine, budget: DailyBudget, config: Config)` with attributes `engine`, `budget`, `config`
  - `LookupResult(status: str, hit: SourceHit | None)` where `status` is exactly one of `"found"`, `"not_found"`, `"over_budget"`, `"error"`
  - `async lookup_source(engine: ImageSearchEngine, budget: DailyBudget, excluded_domains: frozenset[str], image_url: str, image_bytes: bytes) -> LookupResult` — Task 13's watcher calls this exact signature, so do not reorder its parameters

- [ ] **Step 1: Write the failing tests**

`tests/exts/test_sauce_lookup.py`:
```python
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


async def test_exhausted_budget_skips_the_engine(tmp_path: Path) -> None:
    engine = StubEngine(hits=[SourceHit("https://a.example/x", "A", "A")])
    limit = budget(tmp_path, max_per_day=1)
    await lookup_source(engine, limit, EXCLUDED, "https://cdn/x.png", b"")
    result = await lookup_source(engine, limit, EXCLUDED, "https://cdn/x.png", b"")
    assert result.status == "over_budget"
    assert engine.calls == 1


async def test_engine_failure_is_reported_not_raised(tmp_path: Path) -> None:
    engine = StubEngine(error=EngineError("boom"))
    result = await lookup_source(engine, budget(tmp_path), EXCLUDED, "https://cdn/x.png", b"")
    assert result.status == "error"
    assert result.hit is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/exts/test_sauce_lookup.py -v`
Expected: FAIL with `ImportError: cannot import name 'lookup_source'`

- [ ] **Step 3: Add `lookup_source` and the result type to `saucebot/exts/sauce.py`**

Insert after the `first_image_attachment` function:

```python
@dataclass(frozen=True)
class LookupResult:
    """Outcome of one search: found / not_found / over_budget / error."""

    status: str
    hit: SourceHit | None = None


async def lookup_source(
    engine: ImageSearchEngine,
    budget: DailyBudget,
    excluded_domains: frozenset[str],
    image_url: str,
    image_bytes: bytes,
) -> LookupResult:
    """Spend one unit of budget on a search and return the best non-excluded hit."""
    if not await budget.acquire():
        log.info("daily search budget exhausted; skipping %s", image_url)
        return LookupResult(status="over_budget")
    try:
        hits = await engine.search(image_url, image_bytes)
    except EngineError:
        log.exception("engine failed searching %s", image_url)
        return LookupResult(status="error")
    hits = filter_excluded_domains(hits, excluded_domains)
    if not hits:
        return LookupResult(status="not_found")
    return LookupResult(status="found", hit=hits[0])
```

Update the imports at the top of the file:

```python
from saucebot.budget import DailyBudget
from saucebot.engines.base import (
    EngineError,
    ImageSearchEngine,
    SourceHit,
    filter_excluded_domains,
)
```

`DEFAULT_EXCLUDED_DOMAINS` is no longer imported here; the config supplies the set.

- [ ] **Step 4: Rewrite the cog's `_lookup` to use it**

Replace the `Sauce._lookup` method with:

```python
    async def _lookup(self, ctx: commands.Context, attachment: discord.Attachment) -> None:
        try:
            image_bytes = await attachment.read()
        except discord.HTTPException:
            log.exception("could not read attachment on message %s", ctx.message.id)
            await ctx.reply("I couldn't read that image.")
            return
        async with ctx.typing():
            result = await lookup_source(
                self.bot.engine,
                self.bot.budget,
                self.bot.config.all_excluded_domains,
                attachment.url,
                image_bytes,
            )
        messages = {
            "over_budget": "Today's search budget is spent. Try again tomorrow.",
            "error": "Search failed. Check the logs.",
            "not_found": "No source found.",
        }
        if result.status == "found" and result.hit is not None:
            await ctx.reply(f"Source: {result.hit.url}")
            return
        await ctx.reply(messages[result.status])
```

`async with ctx.typing()` matters: a Lens search takes 5-12 seconds, so the typing indicator is
the only feedback the user gets that the bot is working.

- [ ] **Step 5: Add the channel restriction to the command**

Insert at the start of the `sauce` command body, right after `target = ctx.message`:

```python
        allowed = self.bot.config.command.allowed_channel_ids
        if allowed and ctx.channel.id not in allowed:
            return
```

- [ ] **Step 6: Update `SauceBot` to carry the budget and config**

`saucebot/bot.py` — replace the `__init__`:

```python
    def __init__(
        self,
        *,
        command_prefix: str,
        engine: ImageSearchEngine,
        budget: DailyBudget,
        config: Config,
    ) -> None:
        super().__init__(command_prefix=command_prefix, intents=build_intents())
        self.engine = engine
        self.budget = budget
        self.config = config
```

Add imports:

```python
from saucebot.budget import DailyBudget
from saucebot.config import Config
```

- [ ] **Step 7: Build the real engine in `saucebot/__main__.py`**

Replace `run()`:

```python
async def run() -> None:
    load_dotenv()
    secrets = load_secrets(os.environ)
    config = load_config(os.environ.get("SAUCEBOT_CONFIG", "config.toml"))
    budget = DailyBudget(
        path=Path(os.environ.get("SAUCEBOT_DATA_DIR", "data")) / "budget.json",
        max_per_day=config.search.max_searches_per_day,
    )
    async with aiohttp.ClientSession() as session:
        engine = SerpApiLensEngine(session=session, api_key=secrets.serpapi_api_key)
        bot = SauceBot(
            command_prefix=config.command.prefix,
            engine=engine,
            budget=budget,
            config=config,
        )
        async with bot:
            await bot.start(secrets.discord_token)
```

Imports to add:

```python
from pathlib import Path

import aiohttp

from saucebot.budget import DailyBudget
from saucebot.engines.serpapi_lens import SerpApiLensEngine
```

Remove the now-unused `from saucebot.engines.base import NullEngine`.

- [ ] **Step 8: Fix the bot tests for the new constructor**

`tests/test_bot.py` — replace the setup-hook test:

```python
async def test_setup_hook_loads_every_declared_extension(tmp_path) -> None:
    from saucebot.budget import DailyBudget
    from saucebot.config import parse_config

    config = parse_config(
        {"watch": {"channel_ids": [1]}, "response": {"templates": ["{source_url}"]}}
    )
    bot = SauceBot(
        command_prefix="?",
        engine=NullEngine(),
        budget=DailyBudget(path=tmp_path / "b.json", max_per_day=1),
        config=config,
    )
    await bot.setup_hook()
    assert set(bot.extensions) == set(EXTENSIONS)
    assert bot.get_cog("Sauce") is not None
    await bot.close()
```

- [ ] **Step 9: Run the full verification**

Run: `scripts/verify.sh`
Expected: `== all gates passed`

- [ ] **Step 10: Commit and open the draft PR (rituals R4–R6)**

```bash
git add saucebot/bot.py saucebot/__main__.py saucebot/exts/sauce.py \
        tests/exts/test_sauce_lookup.py tests/test_bot.py
git commit -m "feat: wire the Lens engine and daily budget into ?sauce" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

---

# PR 4 — `feat: author self-match filter`

Branch `feat/self-match`, base `feat/serpapi-engine`. Labels `type:feature`, `area:bot`.
Why: calling someone out for reposting their own art is the one failure mode that makes the bot genuinely unpleasant; it has to be impossible before the watcher is switched on.
What: a pure matching module, no Discord or HTTP, that decides whether a poster is the author of a hit.
Manual verification: `uv run pytest tests/test_matching.py -v` and read the parameter table.

## Task 11: Identity normalisation and handle extraction

**Files:**
- Create: `saucebot/matching.py`
- Test: `tests/test_matching.py`

**Interfaces:**
- Produces:
  - `normalise(value: str) -> str`
  - `PROFILE_HOSTS: dict[str, str]` mapping host suffix to extraction strategy name
  - `handle_from_url(url: str) -> str`
  - `title_candidates(title: str) -> list[str]`
  - `is_self_post(identities: Iterable[str], hit: SourceHit, threshold: int) -> bool`
  - `first_non_self_hit(hits: Sequence[SourceHit], identities: Iterable[str], threshold: int) -> SourceHit | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_matching.py`:
```python
import pytest

from saucebot.engines.base import SourceHit
from saucebot.matching import (
    first_non_self_hit,
    handle_from_url,
    is_self_post,
    normalise,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Freaq", "freaq"),
        ("DJ_Freaq", "djfreaq"),
        ("dj.freaq", "djfreaq"),
        ("dj-freaq", "djfreaq"),
        ("Freaq2024", "freaq"),
        ("  Freaq  ", "freaq"),
        ("", ""),
        ("1234", ""),
    ],
)
def test_normalise_strips_decoration_and_trailing_digits(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://twitter.com/pisuke_/status/1119375369423876096", "pisuke_"),
        ("https://x.com/pisuke_/status/1119375369423876096", "pisuke_"),
        ("https://www.reddit.com/u/spez/", "spez"),
        ("https://reddit.com/user/spez/comments/abc/title/", "spez"),
        ("https://www.instagram.com/p/abc/", ""),
        ("https://www.instagram.com/someartist/", "someartist"),
        ("https://www.tiktok.com/@someartist/video/123", "someartist"),
        ("https://bsky.app/profile/artist.bsky.social/post/abc", "artist.bsky.social"),
        ("https://www.deviantart.com/pantherd1945/art/Thing-123", "pantherd1945"),
        ("https://someartist.tumblr.com/post/123", "someartist"),
        ("https://www.facebook.com/pythonlang/", ""),
        ("https://example.com/some/page", ""),
        ("not a url", ""),
        ("https://twitter.com/", ""),
    ],
)
def test_handle_extraction_per_site(url: str, expected: str) -> None:
    assert handle_from_url(url) == expected


def hit(url: str = "https://example.com/x", title: str = "", site: str = "") -> SourceHit:
    return SourceHit(url=url, title=title, site=site)


def test_matching_handle_is_a_self_post() -> None:
    assert is_self_post(["Freaq"], hit("https://twitter.com/freaq_/status/1"), 80) is True


def test_different_handle_is_not_a_self_post() -> None:
    assert is_self_post(["Freaq"], hit("https://twitter.com/someoneelse/status/1"), 80) is False


def test_display_name_in_the_page_title_is_a_self_post() -> None:
    assert is_self_post(["djfreaq"], hit(title="Art by DJ Freaq - DeviantArt"), 80) is True


def test_site_name_alone_never_matches() -> None:
    assert is_self_post(["Reddit"], hit(site="Reddit"), 80) is False


def test_a_hit_with_no_handle_and_no_title_never_matches() -> None:
    assert is_self_post(["anyone"], hit(), 80) is False


def test_an_empty_identity_never_matches() -> None:
    assert is_self_post(["", "   "], hit("https://twitter.com/someone/status/1"), 80) is False


def test_threshold_is_inclusive() -> None:
    identity, handle_hit = "abcdefghij", hit("https://twitter.com/abcdefghix/status/1")
    assert is_self_post([identity], handle_hit, 90) is True
    assert is_self_post([identity], handle_hit, 91) is False


def test_any_identity_matching_is_enough() -> None:
    identities = ["someusername", "Server Nickname", "freaq"]
    assert is_self_post(identities, hit("https://twitter.com/freaq/status/1"), 80) is True


def test_first_non_self_hit_skips_the_posters_own_pages() -> None:
    hits = [
        hit("https://twitter.com/freaq/status/1"),
        hit("https://knowyourmeme.com/memes/thing"),
    ]
    chosen = first_non_self_hit(hits, ["freaq"], 80)
    assert chosen is not None
    assert chosen.url == "https://knowyourmeme.com/memes/thing"


def test_first_non_self_hit_returns_none_when_every_hit_is_the_poster() -> None:
    hits = [
        hit("https://twitter.com/freaq/status/1"),
        hit("https://www.deviantart.com/freaq/art/X"),
    ]
    assert first_non_self_hit(hits, ["freaq"], 80) is None


def test_first_non_self_hit_on_an_empty_list() -> None:
    assert first_non_self_hit([], ["freaq"], 80) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_matching.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.matching'`

- [ ] **Step 3: Implement `saucebot/matching.py`**

```python
"""Decide whether the person who posted an image is the person who made it.

Pure string work: no Discord types, no HTTP. The bot stays silent when a hit
looks like the poster's own page, which is the difference between a joke and
an insult.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from saucebot.engines.base import SourceHit

_DECORATION = re.compile(r"[\s._\-@]+")
_TRAILING_DIGITS = re.compile(r"\d+$")
_TITLE_SPLIT = re.compile(r"[^0-9A-Za-z]+")

# Hosts whose URL path carries the author's handle, and the path index it sits at.
_HANDLE_AT_INDEX: dict[str, int] = {
    "twitter.com": 0,
    "x.com": 0,
    "instagram.com": 0,
    "tiktok.com": 0,
    "deviantart.com": 0,
}
_HANDLE_AFTER_SEGMENT: dict[str, tuple[str, ...]] = {
    "reddit.com": ("u", "user"),
    "bsky.app": ("profile",),
}
# Paths on the above hosts that are content, not profiles.
_NOT_A_HANDLE = frozenset({"p", "reel", "status", "art", "explore", "i", "web", "home", "video"})


def normalise(value: str) -> str:
    """Lowercase, drop decoration and a trailing number, so `DJ_Freaq2024` -> `djfreaq`."""
    collapsed = _DECORATION.sub("", value.strip().lower())
    return _TRAILING_DIGITS.sub("", collapsed)


def handle_from_url(url: str) -> str:
    """Pull the author's handle out of a profile-style URL. Empty when there isn't one."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower().removeprefix("www.")
    segments = [segment for segment in parts.path.split("/") if segment]

    if host.endswith(".tumblr.com"):
        return host.removesuffix(".tumblr.com")

    for suffix, index in _HANDLE_AT_INDEX.items():
        if host == suffix or host.endswith("." + suffix):
            if len(segments) <= index:
                return ""
            candidate = segments[index].lstrip("@")
            return "" if candidate.lower() in _NOT_A_HANDLE else candidate

    for suffix, markers in _HANDLE_AFTER_SEGMENT.items():
        if host == suffix or host.endswith("." + suffix):
            for marker in markers:
                if marker in segments:
                    position = segments.index(marker)
                    if position + 1 < len(segments):
                        return segments[position + 1]
            return ""
    return ""


def title_candidates(title: str) -> list[str]:
    """Normalised name-shaped fragments of a page title.

    Each word, plus each adjacent pair joined, so a title like
    "Art by DJ Freaq - DeviantArt" yields the candidate "djfreaq" and matches a
    poster called ``DJ_Freaq``. Collapsing the whole title into one string
    instead would score ~48 against a 7-character name and never match.
    """
    words = [word for word in _TITLE_SPLIT.split(title) if word]
    pairs = [words[index] + words[index + 1] for index in range(len(words) - 1)]
    candidates = [normalise(fragment) for fragment in (*words, *pairs)]
    return [candidate for candidate in candidates if candidate]


def is_self_post(identities: Iterable[str], hit: SourceHit, threshold: int) -> bool:
    """True when any of the poster's names looks like the author of this hit."""
    candidates = [normalise(identity) for identity in identities]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return False

    handle = normalise(handle_from_url(hit.url))
    fragments = title_candidates(hit.title)
    for candidate in candidates:
        if handle and fuzz.ratio(candidate, handle) >= threshold:
            return True
        if any(fuzz.ratio(candidate, fragment) >= threshold for fragment in fragments):
            return True
    return False


def first_non_self_hit(
    hits: Sequence[SourceHit], identities: Iterable[str], threshold: int
) -> SourceHit | None:
    """The best hit that isn't the poster's own page, or None if they all are."""
    names = list(identities)
    for hit in hits:
        if not is_self_post(names, hit, threshold):
            return hit
    return None
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_matching.py -v`
Expected: all tests pass. `test_display_name_in_the_page_title_is_a_self_post` is the one to
watch: it only passes because `title_candidates` emits adjacent word pairs, so "DJ Freaq" in the
title becomes the candidate `djfreaq`. Verified against rapidfuzz 3.14: that scores 100, while
three unrelated names score 19, 44 and 48 against the same title.

- [ ] **Step 5: Run the full verification**

Run: `scripts/verify.sh`
Expected: `== all gates passed`

- [ ] **Step 6: Commit and open the draft PR (rituals R4–R6)**

```bash
git add saucebot/matching.py tests/test_matching.py
git commit -m "feat(matching): suppress call-outs when the poster is the author" -m "Fuzzy-compares the poster's username, display name and nickname against the handle in the source URL and the words in the page title, so an artist posting their own work is never accused of stealing it." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

---

# PR 5 — `feat: passive watcher with templated call-outs`

Branch `feat/watcher`, base `feat/self-match`. Labels `type:feature`, `area:bot`.
Why: this is the feature the fork exists for — the bot watches the configured channel and calls out reposts on its own.
What: the template renderer, the `on_message` listener with its whole skip chain, and a per-user cooldown.
Manual verification: post a widely-reposted image as a targeted user in the watched channel and get the call-out; post an unknown photo and get silence; post one of your own tweets and get silence.

## Task 12: Response rendering

**Files:**
- Create: `saucebot/responses.py`
- Test: `tests/test_responses.py`

**Interfaces:**
- Consumes: `SourceHit` (Task 2); `ResponseConfig`, `ResponseMode` (Task 7); `handle_from_url` (Task 11).
- Produces: `author_label(hit: SourceHit) -> str`; `render(templates: Sequence[str], hit: SourceHit, user_mention: str, rng: random.Random | None = None) -> str`; `SAFE_MENTIONS: discord.AllowedMentions` is **not** here — it lives in the watcher (Task 13) to keep this module Discord-free.

- [ ] **Step 1: Write the failing tests**

`tests/test_responses.py`:
```python
import random

from saucebot.engines.base import SourceHit
from saucebot.responses import author_label, render


def hit(
    url: str = "https://knowyourmeme.com/memes/x", title: str = "Meme", site: str = "KYM"
) -> SourceHit:
    return SourceHit(url=url, title=title, site=site)


def test_author_label_prefers_the_url_handle() -> None:
    assert author_label(hit(url="https://twitter.com/pisuke_/status/1")) == "pisuke_"


def test_author_label_falls_back_to_the_site_name() -> None:
    assert author_label(hit(url="https://example.com/page", site="Example Site")) == "Example Site"


def test_author_label_is_empty_when_there_is_nothing_to_say() -> None:
    assert author_label(SourceHit(url="https://example.com/p", title="", site="")) == ""


def test_renders_every_placeholder() -> None:
    template = "{user} {source_url} {title} {author} {site}"
    text = render([template], hit(url="https://twitter.com/pisuke_/status/1"), "<@1>")
    assert text == "<@1> https://twitter.com/pisuke_/status/1 Meme pisuke_ KYM"


def test_a_template_may_omit_placeholders() -> None:
    assert render(["Stolen meme!"], hit(), "<@1>") == "Stolen meme!"


def test_picks_from_the_template_list_deterministically_with_a_seeded_rng() -> None:
    templates = ["one {source_url}", "two {source_url}", "three {source_url}"]
    chosen = {render(templates, hit(), "<@1>", rng=random.Random(seed)) for seed in range(20)}
    assert len(chosen) == 3


def test_everyone_and_here_in_a_title_are_defanged() -> None:
    text = render(["{title} {source_url}"], hit(title="@everyone look @here"), "<@1>")
    assert "@everyone" not in text
    assert "@here" not in text
    assert "everyone" in text


def test_a_role_mention_in_a_title_is_defanged() -> None:
    text = render(["{title}"], hit(title="see <@&12345>"), "<@1>")
    assert "<@&12345>" not in text


def test_the_user_mention_itself_survives() -> None:
    assert render(["{user} busted"], hit(), "<@123456789>") == "<@123456789> busted"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_responses.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.responses'`

- [ ] **Step 3: Implement `saucebot/responses.py`**

```python
"""Turn a hit into the line the bot posts.

Kept free of Discord types so it can be tested as pure string work. The caller
is still responsible for passing AllowedMentions when it sends the result.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence

from saucebot.engines.base import SourceHit
from saucebot.matching import handle_from_url

# Text from a third-party page title must never ping the server.
_MASS_MENTION = re.compile(r"@(everyone|here)")
_ROLE_OR_USER_MENTION = re.compile(r"<@[!&]?\d+>")


def author_label(hit: SourceHit) -> str:
    """The handle behind the source, falling back to the site name."""
    return handle_from_url(hit.url) or hit.site


def _defang(text: str) -> str:
    """Strip anything in untrusted text that Discord would turn into a ping."""
    text = _MASS_MENTION.sub(r"\1", text)
    return _ROLE_OR_USER_MENTION.sub("", text).strip()


def render(
    templates: Sequence[str],
    hit: SourceHit,
    user_mention: str,
    rng: random.Random | None = None,
) -> str:
    """Fill one randomly chosen template. Missing placeholders render as empty."""
    chooser = rng or random
    template = chooser.choice(list(templates))
    values = {
        "user": user_mention,
        "source_url": hit.url,
        "title": _defang(hit.title),
        "author": _defang(author_label(hit)),
        "site": _defang(hit.site),
    }
    return template.format_map(_Defaulting(values)).strip()


class _Defaulting(dict):
    """format_map helper: an unknown placeholder renders as empty, never raises."""

    def __missing__(self, key: str) -> str:
        return ""
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_responses.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add saucebot/responses.py tests/test_responses.py
git commit -m "feat(responses): render call-out templates and defang untrusted page titles" -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

## Task 13: The passive watcher

**Files:**
- Create: `saucebot/exts/watcher.py`
- Modify: `saucebot/bot.py` (add the extension to `EXTENSIONS`)
- Test: `tests/exts/test_watcher.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `Cooldown(seconds: int, clock: Callable[[], float] = time.monotonic)` with `def check_and_stamp(self, user_id: int) -> bool`
  - `should_watch(message, config) -> bool`
  - `image_attachments(message, limit) -> list[discord.Attachment]`
  - `identities_of(member) -> list[str]`
  - cog `Watcher`, `async def setup(bot)`

- [ ] **Step 1: Write the failing tests**

`tests/exts/test_watcher.py`:
```python
from types import SimpleNamespace

import pytest

from saucebot.config import parse_config
from saucebot.exts.watcher import Cooldown, identities_of, image_attachments, should_watch

WATCHED_CHANNEL = 111
WATCHED_USER = 222


def config(**watch_overrides):
    watch = {"channel_ids": [WATCHED_CHANNEL], "user_ids": [WATCHED_USER]}
    watch.update(watch_overrides)
    return parse_config({"watch": watch, "response": {"templates": ["{source_url}"]}})


def attachment(content_type: str | None = "image/png"):
    return SimpleNamespace(content_type=content_type, url="https://cdn/x.png")


def message(
    *,
    channel_id: int = WATCHED_CHANNEL,
    author_id: int = WATCHED_USER,
    is_bot: bool = False,
    webhook_id: int | None = None,
    attachments: list | None = None,
):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
        author=SimpleNamespace(id=author_id, bot=is_bot),
        webhook_id=webhook_id,
        attachments=attachments if attachments is not None else [attachment()],
    )


def test_watches_a_targeted_user_in_a_targeted_channel() -> None:
    assert should_watch(message(), config()) is True


def test_ignores_other_channels() -> None:
    assert should_watch(message(channel_id=999), config()) is False


def test_ignores_untargeted_users() -> None:
    assert should_watch(message(author_id=999), config()) is False


def test_an_empty_user_list_watches_everyone() -> None:
    assert should_watch(message(author_id=999), config(user_ids=[])) is True


def test_ignores_bots() -> None:
    assert should_watch(message(is_bot=True), config(user_ids=[])) is False


def test_ignores_webhooks() -> None:
    assert should_watch(message(webhook_id=5), config(user_ids=[])) is False


def test_ignores_messages_without_images() -> None:
    assert should_watch(message(attachments=[]), config()) is False
    assert should_watch(message(attachments=[attachment("video/mp4")]), config()) is False


def test_image_attachments_respects_the_limit() -> None:
    msg = message(attachments=[attachment(), attachment(), attachment("text/plain"), attachment()])
    assert len(image_attachments(msg, limit=2)) == 2


def test_image_attachments_skips_unknown_content_types() -> None:
    msg = message(attachments=[attachment(None), attachment("image/gif")])
    assert len(image_attachments(msg, limit=5)) == 1


def test_identities_include_name_display_name_and_nick() -> None:
    member = SimpleNamespace(
        name="username", global_name="Display Name", display_name="Server Nick"
    )
    assert identities_of(member) == ["username", "Display Name", "Server Nick"]


def test_identities_tolerate_a_user_without_a_global_name() -> None:
    member = SimpleNamespace(name="username", global_name=None, display_name="username")
    assert identities_of(member) == ["username"]


def test_cooldown_blocks_a_second_callout_inside_the_window() -> None:
    now = {"t": 1000.0}
    cooldown = Cooldown(seconds=60, clock=lambda: now["t"])
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(1) is False
    now["t"] = 1059.0
    assert cooldown.check_and_stamp(1) is False
    now["t"] = 1060.0
    assert cooldown.check_and_stamp(1) is True


def test_cooldown_is_per_user() -> None:
    cooldown = Cooldown(seconds=60, clock=lambda: 1000.0)
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(2) is True


def test_a_zero_cooldown_never_blocks() -> None:
    cooldown = Cooldown(seconds=0, clock=lambda: 1000.0)
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(1) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/exts/test_watcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'saucebot.exts.watcher'`

- [ ] **Step 3: Implement `saucebot/exts/watcher.py`**

```python
"""The passive listener: search images posted by watched users, call out reposts.

Every branch that decides *not* to act is an early return, and every failure is
logged and swallowed — the channel must never see a traceback or an API error.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from saucebot.config import Config, ResponseMode
from saucebot.engines.base import SourceHit
from saucebot.exts.sauce import lookup_source
from saucebot.matching import first_non_self_hit
from saucebot.responses import render

if TYPE_CHECKING:
    from saucebot.bot import SauceBot

log = logging.getLogger(__name__)

# The call-out may only ping the poster, never a role and never the server.
SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True)


class Cooldown:
    """Per-user quiet period, so one person's posting spree can't spam the channel."""

    def __init__(self, seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def check_and_stamp(self, user_id: int) -> bool:
        """True if a call-out is allowed now; records the time when it is."""
        now = self._clock()
        previous = self._last.get(user_id)
        if previous is not None and now - previous < self._seconds:
            return False
        self._last[user_id] = now
        return True


def should_watch(message: discord.Message, config: Config) -> bool:
    """Whether this message is in scope for the watcher."""
    if message.author.bot or message.webhook_id is not None:
        return False
    if message.channel.id not in config.watch.channel_ids:
        return False
    if config.watch.user_ids and message.author.id not in config.watch.user_ids:
        return False
    return bool(image_attachments(message, limit=1))


def image_attachments(message: discord.Message, limit: int) -> list[discord.Attachment]:
    """Up to ``limit`` attachments that are actually images."""
    images = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
    return images[:limit]


def identities_of(member: discord.abc.User) -> list[str]:
    """The names this person is known by, de-duplicated, most specific last."""
    names = [
        member.name,
        getattr(member, "global_name", None),
        getattr(member, "display_name", None),
    ]
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


class Watcher(commands.Cog):
    def __init__(self, bot: SauceBot) -> None:
        self.bot = bot
        self.cooldown = Cooldown(bot.config.watch.min_seconds_between_callouts)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        config = self.bot.config
        if not should_watch(message, config):
            return
        if not self.cooldown.check_and_stamp(message.author.id):
            log.debug("cooldown active for %s; skipping", message.author.id)
            return
        try:
            await self._inspect(message, config)
        except Exception:
            # The listener must never propagate: a traceback here would be logged
            # by discord.py but could also leave the channel silently unprocessed.
            log.exception(
                "watcher failed on message %s in channel %s", message.id, message.channel.id
            )

    async def _inspect(self, message: discord.Message, config: Config) -> None:
        identities = identities_of(message.author)
        for attachment in image_attachments(message, config.search.max_attachments_per_message):
            try:
                image_bytes = await attachment.read()
            except discord.HTTPException:
                log.warning("could not read attachment on message %s", message.id)
                continue
            result = await lookup_source(
                self.bot.engine,
                self.bot.budget,
                config.all_excluded_domains,
                attachment.url,
                image_bytes,
            )
            if result.status == "over_budget":
                return
            if result.status != "found" or result.hit is None:
                continue
            hit = first_non_self_hit([result.hit], identities, config.match.self_match_threshold)
            if hit is None:
                log.info("message %s looks like the poster's own work; staying quiet", message.id)
                continue
            await self._call_out(message, hit, config)
            return

    async def _call_out(self, message: discord.Message, hit: SourceHit, config: Config) -> None:
        text = render(config.response.templates, hit, message.author.mention)
        try:
            if config.response.mode is ResponseMode.REPLY:
                await message.reply(text, allowed_mentions=SAFE_MENTIONS)
            else:
                await message.channel.send(text, allowed_mentions=SAFE_MENTIONS)
        except discord.HTTPException:
            log.exception("could not post the call-out for message %s", message.id)


async def setup(bot: SauceBot) -> None:
    await bot.add_cog(Watcher(bot))
```

Note `_inspect` only passes the single best hit to `first_non_self_hit`. That is deliberate:
`lookup_source` already reduced the engine's list to one hit. If a later change wants to fall
through to the second-best hit when the best is a self-post, `lookup_source` must return the
whole list instead — a change with its own issue, not a silent edit here.

- [ ] **Step 4: Register the extension**

`saucebot/bot.py` — change the tuple:

```python
EXTENSIONS: tuple[str, ...] = ("saucebot.exts.sauce", "saucebot.exts.watcher")
```

- [ ] **Step 5: Update the bot test's expectation**

`tests/test_bot.py` — after `await bot.setup_hook()` the assertion already compares against
`EXTENSIONS`, so it needs no edit, but add one line to confirm the new cog is live:

```python
    assert bot.get_cog("Watcher") is not None
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest tests/exts/test_watcher.py tests/test_bot.py -v`
Expected: all tests pass.

- [ ] **Step 7: Run the full verification**

Run: `scripts/verify.sh`
Expected: `== all gates passed`

- [ ] **Step 8: Commit and open the draft PR (rituals R4–R6)**

```bash
git add saucebot/exts/watcher.py saucebot/bot.py tests/exts/test_watcher.py tests/test_bot.py
git commit -m "feat(watcher): call out reposts from watched users automatically" -m "Searches images posted by targeted users in targeted channels and replies with a templated line only when a source is found and the poster is not its author. Silent on every other path, including engine failure." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

---

# PR 6 — `chore: Dockerfile and compose for wrz-droplet`

Branch `chore/deploy`, base `feat/watcher`. Labels `type:chore`, `area:deploy`.
Why: the bot has to stay online, and wrz-droplet already runs its other services under Docker.
What: a digest-pinned multi-stage image, a compose file mounting config and data, and the operator runbook in the README.
Manual verification: `docker compose up -d` on wrz-droplet, then `docker compose logs -f` shows the bot connecting; `?sauce` works in the server.

## Task 14: Container image and compose

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `compose.yml`
- Modify: `README.md` (append a Deployment section)

**Interfaces:**
- Produces: image entrypoint `python -m saucebot`; expects `/app/config.toml` read-only and `/app/data` writable.

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.github
.venv
__pycache__
*.pyc
.pytest_cache
.ruff_cache
tests
docs
scripts
data
.env
config.toml
.agent
```

- [ ] **Step 2: Write `Dockerfile`**

Digests resolved 2026-09-12; refresh them deliberately, never silently.

```dockerfile
# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /build
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/build/.venv/bin:$PATH" \
    SAUCEBOT_CONFIG=/app/config.toml \
    SAUCEBOT_DATA_DIR=/app/data
COPY --from=builder /build /build
WORKDIR /app
COPY saucebot/ ./saucebot/
RUN useradd --create-home --uid 10001 saucebot \
    && mkdir -p /app/data \
    && chown -R saucebot:saucebot /app
USER saucebot
ENTRYPOINT ["python", "-m", "saucebot"]
```

`--no-install-project` keeps the build cache valid when only source changes; the source is
copied into `/app` and found because the working directory is on `sys.path`.

- [ ] **Step 3: Write `compose.yml`**

```yaml
services:
  saucebot:
    build: .
    image: saucebot:latest
    container_name: saucebot
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./config.toml:/app/config.toml:ro
      - ./data:/app/data
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          memory: 256M
```

The memory limit and log rotation matter because wrz-droplet runs other services; an unbounded
log or a leak must not take the host down.

- [ ] **Step 4: Build and smoke-test the image locally**

```bash
docker compose build
docker run --rm --entrypoint python saucebot:latest -c "import saucebot, discord, rapidfuzz; print(saucebot.__version__, discord.__version__)"
```

Expected: prints `1.0.0` and the discord.py version. A missing-module error means the
`COPY saucebot/` step or the `PATH` is wrong.

- [ ] **Step 5: Confirm it refuses to start without secrets**

```bash
docker run --rm -e DISCORD_TOKEN= -e SERPAPI_API_KEY= saucebot:latest; echo "exit=$?"
```

Expected: one log line naming both missing variables and `exit=1`. This proves the
fail-loud path works in the container, not just in tests.

- [ ] **Step 6: Append the Deployment section to `README.md`**

```markdown
## Deployment (Docker)

On the host:

```bash
git clone https://github.com/thewrz/saucebot.git && cd saucebot
cp .env.example .env                  # fill in DISCORD_TOKEN and SERPAPI_API_KEY
cp config.example.toml config.toml    # set channel_ids, user_ids, templates
mkdir -p data
docker compose up -d --build
docker compose logs -f
```

`config.toml` is mounted read-only; `data/` holds the persisted daily search count.
After editing `config.toml`, restart with `docker compose restart` — the bot reads
its configuration once, at startup.

### Discord setup

The bot needs the **Message Content Intent** enabled in the developer portal, and
the *Read Messages*, *Send Messages*, and *Read Message History* permissions in the
channels it watches. To limit it to one channel, deny its role *View Channel*
everywhere else — Discord enforces that server-side, which is stronger than config.
```

- [ ] **Step 7: Run the full verification**

Run: `scripts/verify.sh`
Expected: `== all gates passed`

- [ ] **Step 8: Commit and open the draft PR (rituals R4–R6)**

```bash
git add Dockerfile .dockerignore compose.yml README.md
git commit -m "chore(deploy): digest-pinned container image and compose stack" -m "Runs as a non-root user with a memory limit and rotated logs so it behaves alongside the other services on the host." -m "Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>"
```

---

## After the last PR

1. **Adversarial review, once, at the very end.** With CI green on the whole stack, ask the *other*
   harness for a blind review of `git diff main...feat/watcher`. The direction depends on who
   executed this plan: a **Claude** executor asks Codex (`gpt-6-astra`, effort `xhigh`); a **Codex**
   executor asks Claude (`claude-opus-5`, effort `high`). Feed the reviewer only the diff — no spec,
   no plan, no issues, no PR bodies — with file access disabled, so it judges what the code *does*
   rather than what it was meant to do. Run it once; do not re-run after the fix push.
2. **Merge in order** (1 → 6), letting each stacked PR retarget to `main` as its base merges.
3. **Board:** move each issue to `Done` as its PR merges (`gh-project-move <N> "Done"`).
4. **Rotate the SerpApi key** used during development, and confirm the deployed `.env` has the new one.
5. **Open the follow-up issue** for the Google Vision engine (`type:feature`, `area:engine`),
   referencing spec section 6.2.

## Out of scope (do not build)

Per-guild config, slash commands, a database, the alias map, perceptual-hash repost detection,
the SerpApi image-upload flow, image downscaling, and the Vision engine. Each is its own issue
if it is ever wanted.
