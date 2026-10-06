# Plan 00494 Tasks 1.1-1.3: Claude Code mods, review and brainstorm (Opus)

Citation shorthand: `M/x.md:N` is `remote-docs/code.claude.com/docs/en/plugins/mods/x.md` line N;
`D/x.md:N` is `remote-docs/code.claude.com/docs/en/x.md` line N; `DTS:N` is
`remote-docs/raw.githubusercontent.com/anthropics/claude-code/main/mods/types/claude-code.d.ts.md` line N.
Line numbers are file lines, frontmatter included.

## Sources

Captured with `bin/hooks-daemon remote-docs add` (commits `013b4ab38`, `0bd1c8ce0`). **No capture was refused.**
One page (`M/create.md`) had a fake session id swapped by the registry and is recorded `converted` with `value_swaps`.

The mods pages (all ten listed under "Mods" in `https://code.claude.com/docs/llms.txt`):

| Path                | URL                                                       |
| ------------------- | --------------------------------------------------------- |
| `M/overview.md`     | https://code.claude.com/docs/en/plugins/mods/overview     |
| `M/create.md`       | https://code.claude.com/docs/en/plugins/mods/create       |
| `M/reference.md`    | https://code.claude.com/docs/en/plugins/mods/reference    |
| `M/interface.md`    | https://code.claude.com/docs/en/plugins/mods/interface    |
| `M/gallery.md`      | https://code.claude.com/docs/en/plugins/mods/gallery      |
| `M/events.md`       | https://code.claude.com/docs/en/plugins/mods/events       |
| `M/api.md`          | https://code.claude.com/docs/en/plugins/mods/api          |
| `M/test.md`         | https://code.claude.com/docs/en/plugins/mods/test         |
| `M/troubleshoot.md` | https://code.claude.com/docs/en/plugins/mods/troubleshoot |
| `M/admin.md`        | https://code.claude.com/docs/en/plugins/mods/admin        |

Pages the mods pages depend on (not previously vendored; the old `plugins.md` / `plugins-reference.md` captures are
different URLs):

| Path                              | URL                                                        |
| --------------------------------- | ---------------------------------------------------------- |
| `D/plugins/overview.md`           | https://code.claude.com/docs/en/plugins/overview           |
| `D/plugins/components.md`         | https://code.claude.com/docs/en/plugins/components         |
| `D/plugins/manifest-reference.md` | https://code.claude.com/docs/en/plugins/manifest-reference |
| `D/plugins/loading.md`            | https://code.claude.com/docs/en/plugins/loading            |
| `D/plugins/security.md`           | https://code.claude.com/docs/en/plugins/security           |
| `D/plugins/org.md`                | https://code.claude.com/docs/en/plugins/org                |
| `D/settings-reference.md`         | https://code.claude.com/docs/en/settings-reference         |
| `D/managed-settings.md`           | https://code.claude.com/docs/en/managed-settings           |
| `D/permissions.md`                | https://code.claude.com/docs/en/permissions                |

Upstream source, captured `--verbatim` (fidelity `verbatim`):

- `DTS` = https://raw.githubusercontent.com/anthropics/claude-code/main/mods/types/claude-code.d.ts. The reference
  calls this "the complete reference" (`M/reference.md:22`). Caveat: it says it was written by Claude Code 2.1.277
  and marks the surface "EARLY ACCESS" (`DTS:11-14`), while the docs describe 2.1.289 (`M/reference.md:19`) and this
  machine runs 2.1.291. The docs say to trust the copy Claude Code writes beside a `--plugin-dir` mod for your own
  build (`M/create.md:287-299`).
- https://raw.githubusercontent.com/anthropics/claude-code/main/mods/sec-default/README.md (the built-in guard).

Already vendored and used: `D/changelog.md` (mods shipped in 2.1.287, October 1 2026, `D/changelog.md:348-350`; heavy
churn since, e.g. `D/changelog.md:34-38,65-88`).

