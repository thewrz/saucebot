# Saucebot watcher — design spec

Date: 2026-09-12
Status: approved in brainstorm, pending written review
Fork: https://github.com/thewrz/saucebot (upstream sowwic/saucebot, no license)

## 1. Goal

Turn saucebot from a manual `?sauce` command into a passive watcher that
reverse-image-searches images posted by targeted users in targeted channels
of one Discord server, and calls the poster out with a configurable line and
the source link — but only when a source is actually found, and never when
the poster appears to be the original author.

## 2. Decisions taken in brainstorm

| Topic | Decision |
|---|---|
| Deployment shape | One server, flat config file, no per-guild anything |
| Watcher behaviour | Watch-and-call-out: search targeted users' images silently, reply only on a real, non-self hit; `?sauce` stays for manual use |
| Search engine | SerpApi Google Lens (`type=exact_matches`) first; Google Cloud Vision web detection as a later second engine behind the same interface; SauceNao dropped (anime-only indexes, no photo-meme coverage — verified with a live test image) |
| Self-match | Fuzzy only (rapidfuzz), no alias map |
| Call-out format | Plain-text templates with placeholders; `reply` or `mention` mode |
| Runtime | Docker on the wrz-droplet VPS (multi-service Ubuntu host) |
| Layout | Single installable package `saucebot/`, `python -m saucebot`, uv + ruff + pytest, multi-stage Dockerfile (matches python-discord/bot and kkrypt0nn template conventions surveyed 2026-09-12) |
| License | MIT for the fork's changes, credit sowwic, note upstream carried no license; GPL `saucenao-api` dependency removed |

## 3. Discord facts that shape the design

