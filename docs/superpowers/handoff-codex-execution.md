# Handoff — Codex execution of the saucebot watcher plan

Audience: a Codex session (gpt-6-astra) taking over implementation with no prior
conversation context. Everything you need is on disk; nothing depends on the
chat that produced the plan.

---

## 1. Mission

Implement `docs/superpowers/plans/2026-09-12-saucebot-watcher.md` in full: 15 TDD
tasks across 6 stacked draft PRs that turn this fork of `sowwic/saucebot` into a
passive Discord watcher. It reverse-image-searches images posted by targeted
users in targeted channels and calls the poster out with a configurable line and
the source link — but only when a source is actually found, and never when the
poster looks like the original author.

The design was settled in a brainstorm and approved. **Do not redesign it.** If
you believe a decision is wrong, finish the task under the documented decision
and raise the concern in the PR body rather than silently diverging.

## 2. Where everything is

| What | Path |
|---|---|
| Repository | `<repository-root>` (remote `origin` = `thewrz/saucebot`, `upstream` = `sowwic/saucebot`) |
| **The plan (your instruction set)** | `docs/superpowers/plans/2026-09-12-saucebot-watcher.md` |
| The design spec (the *why*) | `docs/superpowers/specs/2026-09-12-saucebot-watcher-design.md` |
| This handoff | `docs/superpowers/handoff-codex-execution.md` |

Read the plan's header, **Global Constraints**, and **PR ritual** sections before
touching anything. The plan argues from the spec; read the spec when a task's
intent is unclear, not to re-litigate it.

### Repository state at handoff

- Branch `docs/spec` holds the spec and the plan (2 commits). **It is local-only —
  not yet pushed.** PR 1 bases on it, so the plan's Task 0 pushes it first. Do
  that before any `gh pr create`, or the base ref will not exist.
- `main` is still upstream's last commit (`e8118c1`). Nothing has been built yet.
- The personal negative-case image supplied during development was removed at
  the owner's request. Use an operator-provided image outside Git for live checks.
- `.agent/` is untracked session state. **Never commit it.**

## 3. "Ultracode" for Codex — what actually applies here

Codex has no feature literally named *ultracode*. On this machine the equivalent
capability is the `multi_agent` feature, which `codex features list` reports as
**stable and enabled**, together with the `parallel-issues` skill, which dispatches
one Codex issue lead per isolated git worktree.

**`parallel-issues` is the wrong tool for this plan, and you should not use it.**
That skill parallelises *independent* GitHub issues. This plan is a dependency
chain: each PR branches from the previous one, and PRs 3 and 5 modify the same
files (`saucebot/bot.py`, `saucebot/__main__.py`, `saucebot/exts/sauce.py`).
Fanning it out would violate the plan's own rule to serialise overlapping work.

The correct execution model is **sequential subagent-driven development**: one
fresh subagent per task, 15 in total, with a review gate between each. Delegate
via whatever subagent mechanism your harness exposes under `multi_agent`; if that
is unavailable, run each task as its own `codex exec` invocation so every task
still starts with clean context. Fresh context per task is the point — not
parallelism.

### The one safe parallel opportunity

Task 11 (PR 4, `saucebot/matching.py`) creates exactly one new module plus its
test and shares no file with PR 2 or PR 3. It depends only on `SourceHit` from
PR 1. If you want concurrency, branch `feat/self-match` from `chore/repackage`
instead of `feat/serpapi-engine` and run it alongside PR 2/PR 3 in a separate
worktree. The cost is that PR 5 then needs both lines merged before it starts.
Take the simple sequential chain unless throughput genuinely matters.

## 4. Execution protocol

For each task, in plan order (Task 0, then 1 through 14):

1. **Dispatch one fresh subagent** with the prompt template in section 5.
2. The subagent executes **only that task's steps**, in order, and stops.
3. **Review its work before dispatching the next one.** Confirm: the test was
   written first and observed failing, the implementation is the plan's, the
   verification command was actually run, and its output was reported rather
   than assumed.
4. If a task's deliverable is wrong, send the same subagent a correction rather
   than starting the next task on a broken base.

Do not batch several tasks into one subagent. The task boundaries are the review
gates, and they are what keep a 15-task run from drifting.

### Between PRs

Each PR section in the plan ends with rituals R4–R6: commit, run
`scripts/verify.sh`, push, open a **draft** PR based on the previous PR's branch,
and move the issue to `In review`. Complete the whole ritual before starting the
next PR's first task.

## 5. Subagent prompt template

Every implementer subagent gets this verbatim, with the bracketed values filled:

```
You are implementing ONE task from an approved plan. Do only this task.

Repository: <repository-root>
Plan:       docs/superpowers/plans/2026-09-12-saucebot-watcher.md
Your task:  Task [N] — [title]
Your branch: [branch]

## Branch Rules (MANDATORY — before touching any file)
1. `git branch --show-current` → if on main, STOP and create the branch first.
2. Read the plan's "Global Constraints" and "PR ritual" sections.
3. Never commit to main.
4. Branch for this task: [branch]
5. Create if missing: git fetch origin && git checkout -b [branch] [base-branch]

## How to work
- Open the plan and find "## Task [N]". Execute its steps IN ORDER.
- It is test-driven: write the failing test, RUN it and confirm it fails for the
  stated reason, then implement, then RUN the test again and confirm it passes.
  Never skip the observed-failure step.
- The plan contains the actual code. Use it. If reality forces a deviation,
  make it, and say so explicitly in your final report.
- Stage explicit paths. NEVER `git add -A` or `git add .` — the untracked
  `.agent/` directory must not be committed.
- End your commit message with: Co-Authored-By: Codex gpt-6-astra <noreply@openai.com>

## Definition of done
The task's final step is complete, its verification command was actually run,
and you are reporting its real output. If a gate fails, report the failure —
never describe a skipped or failing check as passing.

## Report back
- Files created/modified
- The verification command you ran and its actual output
- Any deviation from the plan and why
- Anything you could not complete
```