Not captured (deliberately): the sample mods in `anthropics/claude-code-playground` and the built-in mods' source under
`anthropics/claude-code/tree/main/mods/` (code, not documentation; `M/overview.md:62-66,252-257`).

## Review

### What a mod is

A mod is a Claude Code plugin whose `hooks/hooks.json` has a `modules` key pointing at one JavaScript/TypeScript ES
module (the "hooks module") that exports `register(on, options)` (`M/overview.md:19`, `M/reference.md:29-37`,
`M/create.md:145`). Claude Code calls the module's functions in its own process when events fire; each function can
observe, rewrite or answer the event as middleware (`next(e)`) (`M/overview.md:187-195`, `M/events.md:25`). The docs
call these functions "hooks" and the settings-file kind "settings hooks" (`M/overview.md:22`). It is not a new package
type: every plugin mechanism (marketplaces, scopes, versioning, `enabledPlugins`) applies unchanged
(`M/overview.md:51-56`, `M/admin.md:204-213`), and the same plugin can also ship skills, MCP servers and settings hooks
(`M/overview.md:231`, `M/reference.md:32`).

### Authoring, packaging, loading

- Three files: `.claude-plugin/plugin.json` (no mod-specific required fields), `hooks/hooks.json` with
  `"modules": ["./register.js"]`, and the module. Optional `types/index.d.ts` for `$.state`; `*.test.ts` files
  (`M/reference.md:29-35`). No Node, bundler or build step (`M/create.md:27`).
- The module has no Node.js APIs, no timer globals, no file or network access of its own; standard web APIs only.
  Everything outside goes through the `$` mods API (`M/api.md:180`, `M/overview.md:195`).
- Static analysis is load-bearing: Claude Code refuses to load a module whose API use it cannot read
  (`M/admin.md:127`). Rules: write `$.ns.method` in full, string-literal event names, no dynamic `import()`, imports
  only from inside the plugin or `claude-code` (`M/create.md:324-331`). `claude plugin validate` prints the `hooks:`
  and `calls:` lines (plus `env reads/writes`, `state reads/writes`) (`M/create.md:305-320`).
- Two authoring paths: Claude writes one via the built-in `plugin-authoring` skill into
  `~/.claude/dev-mods/<session-id>/<name>/`, loaded after a per-session hot-reload approval (`M/create.md:37-56`);
  or a human develops with `claude --plugin-dir <dir>`, which hot-reloads on save (`M/create.md:212-265`). Claude-written
  mods are deleted after `cleanupPeriodDays` unless copied out (`M/create.md:70`), and do not load in `claude -p`,
  `dontAsk`, an untrusted workspace, `--safe-mode`/`--bare`, or under `disableAllHooks` (`M/create.md:79-83`).
- Testing: `claude plugin test` runs `*.test.ts` with stubs, no session, sign-in or network (`M/create.md:333-373`,
  `M/test.md`).
- Distribution is plugin distribution: send a directory/zip, a team marketplace, managed install, or public
  marketplace / Anthropic directory (`M/create.md:377-386`). Installed copies are cached by version, so a release needs
  a version bump (`M/create.md:386`, `M/troubleshoot.md:196-200`).

### Scope, enabling and trust

- On by default from 2.1.287 terminal / 2.1.286 Desktop (`M/overview.md:107`). Off switches: disable the plugin;
  `--safe-mode` per session; `disableAllHooks` in user settings stops user-installed mods, settings hooks and the custom
  status line together (`M/overview.md:112-120`, `D/settings-reference.md:4057-4064`). Built-in mods ignore these
  (`M/overview.md:248`).
