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
4. `cp config.example.toml config.toml` and set the channels, users, and response templates.
5. `uv sync` then `uv run python -m saucebot`.

## Commands

- `?sauce` with an image attached — search that image.
- `?sauce <message link>` — search the first image on a message in this server.

The watcher uses the exact channel IDs in `config.toml`; include each child
thread ID explicitly when threads should be watched. Its per-user cooldown starts
when a watched search is attempted, including searches that return no result,
match the poster, or fail. A selected Discord CDN URL is sent to SerpApi, which
fetches the image for the Lens search.

The watcher and `?sauce` share the daily search cap. The manual command has no
per-user cooldown; use `command.allowed_channel_ids` to control where it can run.

## Development

`scripts/verify.sh` runs lint, format check, tests, and a dependency audit; CI
runs the same script.

## Deployment (Docker)

On the host:

```bash
git clone https://github.com/thewrz/saucebot.git && cd saucebot
cp .env.example .env                  # fill in DISCORD_TOKEN and SERPAPI_API_KEY
cp config.example.toml config.toml    # set channel_ids, user_ids, templates
mkdir -p data
sudo chown -R 10001:10001 data        # the container writes its daily budget as UID 10001
docker compose up -d --build
docker compose logs -f
```

`config.toml` is mounted read-only; `data/` holds the persisted daily search count.
If the budget file is missing, corrupt, or unreadable, the bot follows its
recovery policy and starts that day's count at zero.
After editing `config.toml`, restart with `docker compose restart` — the bot reads
its configuration once, at startup.

### Discord setup

The bot needs the **Message Content Intent** enabled in the developer portal, and
the *Read Messages*, *Send Messages*, and *Read Message History* permissions in the
channels it watches. To limit it to one channel, deny its role *View Channel*
everywhere else — Discord enforces that server-side, which is stronger than config.

## License

MIT for this fork's changes (see `LICENSE`). Upstream carried no license.
