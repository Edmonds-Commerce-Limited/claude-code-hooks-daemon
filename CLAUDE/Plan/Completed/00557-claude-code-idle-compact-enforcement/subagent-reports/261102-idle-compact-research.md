# Idle compaction in Claude Code: research report

Date: 2026-11-02. Installed Claude Code: `2.1.316 (Claude Code)`
(`/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`).

Evidence sources, by label:

- **[VD-SR]** the vendored settings reference
  `remote-docs/code.claude.com/docs/en/settings-reference.md`, `### idleCompaction`,
  lines 2397-2444, and `### autoCompactEnabled`, lines 2190-2207. It was captured on
  2026-10-23, before 2.1.314, so it is stale on rollout scope (see section 3).
- **[VD-HK]** the vendored hooks page `remote-docs/code.claude.com/docs/en/hooks.md`,
  lines 3287-3330 (PreCompact and PostCompact).
- **[VD-PC]** the vendored prompt-caching page
  `remote-docs/code.claude.com/docs/en/prompt-caching.md`, lines 197 and 274-305.
- **[CL]** the upstream changelog
  `https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md`, downloaded
  on 2026-11-02 to `untracked/scratch/cl/CHANGELOG.md`. The vendored
  `remote-docs/.../changelog.md` copy stops at 2.1.303.
- **[EV]** the live env-vars page `https://code.claude.com/docs/en/env-vars`, fetched on
  2026-11-02. It is not vendored.
- **[BIN]** strings and minified code taken from the 2.1.316 binary with GNU grep and dd.
  Extracts are in `untracked/scratch/idle-strings.txt` and
  `untracked/scratch/idle-code-{a,d,e}.txt`. Minified identifiers such as `K3o` and `kf`
  are build-specific.

## 1. What it does

- **What it is.** It "compacts a long conversation that you've stepped away from, shortly
  before its prompt cache expires. Your next message then sends a summary instead of the
  whole conversation." When you return, a line starts with
  `Compacted while idle, before the prompt cache expired`. [VD-SR 2399]
- **When it fires.** It is tied directly to the prompt-cache TTL. It fires roughly 54 min
  after the last request, which is 0.9 of the 1h cache TTL.
  - The docs give the idle-time condition as about fifty-four minutes since the last
    request, with the computer awake at that point. [VD-SR 2408]
  - The changelog for 2.1.299 describes the same figure, "before its one-hour prompt cache
    expires". [CL line 824]
  - In the code, the class `RZt.#t` (arm) computes
    `fire = lastActivityAt + (expiresAt - lastActivityAt) * 0.9` with `G3o=0.9`. It returns
    early unless the last request's cache `ttl === "1h"` and `q8() === oR`, where
    `oR=3600000`. [BIN]
  - The timer is a plain `setTimeout(...).unref()` in the REPL process. It is re-armed after
    each main-thread turn: `Mmn()` saves the turn's cache-safe params, then calls
    `dWt.of(session).arm(savedAt, ...)`. So it runs in the background while the REPL is idle
    and needs no user input. [BIN]
- **Gates checked at fire time.** `K3o(...)` returns a skip reason in this order: [BIN]
  1. `compaction_off`: `kf()` is false. That is the case when `DISABLE_COMPACT` or
     `DISABLE_AUTO_COMPACT` is set, or `autoCompactEnabled` is false.
  2. `idle_compaction_off`: `idleCompaction` is false.
  3. `precompute_compaction_off` or `swap_unsupported`: summarize path only.
  4. `prefix_changed`.
  5. `not_one_hour`.
  6. `lapsed`: the cache is not warm, or the timer fired more than 60000 ms late
     (`z3o=60000`). This covers a machine that was asleep.
  7. `small`: context tokens are below `max(100000, CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS ?? 200000)`.
  8. `newer_request`.
  9. `near_limit`: the rate-limit status is not `"allowed"`.
- **Session kind.** Arming also requires `KU()`. That is true for an interactive session.
  It is false when `CLAUDE_CODE_SESSION_KIND` is `bg`, `daemon` or `daemon-worker`, and for
  non-interactive child sessions. [BIN] The docs say "you're in an interactive terminal
  session". [VD-SR 2403]