- Anthropic can turn installed mods off remotely; no local setting overrides that (`M/troubleshoot.md:39,71`).
- Workspace trust prompt gates loading (`M/admin.md:91`).
- Organisation tiers: chain order is built-in guard `sec-default@builtin` + `prependPlugins` + other org mods, then
  user mods, then `appendPlugins`, then other built-ins (`M/events.md:295-304`). An "organisation mod" must be enabled by
  managed `enabledPlugins` AND come from a managed directory marketplace loaded in place; anything copied from
  GitHub/git/URL/npm counts as a user's (`M/admin.md:243-249,278`). Repositories can never set
  `prependPlugins`/`appendPlugins`; a user can only on a machine with no managed settings and no Team/Enterprise sign-in
  (`M/admin.md:316`, `M/reference.md:279`).
- Managed controls: `allowManagedModsOnly` (option on the built-in guard), `allowModsToOverrideDenyRules`,
  `allowManagedHooksOnly`, `disableAllHooks`, `disableSideloadFlags` (`M/admin.md:149-162,221-231`,
  `M/reference.md:275-285`). A policy mod can refuse other mods at `plugin.register` from their `uses` list, and
  intercept any `$` call by name (`fs.write`, `process.run`) (`M/admin.md:318-370`, `M/reference.md:150-153,169`).

### What a mod can do

- **Events** (`M/reference.md:54-169`): tools (`tool.call` incl. subagent and MCP calls, `tool.check`, `tool.describe`);
  prompts and what Claude reads (`prompt.submit`, `prompt.compose`/`prompt.section` for the system prompt,
  `prompt.context`, `prompt.attachment` for reminders, `skill.prompt`, `attribution.text`); commands and `/config`
  rows; turns (`turn.start`, `turn.step` per model request with model/effort override and usage, `turn.complete`);
  session (`start`, `end`, `compact` with veto, `receive`/`send` between sessions, `append` to rewrite stored rows,
  `measure` for plan-limit changes); subagents (`agent.offer` to withhold a type, `agent.spawn` to pick model or deny);
  interface (`ui.render` at 13 render sites, presses, input); other mods (`plugin.register`, `engine.create`); telemetry;
  every settings-hook event as `classic.<Event>`; and every `$` call as an event.
- **API** (`M/reference.md:175-197`): `$.ui` (panes, band above the prompt, toast, status line under the prompt, log,
  `ask` dialog), `$.command`/`$.tool`/`$.agent` register (tools appear as `mcp__<plugin>__<name>`, `M/api.md:53`),
  `$.model.complete`/`fork`/`classify` on the user's plan (`M/api.md:80-107`), `$.prompt.submit` (optionally as the
  user's own words), `$.session` (messages, usage with context % and rate limits, `compact`, `send`), `$.fs`,
  `$.process` (argv, no shell), `$.http.fetch`, `$.store` (machine-wide JSON KV, 4 MiB, not atomic across sessions),
  `$.state` (reactive per session), `$.clock` timers that run between turns (`M/api.md:111-128`), `$.mcp`, `$.audio`.
- **Commands** run a function at once with no Claude turn, even mid-turn with `immediate: true`
  (`M/overview.md:32`, `M/api.md:47`).
- **Where**: hooks run in the terminal, Desktop Code tab, VS Code chat, `claude -p`, Agent SDK, Remote Control and cloud
  sessions; drawing only in terminal and Desktop (`M/overview.md:201-213`).

### What it cannot do

- Cannot change the permission prompt (`M/overview.md:93`, `M/interface.md:302`).
- There is no render site for the settings `statusLine` itself; the nearest are `PromptHint`, `SessionMode`,
  `InfoNotice`, `Spinner` and the `AbovePrompt` band (`M/reference.md:203-217`). (Inference from the table; not stated.)
- Cannot override managed `PreToolUse` hooks; and where the built-in guard loads, cannot lift a `deny` rule
  (`M/admin.md:74-87`).
- Limits: 10 s own execution per hook (50 ms for `prompt.edit`), 1 s for `.catch`, `$.process.run` 30 s default /
  10 min max, 4 MiB file I/O, redraw throttles (`M/reference.md:250-269`).