## 6. Constraints that override your defaults

These come from the repository owner's global rules and the plan's Global
Constraints. They are not negotiable.

- **Attribution: credit yourself, not Claude.** The plan's code blocks carry the
  placeholder `Co-Authored-By: <YOUR-AGENT> <noreply@<provider>>`. Substitute
  `Co-Authored-By: Codex gpt-6-astra <noreply@openai.com>`. Agent-drafted issue
  and PR bodies open with `This was written agentically; verify its assertions:`
  and close with `🤖 Co-authored by Codex gpt-6-astra.` Do not credit Claude for
  work you did.
- **Every PR opens as a draft** (`gh pr create --draft`). A human flips it to
  ready. Never open a ready-for-review PR.
- **Never trigger review bots.** Do not post `@coderabbitai review` or any other
  bot trigger. Automatic and incremental reviews are deliberately off; the human
  triggers them.
- **Issues first.** Each PR gets its GitHub issue before code, with labels, and
  the PR closes it. Task 0 creates the labels.
- **GitHub API budget: REST first.** Use `gh api repos/{owner}/{repo}/...` for
  issues and PR data. `gh issue list/view/create --json` rides GraphQL, which is
  the scarce pool shared across every tool on this account. GraphQL is only for
  Projects v2 and PR review-thread resolution state.
- **Board moves** use `gh-project-move <issue> "<status>"` (In progress → In
  review → Done). If the repo is on no Project board, the helper no-ops. Never
  fail the actual work over a board move.
- **Gates are evidence.** Run `scripts/verify.sh` and report its real output.
  Never delete, loosen, or suppress a gate to go green.
- **Secrets never enter the repo.** `DISCORD_TOKEN` and `SERPAPI_API_KEY` live in
  `.env`, which is gitignored. `config.toml` is gitignored;
  `config.example.toml` is tracked.

## 7. Adversarial review — the direction reverses for you

The plan's "After the last PR" section says to request the end-of-work adversarial
review from Codex. **That was written for a Claude executor. You are Codex, so
the cross-harness reviewer is Claude**: `claude-opus-5`, effort `high`.

Run it **once**, at the very end, after CI is green on the whole stack. Feed the
reviewer only `git diff main...feat/watcher` — no spec, no plan, no issues, no PR
bodies — with file access disabled, so it judges what the code *does* rather than
what it was meant to do. Do not re-run it after the fix push.

## 8. Known gotchas

- **The SerpApi trap.** A Lens search that finds nothing returns **HTTP 200** with
  *no* `exact_matches` key plus a top-level `error` string reading "Google Lens
  hasn't returned any results for this query." That is the ordinary empty result
  and must map to an empty list, never an exception — it is the common case for
  this bot, so treating it as a failure would make the bot raise on nearly every
  image. Verified against the live API on 2026-09-12; fixtures in Task 8 pin it.
  401 = bad key, 429 = quota, 400 = malformed. A search takes 5–12 seconds.
- **`uv audit` must stay clean.** The upstream pins are all CVE-stale and one
  (`install==1.3.4`) no longer exists on PyPI. Task 1 replaces the whole
  dependency set via `uv add`; do not resurrect `requirements.txt`.
- **`pytest` with `asyncio_mode = "auto"`** means async tests need no decorator.
  Task 8 adds `pytest-aiohttp` for its `aiohttp_server` fixture.
- **Manual verification of PR 3 and PR 5 needs real credentials.** A Discord bot
  token with the Message Content intent enabled, and a SerpApi key. Ask the
  repository owner rather than skipping the check — and say plainly in the PR
  that manual verification is pending if they are unavailable.
- **The development SerpApi key is to be rotated** once implementation is done.
  It is the last item in the plan's "After the last PR" list.

## 9. Stop and ask

Stop and escalate to the repository owner rather than improvising when:

- a task's tests cannot pass without changing the plan's documented interface;
- `uv audit` reports an advisory with no available fixed version;
- CI fails for a reason outside the diff;
- a GitHub API call reports a rate-limit or scope error (`gh auth refresh -s project`
  fixes a missing project scope);
- any step would require committing a secret, or weakening a gate.

Report what is applied versus remaining. Never retry into an exhausted rate-limit
pool, and never re-run a creation batch on uncertainty — read what exists first.

## 10. Definition of done

- Six draft PRs open, stacked 1→6, each under ~500 lines of real change, each
  closing its issue, each with CI green.
- `scripts/verify.sh` passes: `ruff check`, `ruff format --check`, `pytest`,
  `uv audit`.
- `docker compose build` succeeds and the container fails loudly with exit 1 when
  secrets are missing.
- The one end-of-work adversarial review has been run by Claude Opus 5 and its
  findings addressed.
- A follow-up issue exists for the Google Vision engine (spec section 6.2).
- The repository owner has been told the SerpApi key needs rotating.