- **What it compacts.** It compacts the main conversation, as a normal compaction would.
  - There are two outcomes. `compacted` uses the host's normal compaction and shows
    "Compacted while idle". `summarized` writes a summary in the background, which is used on
    the next message; it shows `Compacted using a summary written while you were away` and
    requires `precomputeCompactionEnabled`. [BIN]
  - The changelog for 2.1.314 describes the IDE path as "summarized, and the summary is used
    on your next message if the prompt cache has expired". [CL]
- **Telemetry events.** `tengu_idle_compact_fired`, `tengu_idle_compact_settled` and
  `tengu_idle_compaction_setting_changed`. [BIN]
- **A second, undocumented mechanism: `SleepCompactor`.** [BIN, idle-code-d.txt]
  - It is gated by `CLAUDE_CODE_SLEEP_COMPACT && uie()`, with its own defaults: minimum
    150000 tokens, floor 60000, and `CLAUDE_CODE_SLEEP_COMPACT_AFTER_MS` clamped to
    60000-210000.
  - It honours the same `kf()` and `idleCompaction` switches.
  - It appears to be for host or remote runners. It is not in any doc found. Unverified
    purpose.
- **Other unrelated strings.** `CLAUDE_CODE_IDLE_THRESHOLD_MINUTES` and
  `CLAUDE_CODE_IDLE_TOKEN_THRESHOLD` are in the env table. They look unrelated, possibly
  the older away-from-session `/clear` nudge. Unverified.

## 2. Configuration

| Control                                                                                                                                                                        | Where / scope                                                                                  | Default                                               | Evidence                                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `idleCompaction` (bool)                                                                                                                                                        | settings.json, any scope: user, project, local or managed. `--settings` also works.            | `true`                                                | [VD-SR 2410-2417]. Schema text in \[BIN\]: "Set to false to stop Claude Code from compacting a long conversation while the session is idle. Defaults to true." Needs v2.1.290 or later. |
| `/config` row **Idle compaction** (category "Model & output")                                                                                                                  | Writes to user settings. Shown only when the effective source is user settings or the default. | on                                                    | [VD-SR 2425-2428]. [CL 2.1.302]. [BIN] `He=ei("idleCompaction",!0).source,po=He==="userSettings"\|\|...`                                                                                |
| `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` (env, or settings `env`)                                                                                                                 | Process environment                                                                            | 200000. Values below 100000 are raised to 100000.     | [EV], [VD-SR 2434]. [BIN] `EZt(){return Math.max(W3o,i.CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS??j3o)}` with `j3o=200000,W3o=1e5`                                                            |
| `autoCompactEnabled=false`                                                                                                                                                     | settings, any scope                                                                            | `true`                                                | Also turns idle compaction off. [VD-SR 2207]                                                                                                                                            |
| `DISABLE_AUTO_COMPACT=1` / `DISABLE_COMPACT=1`                                                                                                                                 | env                                                                                            | unset                                                 | Turn idle compaction off. [EV], [BIN] `kf()`                                                                                                                                            |
| `precomputeCompactionEnabled` (bool)                                                                                                                                           | settings                                                                                       | `true`                                                | Gates only the "summarized" path. In the [BIN] schema. Not in the vendored docs, so undocumented in what we hold.                                                                       |
| Feature-flag kill switches: `DISABLE_GROWTHBOOK`, `DISABLE_TELEMETRY`, `DO_NOT_TRACK`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, a third-party provider, or the apps gateway | env                                                                                            | n/a                                                   | The live [EV] "Features that need feature-flag fetching" section still lists idle compaction. This conflicts with CL 2.1.314; see section 3.                                            |
| TTL controls `promptCacheTtl`, `ENABLE_PROMPT_CACHING_1H`, `FORCE_PROMPT_CACHING_5M`                                                                                           | settings / env                                                                                 | 1h cache TTL only on a subscription within plan usage | Idle compaction needs the 1h TTL, so `FORCE_PROMPT_CACHING_5M=1` disables it indirectly. [VD-PC 281-305]                                                                                |
| CLI flag                                                                                                                                                                       | none found                                                                                     |                                                       | No dedicated CLI flag was found in the docs or the binary. Unverified as absent.                                                                                                        |

## 3. Rollout status