- Not sandboxed in any way: it acts as the user (`M/overview.md:80-89`, `M/admin.md:94`).

### Lifecycle and versioning

Module-level variables reset on every reload; `$.state` survives reloads but not `/clear`/`/resume`/`/branch`;
`$.store` persists across sessions (`M/interface.md:706-716`, `M/troubleshoot.md:202-212`). `session.start` fires per
load and reload, not after `/clear` (`M/reference.md:115`). A failing hook is skipped (fail-open) unless it has a
`.catch` (`M/events.md:315-334`); a failed reload keeps the previous version (`M/troubleshoot.md:236`); a mod that
crashes the shared worker thread is unloaded, and three untraced crashes unload every non-built-in mod for the session
(`M/troubleshoot.md:136-146`, `M/admin.md:372`). The API "can change between releases" and authors should state the
tested version (`M/create.md:299,384`).

### Security and permission model (the part that matters to the daemon)

- A user mod's `tool.check` answers AFTER the permission rules and the non-managed `PreToolUse` hooks, and can replace
  their decision: approve an `ask`, approve a call a non-managed `PreToolUse` hook blocked, skip the auto-mode
  classifier, and, on a machine without managed settings or Team/Enterprise sign-in, approve a call a `deny` rule
  refuses (`D/permissions.md:572-577`, `M/events.md:189-210,313`, `M/admin.md:77`).
- A `tool.call` hook that answers without calling `next` stops the non-managed `PreToolUse` hooks from running at all
  (`M/events.md:308-311`, `M/admin.md:87`).
- The `classic.*` chain is "[managed settings hooks, ...hooks modules, the other settings hooks as core]" (`DTS:956-958`),
  so a mod on any `classic.<Event>` that does not call `next` suppresses every project/user settings hook for that event.
- A mod's own `$.fs`/`$.process` calls are not tool calls: no deny rule or `PreToolUse` hook sees them
  (`M/admin.md:76`, `D/plugins/security.md:48`).
- Rewriting a tool call's input happens before the non-managed `PreToolUse` hooks run, so those hooks judge the
  rewritten input (`M/events.md:311`); in auto mode a post-classifier rewrite is denied (`M/troubleshoot.md:152-156`).

### How mods relate to the other extension points

| Thing          | Relation (source)                                                                                                                                                                                                                           |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Settings hooks | Still supported, "Nothing about them is deprecated" (`M/admin.md:85`). Mods run in-process, can draw and add commands; settings hooks are scripts (`M/overview.md:223-229`). Mods can hook every settings-hook event as `classic.*`.        |
| Plugins        | A mod IS a plugin with a `modules` key (`D/plugins/overview.md:42`, `D/plugins/components.md:785`).                                                                                                                                         |
| Skills         | Text Claude reads; can ship in the same plugin; a mod can rewrite a skill's text (`skill.prompt`) (`M/reference.md:83`).                                                                                                                    |
| Agents         | A mod can register agent types, withhold offered ones, choose a subagent's model or refuse its spawn (`M/reference.md:127-130,181`).                                                                                                        |
| Output styles  | Not mentioned in any vendored mods page. The closest lever is `prompt.compose`/`prompt.section` over the system prompt (`M/reference.md:79-80`).                                                                                            |
| Settings       | A mod reads settings (`$.settings.read`) and `/config` rows, and can veto/rewrite a `/config` change (`M/reference.md:94-95,186-187`). It gets options from manifest `userConfig` via `pluginConfigs` (`M/reference.md:37,285`).            |
| MCP            | A mod can register tools Claude sees as `mcp__<plugin>__<name>` with no server process (`M/api.md:53-76`), call connected MCP tools, and defer any tool behind tool search via `tool.describe` (`M/reference.md:68`).                       |
| Status line    | The settings status line is a separate command; `disableAllHooks` stops both (`D/settings-reference.md:4037-4044`). A mod has `$.ui.status` (one line under the prompt) and `$.session.usage()` "as the status line has them" (`DTS:2430`). |

