# Final adversarial review disposition

One blind review completed using Claude Opus 5 with high effort on 2026-09-13.
Input was the implementation diff from `main...feat/watcher`; `docs/**` was
excluded to honor the prohibition on giving the reviewer the spec, plan, or
handoff. Tools, file access, MCP, Chrome, and session persistence were disabled.
The deployment PR was outside the prescribed review diff. No second review ran.

Payload SHA-256: `6f482cb675d114d080a05a87d41dcfe30488ba3c7834c27d2f2ecf43975ed53b`.

## Findings and disposition

| ID | Finding | Disposition |
| --- | --- | --- |
| H1 | Manual replies allow third-party mentions | Fixed in `c9625cc`: global deny-all mention default; watcher explicitly permits only poster. |
| H2 | Failed searches consume budget | Retained by design: spec section 7 counts grants/attempts. Refunding ambiguous network failures could exceed the provider quota. Errors are logged and surfaced by the manual command. |
| M1 | Cooldown begins before search, including no-result searches | Retained as supplied in Task 13 to throttle search attempts. Operator documentation clarifies this behavior. |
| M2 | Manual quota draining and command/watcher double searches | No new command rate policy is introduced; shared daily cap and configurable command channels are the approved controls. Duplicate processing of valid commands was fixed in `d09020d` using Discord command-context resolution. |
| M3 | aiohttp exception strings can reveal API key | Fixed in `10f86a7`: status/type-only diagnostics and suppressed sensitive exception chains prevent request URLs and provider error bodies from leaking keys in logged tracebacks. |
| M4 | Same-guild links can read channels inaccessible to caller | Fixed in `3117be8`: caller view/history permissions and private-thread membership are checked before fetching. |
| L1 | Hypothetical found result without hit raises KeyError | Not reachable from `lookup_source`, which constructs found only with a real hit. A richer result type is deferred until an actual interface extension. |
| L2 | Engine config supports only one backend | Deliberate single-backend implementation. Validation rejects all unsupported names; future engine support is issue #15. |
| L3 | Synchronous small budget write blocks event loop | Retained for the single-process, low daily-cap deployment. Offloading adds scheduling complexity without evidence of problematic latency. |
| L4 | Cooldown map retains inactive users | Deferred scaling concern: the map retains one timestamp per observed poster for the process lifetime. The configured channel/user scope bounds ordinary use; no new cleanup policy or testing-only API is introduced. |
| L5 | Exclusions omit additional Discord hosts | Retain the two built-in hosts specified by the approved design; operators can extend `excluded_domains`. No claim of comprehensive Discord-domain coverage. |
| L6 | Trailing digits normalize to the same identity | Explicitly approved matching rule and tested behavior. Conservative self-match suppression intentionally prefers silence; no algorithm redesign. |
| L7 | SerpApi does not use downloaded bytes | Explicit common engine interface supplies URL and bytes to support the future Vision backend; downloads remain as planned. |
| L8 | Watched channel IDs do not include child threads | Exact channel IDs are the approved selection behavior; operator documentation says to list thread IDs explicitly. |
| L9 | Non-atomic persistence can reset budget on crash | Fixed in `899185d`: same-directory atomic replacement, temporary-file cleanup, and refusal on persistence failure. Corrupt-file recovery remains the explicitly tested plan behavior and is documented as a limitation. |
| L10 | uv audit may be unavailable in CI | Not reproduced: canonical verification and all six actual CI jobs successfully ran `uv audit`. The gate remains mandatory. |
| X1 | Negative-case image appears accidental | User-approved fixture explicitly required by handoff; preserved unchanged. No deletion. JSON fixtures drive offline engine tests; JPEG is for live negative-case verification. |
| X2 | Third-party image submission undocumented | Operator documentation explains that SerpApi receives the selected Discord image URL and fetches the image. |

## Additional implementation review

Budget calculation now uses UTC, validates persisted nonnegative integer counts,
and logs exhaustion once per day (`0ba8cf2` removes duplicate lookup messages). Corrections preserve the documented
`async acquire() -> bool` interface. Regression strengthening in `9f06a88`
proved the pre-fix code granted on write failure and persisted the local date
instead of UTC; the corrected code passes both tests.

Design limitation retained: the supplied watcher only checks the first non-excluded result from the shared
lookup helper for self-matching, even though spec prose describes scanning all
results. The implementation follows Task 13's prescribed interface; broader
result selection needs an explicitly approved interface change.

## Verification and delivery

Final code verification: `UV_CACHE_DIR=/tmp/saucebot-uv-cache scripts/verify.sh`
passes Ruff lint, format checks, 159 tests, and `uv audit`. The pre-existing
discord.py `audioop` deprecation warning remains. Final container build and smoke
evidence is recorded in PR #14.
Manual Discord/SerpApi checks and remote deployment remain pending credentials
and an accessible deployment target. No live search or deployment is claimed.
The six prescribed PR boundaries exceed the nominal size target for PRs #4,
#8, and #12: PR #4 is 1,133 changed lines excluding `uv.lock` (759 additions,
374 deletions), PR #8 is 1,007 (976 additions, 31 deletions), and PR #12 is
508 (507 additions, 1 deletion). Their bodies report these actual counts.

Workflow exceptions were disclosed and corrected without history rewriting:
watcher issue #11 was created after Task 12 code and corrected before Task 13;
the accidental upstream draft `sowwic/saucebot#2` from Task 0 was closed; and
the target docs PR #2 was verified. All PRs remain drafts for human review,
readiness, and merging. The development SerpApi key must be rotated.