- **Introduced.**
  - Announced in **2.1.299** (2026-10-14): "Added idle compaction in the terminal ...". [CL]
  - The key and env var "need v2.1.290 or later". That suggests the code shipped dormant
    from 2.1.290 behind a flag and was announced at 2.1.299. Inference, not confirmed.
  - The `/config` row came in **2.1.302** (2026-10-16). [CL]
  - **2.1.314** made two changes. It "Added idle compaction to VS Code and Claude Desktop's
    Code tab". It also "Changed idle compaction to also run for subscribers with telemetry
    turned off, and on Bedrock, Vertex, Foundry and LLM gateways once the one-hour prompt
    cache is on". [CL]
- **Feature flag.**
  - The docs say it needs GrowthBook flag fetching. The env-vars page lists `DISABLE_GROWTHBOOK`.
    [VD-SR 2406, 2428] [EV line 248]
  - The docs also say the first session after an upgrade may lack flag-gated features. [EV]
  - I did not find a dedicated `tengu_*` flag check inside the idle-compaction code path
    (`RZt`/`K3o`). Where the gate sits (call site, TTL flag, or server-side bucket) is
    **unverified**.
  - Whether the flag is at 100% or a partial percentage rollout is **unverified**. No source
    states a percentage.
- **On by default?** Yes, for eligible sessions: "on by default for conversations that meet
  all of these conditions". [VD-SR 2401]
- **By plan.** Effectively subscription-first, because the 1h cache TTL is the default only
  on a Claude subscription within plan usage. Over the plan limit (usage credits), the main
  conversation drops to the 5m cache TTL, so idle compaction does not fire. API-key users
  need `promptCacheTtl: "1h"`. [VD-PC 281-297]
- **By platform.**
  - Terminal from 2.1.299. VS Code and Desktop from 2.1.314.
  - Bedrock, Vertex, Foundry and gateways from 2.1.314, once the 1h cache TTL is on. [CL]
- **Doc conflict.** The live env-vars page still says flag fetching is required, so
  telemetry-off sessions and third-party providers lose idle compaction. Changelog 2.1.314
  says it now runs for both. Treat the changelog as newer; the docs page is likely lagging.
  Unverified which is correct at runtime.

## 4. Interaction with existing compaction settings

- **`autoCompactEnabled`**: a master switch. When false, idle compaction is off too
  (`kf()` is checked first). [VD-SR 2207] [BIN]
- **`DISABLE_AUTO_COMPACT` and `DISABLE_COMPACT`**: both turn it off. [EV 103-104] [BIN]
- **`CLAUDE_CODE_AUTO_COMPACT_WINDOW` and `autoCompactWindow`**: independent. Idle
  compaction uses only its own token minimum.
  - The docs warn that on a 200K window, auto-compact fires before 200K. So with the default
    minimum, idle compaction never applies unless you lower
    `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`. [VD-SR 2436]
  - **This repository** runs `CLAUDE_CODE_AUTO_COMPACT_WINDOW=600000` in the session
    environment and sets `autoCompactWindow: 480000` in `.claude/settings.json`. So
    200K-600K contexts are routine here, and idle compaction will qualify.
- **`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`**: no reference in the idle path (`K3o` and `EZt`), so
  no interaction found. Unverified beyond the code read.
- **PreCompact and PostCompact hooks**: yes, both fire, with `trigger: "auto"`.
  - Matcher `auto` covers "Auto-compact when the conversation reaches the auto-compact
    window, and idle compaction". [VD-HK 3294, 3326]
  - The hook schema in [BIN] enumerates only `["manual","auto"]`.
  - For `auto`, `custom_instructions` is `null`.
  - A PreCompact exit code 2 or `"decision":"block"` skips a proactive compaction. [VD-HK]
  - Whether the background "summarized" (precompute) path also fires PreCompact is
    **unverified**.
  - Consequence for this repository: `handlers/pre_compact/compaction_signal.py` records
    `origin="auto"` for idle compactions. These cannot be told apart from window
    auto-compactions by the hook input alone.
- **Cron interaction (inference, important here).** The failsafe and persistent crons tick
  hourly. An idle session over 200K tokens will be idle-compacted at 0.9 of the 1h cache
  TTL, just before the tick. Each idle hour then costs one compaction plus a
  post-compaction turn rather than a cold re-read. This is relevant to issue #109 and
  Plan 00452 Task 4.5.