## Brainstorm against this repository

Repository context read: `CLAUDE.md`, `CLAUDE/ARCHITECTURE.md` (Overview, Configuration Locations, Security),
`CLAUDE/ClaudeCodePlugins.md`, `CLAUDE/development/CcySupervisor.md` (edit-to-live, usage pause, plugin API),
`CLAUDE/Architecture/StatusLine.md` headings, `CLAUDE/RemoteDocs.md`, and the plugin resolver
`src/claude_code_hooks_daemon/utils/claude_plugins.py`.

Class: **A** better served as a mod, **B** a mod that complements the daemon, **C** no fit, **D** daemon-side work
prompted by mods.

| #   | Area                                              | Class    | Gain / loss and grounding                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ------------------------------------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Guards (PreToolUse handlers) and the daemon core  | C        | Porting gains nothing a `tool.call` `{deny}` does not already give, and loses: Python codebase and tests, multi-language strategy registry, client trust. Mods can be switched off by an org's `allowManagedModsOnly`, by Anthropic remotely, by `--safe-mode`, and by three worker crashes (`M/admin.md:36-57`, `M/troubleshoot.md:39,144`), while settings hooks are not deprecated (`M/admin.md:85`). A user mod would also sit in the same overridable tier as any other user mod. Keep the daemon as settings hooks.                                                                                                                                                                                                                                            |
| 2   | Plugin awareness (`plugin_hooks_advisor`, health) | D        | The resolver treats a `hooks.json` without a `hooks` object as "not a hooks file" (`claude_plugins.py:634-640`), so a mod-only plugin is invisible to `plugin_hooks_advisor` and `hooks-daemon health`. Teach it the `modules` key; flag mods that hook `tool.check`, `tool.call`, `classic.*` or `prompt.submit`, using `claude plugin validate --json` (`hooks:`/`calls:`, `gatingHooks` per `D/changelog.md:38`) rather than parsing JS. Also covers `~/.claude/dev-mods/` and `--plugin-dir`, which the resolver reports unresolved today (`CLAUDE/ClaudeCodePlugins.md:179-180`).                                                                                                                                                                               |
| 3   | Plugin coexistence docs                           | D        | `CLAUDE/ClaudeCodePlugins.md:111` says "a daemon deny always wins: no plugin hook can overrule it". That is now false for mods: `tool.check` can approve a call the daemon's project `PreToolUse` hook denied, and a `tool.call`/`classic.*` answer can stop the daemon running (`D/permissions.md:575`, `M/events.md:311`, `DTS:956-958`). Same for `CLAUDE/ARCHITECTURE.md:897-905`. Cheap, should be done regardless.                                                                                                                                                                                                                                                                                                                                             |
| 4   | ccy supervisor injection decisions                | A (part) | The supervisor types `/compact`, `continue`, `/goal`, `/model` through a PTY and infers state from keystrokes and daemon signal files (`CLAUDE/development/CcySupervisor.md:26-63`). A mod has direct, typed equivalents: `$.session.compact()` (`DTS:2460-2468`), `$.prompt.submit` that waits for idle (`M/api.md:142`), `turn.step` `next({...e, model})` for model restore and `result.usage.model` for exact fallback detection (`M/events.md:247,268`), `prompt.submit` origin `composer` vs `scheduled-trigger` for exact recognition of what the human did (`DTS:7028-7067`), `$.session.usage()` for context/rate limits. Loss: still needs the container-level restart, so ccy stays for that; mods can be disabled under it. Highest value, highest cost. |
| 5   | Crons, failsafe ticks, usage pause                | B        | Ticks are currently recognised by a `[tick:...]` text first line and suppressed via hooks (CLAUDE.md hooksdaemon block). `prompt.submit` gives a closed-set `origin.kind` "never a text prefix" with `scheduled-trigger` for scheduled tasks and `/loop` (`DTS:7028-7067`), and can `{drop}` it at zero model cost (`M/reference.md:76`). A usage pause could watch `session.measure` and `$.session.usage().rateLimits` and resume at `resetsAt` with `$.clock.after` + `$.prompt.submit`, replacing the "one resume cron" dance (`M/reference.md:121,185`, `M/api.md:111-142`). Timers die on module reload and with the session (`M/api.md:146`), so the daemon's persistence must remain the source of truth.                                                    |
| 6   | Status line / operator visibility                 | B        | Keep the settings status line (works with mods off; mods disabled by `allowManagedModsOnly` would blank a mod one). Add an optional band/pane: daemon health, recent denies/advisories, active plan, crons, with buttons (`M/interface.md:196-218`, `M/api.md:130-138`). Medium value; the human-facing advisories that today cost agent context could go to `$.ui.toast`/`$.ui.status` instead.                                                                                                                                                                                                                                                                                                                                                                     |
| 7   | Policy mod protecting the daemon's verdicts       | B        | On an unmanaged single-user machine a user can list a mod in `prependPlugins` (`M/admin.md:316`); a daemon-companion mod there could refuse at `plugin.register` any other user mod that hooks `tool.check` or `classic.*`, and fail closed with `.catch` (`M/admin.md:318-403`). Not available where managed settings exist (then it is the org's job). Medium value, medium cost; overlaps #2.                                                                                                                                                                                                                                                                                                                                                                     |
| 8   | Remote docs routing                               | B        | `remote_docs_routing` denies a `WebFetch` and points at the copy. A mod can answer `tool.call` for `WebFetch` with `{ result: <vendored body> }`, saving a turn (`M/events.md:144`). Low-medium value; note this also skips all non-managed PreToolUse hooks for that call.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| 9   | Plan workflow                                     | B        | A `/plan-new` command with `immediate: true` running `mkplan.bash` via `$.process.run`, and a plan pane listing live plans and their status (`M/api.md:27-47`). Convenience only; low value.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 10  | Tool disable advisor / tool listing cost          | B        | `tool.describe` can defer a tool behind tool search and `agent.offer` can withhold a subagent type (`M/reference.md:68,129`), so "never-want" tools could be enforced rather than advised. Low-medium.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 11  | Model fallback / downgrade detection              | B        | `turn.step` result carries the answering `model` per request, and `serverToolUses` since 2.1.290 (`M/events.md:268`, `D/changelog.md:34`). Exact where the daemon infers. Folds into #4.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| 12  | Subagent report persistence / dispatch rules      | C        | Already covered by `SubagentStop`/`PreToolUse` on Agent; `turn.complete`/`agent.spawn` offer nothing the daemon needs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| 13  | QA pipeline                                       | C        | `claude plugin test` tests mods only; the daemon's QA is Python. Relevant only to whatever mod gets built.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| 14  | Content guards on Bash-authored files             | C        | A mod's `$.fs` writes bypass every guard too (`M/admin.md:76`); nothing to gain.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