- Channel targeting exists natively (deny the bot's role View Channel), but a
  config allowlist is still needed so the bot can see a channel for `?sauce`
  without watching it.
- User targeting does not exist natively; it is config.
- The passive listener needs the privileged Message Content intent — without
  it `Message.attachments` is empty. No verification under 100 guilds.
- discord.py 2.x: intents mandatory, extension `setup()` is async, extensions
  load in `setup_hook`, single shared `aiohttp.ClientSession`.

## 4. Package layout

```
saucebot/
  __main__.py        entry point: logging, .env, config, session, bot.run
  bot.py             SauceBot(commands.Bot): setup_hook loads exts
  config.py          TOML load + pydantic validation → Config
  budget.py          daily search counter persisted to data/budget.json
  matching.py        is_self_post(author_identities, hit) → bool
  responses.py       render(templates, hit, poster) → str
  engines/
    base.py          ImageSearchEngine protocol, SourceHit, EngineError family
    serpapi_lens.py  first engine
    google_vision.py (later PR)
  exts/
    watcher.py       passive on_message listener
    sauce.py         manual ?sauce command
tests/
  fixtures/          captured JSON responses; IMG_5524.jpg (negative smoke image)
docs/superpowers/specs/
```

Removed: `cogs/`, `saucebot/logger.py`, lock-file/ctypes code, three
PyInstaller `build_*.sh`, `.vscode/`, `res/icon.ico`, `requirements.txt`.

## 5. Configuration

Secrets in `.env` (gitignored): `DISCORD_TOKEN`, `SERPAPI_API_KEY`. Missing
either → startup error naming the variable.

Behaviour in `config.toml` (mounted read-only into the container):

```toml
[watch]
channel_ids = [123456789012345678]   # required, non-empty
user_ids = []                        # empty = everyone in the channel
min_seconds_between_callouts = 60    # per-user cooldown

[search]
engine = "serpapi_lens"              # later also "google_vision"
max_searches_per_day = 8             # keeps a month under SerpApi's 250 free
max_attachments_per_message = 3
excluded_domains = []                # merged with built-in Discord CDN hosts

[match]
self_match_threshold = 80            # rapidfuzz score 0-100

[response]
mode = "reply"                       # "reply" | "mention"
templates = [
  "Stolen meme! Source: {source_url}",
  "{user} that's from {author}: {source_url}",
]

[command]
prefix = "?"
allowed_channel_ids = []             # empty = anywhere the bot can see
```

Validation (pydantic, at startup, before connecting): typed snowflake IDs,
`channel_ids` non-empty, threshold in 0..100, `mode` in the enum, templates
non-empty, every `{placeholder}` in the allowed set
`{user, source_url, title, author, site}`, warn if `mode = "mention"` and no
template contains `{user}`. Errors name the offending key. `config.py` is the
only module that reads TOML.

## 6. Engine layer

```python
@dataclass(frozen=True)
class SourceHit:
    url: str
    title: str
    site: str

class ImageSearchEngine(Protocol):
    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]: ...
```

Engines receive both URL and bytes so URL-based (SerpApi) and bytes-based
(Vision) engines share one signature. Nothing downstream knows which engine ran.

### 6.1 SerpApi Google Lens

`GET https://serpapi.com/search` with `engine=google_lens`,
`type=exact_matches`, `url=<Discord attachment URL>`, `api_key`, via the
shared aiohttp session. Discord attachment URLs are public and signed with
roughly a day's validity; the lookup runs seconds after the post. SerpApi's
upload/`image_id` flow is out of scope until expiry actually bites.

Each `exact_matches[]` entry → `SourceHit(link, title, source)`.

Errors → typed exceptions carrying the server message: `BadKeyError`,
`QuotaError`, `EngineError` (includes SerpApi's in-body `error` string on a
200). Exact HTTP codes are pinned during implementation with one live call.

"Found a source" = at least one `exact_matches` entry left after dropping
excluded domains. `visual_matches` is never requested.

Built-in excluded domains: `cdn.discordapp.com`, `media.discordapp.net`.

### 6.2 Google Cloud Vision (later)

`POST vision.googleapis.com/v1/images:annotate`, `WEB_DETECTION`, base64
content, API key in `x-goog-api-key`. `pagesWithMatchingImages` with a full
match → `SourceHit`. Separate issue and PR; not part of this spec's plan.

## 7. Budget

`budget.py`: `async acquire() -> bool`. Counts grants per UTC day against
`max_searches_per_day`; persists `{"date": "YYYY-MM-DD", "count": n}` to
`data/budget.json` after each grant so restarts don't reset it. Resets when
the stored date differs from today. Watcher and `?sauce` share one instance.
When exhausted: watcher drops the search and logs once per day; `?sauce`
replies "daily search budget spent". SerpApi's own monthly cap is the
backstop outside the bot.

## 8. Matching

`matching.py` has no Discord or HTTP dependency.

- Discord identities: username, global display name, guild nickname.
- Normalize both sides: lowercase; strip leading `@`; drop spaces, `_`, `.`,
  `-`; strip trailing digits.
- Hit signals: (a) a handle extracted from the URL path for known profile
  sites — x.com/twitter.com (`/handle/status/`), reddit (`/u/`, `/user/`),
  instagram.com, tiktok.com (`@handle`), bsky.app (`/profile/`),
  deviantart.com, `*.tumblr.com` subdomain; (b) page title tokens. The `site`
  name is never a candidate.
- Compare: `rapidfuzz.fuzz.ratio(identity, handle)` and
  `fuzz.token_set_ratio(identity, title)`. Any score ≥ `self_match_threshold`
  → self-post. No handle and empty title → never a match.
- Across hits: if every hit is self, silence; else the first non-self hit in
  engine order is the source.

## 9. Watcher (`exts/watcher.py`)

`on_message` chain of early returns: author is bot/webhook → skip; channel not
in `watch.channel_ids` → skip; `watch.user_ids` non-empty and author not in
it → skip; no `image/*` attachments → skip; per-user cooldown active → skip.

For each qualifying attachment (up to `max_attachments_per_message`):
`budget.acquire()` (false → log once, stop) → `engine.search()` → drop
excluded domains → self-match filter → first surviving hit → responder →
stop (at most one call-out per message).

All exceptions caught at the handler boundary, logged with message/channel
IDs, never echoed to chat.

## 10. Manual command (`exts/sauce.py`)

`?sauce` with an attachment or a message link. Same engine and budget, no
self-match filter, no templates: replies `Source: <url>` or
`No source found.` Message links are honoured only inside the invoking guild
(closes the upstream cross-guild read). `command.allowed_channel_ids`
restricts where it runs. Human-readable one-liners for quota/budget; generic
"search failed" otherwise.

## 11. Responses (`responses.py`)

`render(templates, hit, poster) -> str`: `random.choice` of a template,
`str.format_map` with a defaulting dict so missing placeholders render empty.
`{user}` = poster mention; `{author}` = extracted handle, else `site`.
Sent with `AllowedMentions` permitting only the poster, so `@everyone` in a
title cannot ping. `mode="reply"` → `message.reply`; `mode="mention"` →
`channel.send` with `{user}` in the text.

## 12. Entry point and bot

`__main__.py`: stdlib logging to stdout (Docker captures it); load `.env`;
load/validate config; open one `aiohttp.ClientSession`; build engine and
budget; construct `SauceBot`; `asyncio.run` inside `async with bot`.
Intents: `default()` + `message_content`. `SauceBot.setup_hook` loads
`saucebot.exts.watcher` and `saucebot.exts.sauce`.

## 13. Deployment

`pyproject.toml` + `uv.lock`; Python ≥ 3.12 (stdlib `tomllib`); deps
`discord.py`, `aiohttp`, `python-dotenv`, `pydantic`, `rapidfuzz` (all
MIT/Apache); dev `ruff`, `pytest`, `pytest-asyncio`. Multi-stage Dockerfile:
uv from `ghcr.io/astral-sh/uv` (digest-pinned), `uv sync --frozen --no-dev`,
source copied last, base `python:3.12-slim` digest-pinned, entrypoint
`python -m saucebot`. `compose.yml`: `env_file: .env`, `./config.toml:ro`,
`./data` rw, `restart: unless-stopped`, memory limit. README rewritten;
credits sowwic; MIT LICENSE added.

## 14. Errors

`ConfigError`; `EngineError` → `BadKeyError`, `QuotaError`; `BudgetExhausted`.
Watcher swallows and logs everything at its boundary. `?sauce` surfaces
one-line human messages, never server text.

## 15. Testing

Boundary tests, HTTP and Discord mocked, fixtures are real captured JSON.

- `matching`: casing/digits equivalence; handle extraction per site; title
  token match; no-signal never matches; threshold edge.
- `engines/serpapi_lens`: exact matches, empty, in-body error, 401, 429.
- `responses`: every placeholder; missing placeholder; `@everyone`
  neutralized; seeded random choice.
- `config`: valid round-trip; each invalid case names the key.
- `budget`: cap, refusal, UTC rollover, reload from file.
- `watcher`: each skip branch; one call-out for a multi-image post; errors
  swallowed.

CI (GitHub Actions, SHA-pinned): `ruff check`, `ruff format --check`,
`pytest`, `uv audit`. Coverage is a diagnostic, not a gate.

## 16. Delivery — PR sequence (each < 500 LOC, independently green)

1. `chore: repackage as installable module with uv, ruff, pytest, CI` — layout,
   dep refresh, delete PyInstaller/lock-file/logger, `?sauce` ported to
   discord.py 2.x with cross-guild fix and a stub engine, LICENSE, README.
2. `feat: TOML config with validation`
3. `feat: SerpApi Google Lens engine and daily budget` — `?sauce` wired to it
4. `feat: author self-match filter`
5. `feat: passive watcher with templated call-outs` — feature-complete
6. `chore: Dockerfile and compose for wrz-droplet`
7. (separate later issue) `feat: Google Vision engine`

Each PR: GitHub issue first with labels, draft PR, attribution banner.

## 17. Out of scope

Per-guild config, slash commands, database, alias map, perceptual-hash
repost detection, SerpApi image upload flow, image downscaling, Vision
engine (own issue).

## 18. Security review of upstream (2026-09-12)

No malicious code or prompt injection found. One dead pin (`install==1.3.4`,
404 on PyPI, unused) removed. All 2021 pins carry CVEs (aiohttp, certifi,
idna, python-dotenv, requests, urllib3); discord.py 1.7.3 EOL. Upstream
`?sauce` could read messages across guilds; fixed in PR 1.