## 5. How this repository checks Claude Code config today, and where a check goes

- **`src/claude_code_hooks_daemon/handlers/session_start/optimal_config_checker.py`**,
  class `OptimalConfigCheckerHandler`:
  - `_run_checks(project_root)` (line 460) returns six check dicts. Each has `name`,
    `passed`, `current`, `why`, `fix`, `where`, `docs`, and optionally `warn`.
  - It is consumed by `cmd_check` in `src/claude_code_hooks_daemon/daemon/cli.py:2016`, at
    line 2052 (`hooks-daemon check`).
  - **Add a `_check_idle_compaction(project_root)` method here.** Model it on
    `_check_effort_source`, which already reads the user, project and local settings plus
    the env section. It would read `idleCompaction`, `autoCompactEnabled`,
    `DISABLE_AUTO_COMPACT`/`DISABLE_COMPACT`, `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`, the TTL
    variables and the flag-fetch kill switches. Then append it to `_run_checks`.
  - `_enforce_settings_sync()` (line 492) is the only place that silently writes
    `~/.claude/settings.json`; today it writes only `alwaysThinkingEnabled`. Enforcement
    (writing `idleCompaction`) would go there.
  - That method's docstring records the policy against second-guessing owner settings
    (Plan 00466 N47). Auto-writing `idleCompaction` would be an owner decision.
  - The `DOCS_URL` constant points at `/settings`. The idle check should cite
    `/settings-reference#idlecompaction`.
- **`hooks-daemon optimise-checklist`** (`cmd_optimise_checklist`, cli.py:7772, which uses
  `config_optimisation/checklist.py::build_checklist`) is derived from the handler registry.
  It covers which daemon handlers are on, not Claude Code settings. It is **not** the place
  for this check.
- **`handlers/session_start/config_optimisation_reminder.py`**: a SessionStart reminder.
  Also not the place for this check.
- **PreCompact handlers**: `handlers/pre_compact/compaction_signal.py` (`_origin()`, at
  lines 107-117) and `disclosure_reset_pre_compact.py`. Idle compactions arrive here as
  `trigger="auto"`.
- **`daemon/spend_report.py`** mentions revisiting the autocompact window. No idle logic.
- **Issue #46** (OPEN, `agent-needs-human`): "optimal_config_checker: add a seventh check for
  CLAUDE_CODE_AUTO_COMPACT_WINDOW".
  - It is filed as **Plan 00428** (Not Started). The triage blocked it because the parser
    semantics could only be inferred from the binary.
  - That objection is now largely dissolved: the vendored settings reference documents
    `autoCompactWindow` as 100000-1000000. Changelog 2.1.304 and the env-vars page say
    `k`/`M` suffixes are accepted from 2.1.304. That contradicts the issue's correction
    comment, which said "plain digits only", but that comment was written about 2.1.274.
  - An idle-compaction check is a natural sibling and could share a "compaction" audit block.
- **Issue #109** (OPEN, `agent-needs-human`): "Idle-session economics: compact before the
  cache goes cold ...".
  - It was folded into **Plan 00452** (Blocked) as Tasks 4.5 and 4.6.
  - Its research comment says "No Claude Code idle-compaction setting was found". That is
    now **obsolete**: upstream shipped exactly the "compact while the cache is still warm"
    behaviour in 2.1.299, with the gates above.

## Open / unverified

- The exact GrowthBook flag name and its rollout percentage.
- Whether the docs or changelog 2.1.314 are right about telemetry-off sessions and
  third-party providers.
- Whether the precompute ("summarized") path fires PreCompact.
- The purpose of `CLAUDE_CODE_SLEEP_COMPACT`.
- The vendored `settings-reference.md` and `changelog.md` predate 2.1.314. A
  `bin/hooks-daemon remote-docs refresh` is recommended; it was not done here because the
  brief limits edits.

Scratch files written: `untracked/scratch/idle-strings.txt`, `idle-code-{a,b,c,d,e,f}.txt`,
`issue46.txt`, `issue109.txt` and `cl/CHANGELOG.md`. All are untracked, under
`untracked/scratch/`.