### Distribution note for any mod this repo ships

The daemon installs per project from a git clone; a mod installs as a plugin from a marketplace. This repository could
host its own marketplace and register it in a client's `.claude/settings.json`, which reaches collaborators behind
the trust gate (`M/create.md:380`, `CLAUDE/ClaudeCodePlugins.md:38-55`). Such a mod counts as a user's, never as an
organisation's (`M/admin.md:278`), so enterprise clients with `allowManagedModsOnly` will not load it. Any mod must
therefore be optional, degrade to nothing, and never be the only enforcement path.

Developing one inside this repo: the `plugin-authoring` skill writes to `~/.claude/dev-mods/` (`M/create.md:43`),
which the daemon's `project_containment` denies (R-WRITE-OUTSIDE-PROJECT-ROOT). Use an in-repo directory with
`--plugin-dir` instead.

## Risks

1. **A user-installed mod can overrule a daemon deny.** `tool.check` replaces the decision of non-managed `PreToolUse`
   hooks; on this machine (no file-based managed settings found at `/etc/claude-code/managed-settings.json`) it can even
   lift deny rules unless the user is on Team/Enterprise (`D/permissions.md:572-577`).
2. **A mod can stop the daemon's hooks running.** Answering `tool.call` without `next` skips non-managed `PreToolUse`
   hooks (`M/events.md:311`); not calling `next` on `classic.<Event>` skips the daemon on any event, Stop included
   (`DTS:956-958`).
3. **Invisible side effects.** `$.fs`/`$.process`/`$.http` calls never pass the daemon (`M/admin.md:76,88`).
4. **Blind spot in the daemon's plugin support.** Mod-only plugins are filtered out by the resolver
   (`claude_plugins.py:634-640`), so `plugin_hooks_advisor` stays silent about exactly the plugins with most power.
5. **Stale canonical doc.** `CLAUDE/ClaudeCodePlugins.md:111` and `CLAUDE/ARCHITECTURE.md:897-905` state a guarantee
   mods break.
6. **Upstream churn.** Five days old, EARLY ACCESS in the types (`DTS:14`), many fixes per release
   (`D/changelog.md:34-88`); anything built now carries a maintenance cost.
7. **Mods do not conflict with the daemon by default.** None ships enabled here except built-ins; only
   `cc-plugin-you-should-know` (disabled by default) runs a side model agent (`M/overview.md:246`).

## Recommended shortlist (value vs cost, highest first)

1. **Mod awareness in the daemon (#2 + #3)**: high value, low cost, no mod to build. Read `modules`, flag gating hooks
   (`tool.check`, `tool.call`, `classic.*`, `prompt.submit`, `session.append`), list mods in `health`, and correct
   `ClaudeCodePlugins.md` / `ARCHITECTURE.md`. Optionally a SessionStart advisory when a mod hooks `tool.check`.
2. **Session-resilience companion mod (#5, with #11)**: high value, medium cost. Exact cron-tick recognition by
   `origin.kind`, zero-cost drop while blocked on a human, usage-pause resume by timer, exact model-fallback reading.
   Optional, daemon state stays authoritative.
3. **Move the ccy supervisor's in-session decisions into a mod (#4)**: very high value, high cost; a design spike first
   (does `$.session.compact`, `$.prompt.submit` and `turn.step` model override cover every injection family?). ccy keeps
   the container restart and the fallback when mods are off.
4. **Operator band/pane (#6)**: medium value, medium cost; good first mod for learning the surface with no enforcement
   risk.
5. **Prepend policy mod (#7)**: medium value, only for unmanaged machines; consider after #1 shows how common
   gating mods are.

Not recommended: porting guards or the daemon core to mods (#1), QA (#13).

## Open questions for the owner

1. Should the daemon treat a mod hooking `tool.check` or `classic.*` as an advisory (like plugin `PreToolUse` hooks
   today) or as something stronger, given it can overrule or silence the daemon?
2. Is shipping a mod at all acceptable, given it would install from a marketplace this repo hosts, count as a user mod,
   and be absent for enterprise clients with `allowManagedModsOnly`?
3. For #3: is moving ccy's injection logic into a JavaScript mod acceptable, given the supervisor is Python and the
   mods API is early access?
4. Unknown from the docs: whether `$.prompt.submit` or `$.command.run` can invoke built-in slash commands such as
   `/model` or `/goal` (only `$.session.compact` is documented as "the same call `/compact` makes", `DTS:2460`).
5. Unknown: whether a session cron created by `CronCreate` arrives as `scheduled-trigger` (the types say "A scheduled
   task, routine or /loop", `DTS:7065`). Needs a live probe before #2 of the shortlist relies on it.
6. Licence for `code.claude.com` and the GitHub captures is recorded `unreviewed`; declare it once under
   `documentation.remote.known_sources` if the review gets quoted outside the repo.
