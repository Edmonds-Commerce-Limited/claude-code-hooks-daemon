# Plan 00494: the single hooks-daemon mod, a design proposal (Opus)

Follows [261006-mods-review-opus.md](261006-mods-review-opus.md) and the owner's rulings in
[OWNER-RULINGS-261006.md § A2](../../00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md#a2-mods-plan-00494).
Research and design only; nothing under `src/` changed.

## Citation shorthand

Same as the review, plus three newly vendored pages.

| Short   | File                                                                                                      |
| ------- | --------------------------------------------------------------------------------------------------------- |
| `M/x:N` | `remote-docs/code.claude.com/docs/en/plugins/mods/x.md` line N                                            |
| `P/x:N` | `remote-docs/code.claude.com/docs/en/plugins/x.md` line N                                                 |
| `D/x:N` | `remote-docs/code.claude.com/docs/en/x.md` line N                                                         |
| `DTS:N` | `remote-docs/raw.githubusercontent.com/anthropics/claude-code/main/mods/types/claude-code.d.ts.md` line N |

New captures for this report, all through `bin/hooks-daemon remote-docs add`, none refused:

- `P/cli-reference` = https://code.claude.com/docs/en/plugins/cli-reference (`claude plugin list --json`, `update`,
  `validate --json`, `/reload-plugins`)
- `P/install` = https://code.claude.com/docs/en/plugins/install (scopes, "Keep plugins updated")
- `P/marketplace-reference` = https://code.claude.com/docs/en/plugins/marketplace-reference (source types)

Read-only check on this machine: `claude --version` prints `2.1.291`; `claude plugin list --json` lists two plugins
(`defence-before-fix@defence-before-fix` project scope, `pyright-lsp@claude-plugins-official` user scope), no mod.

## Owner rulings this design follows

1. **One mod.** One plugin, named `hooks-daemon`, holding every feature behind an internal feature registry, the way
   the `hooks-daemon` skill holds several sub-guides. Never a second mod.
2. **Mods are not for protection.** The mod never answers `tool.call` or `tool.check`, never touches `classic.*`, and
   nothing protective depends on it. Every feature degrades to today's behaviour when the mod is absent.
3. **ccy supervisor stays out.** Nothing here moves supervisor logic into the mod.
4. **Mod awareness is approved daemon work.** Spec in [Part 5](#part-5-daemon-mod-awareness-approved-item-i).

---

## Part 1: how mods are installed and updated (the owner's question)

### 1.1 What the docs settle

**A mod is installed and updated as a plugin, with no mod-specific mechanism.** "A mod installs as a plugin, from a
marketplace"; install, scopes and "keeping plugins updated" "apply to a plugin that contains a mod without changes"
(`M/overview:51-56`). A shell install or update while a session is open needs `/reload-plugins` in that session
(`M/overview:58`).

**How Claude Code decides there is an update.** It computes a version per plugin. The manifest `version` comes first,
then the marketplace entry's `version`, then a source-derived value: a 12-character commit SHA for `github`/`url`/
`git-subdir`, `unknown` for a local directory that is not a git repository (`P/loading:290-306`). Updates compare that
value with `installed_plugins.json` and do nothing when it matches (`P/loading:282`). A manifest that pins
`"version": "1.0.0"` "keeps every user on the cached copy until its author changes the string, however many commits
they push" (`P/loading:310`, `P/manifest-reference:196-198`). A marketplace copy is cached under
`cache/<marketplace>/<plugin>/<version>/`, so a release must change the version (`P/loading:179,197`,
`M/create:386`).

**Who triggers an update.**

| Trigger                        | Behaviour                                                                                                                                                                                                                                                                               | Source                                         |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Background auto-update         | Interactive sessions only, after the first message plus a random delay of up to ten minutes; refreshes marketplaces with auto-update on and updates their plugins on disk. The running session keeps what it loaded and prints `Plugin updated: <name> · Run /reload-plugins to apply`. | `P/loading:336-338`, `P/install:351-355`       |
| Which marketplaces auto-update | `autoUpdate` on the `extraKnownMarketplaces` entry, else the `/plugin` toggle, else the default: on for official Anthropic marketplaces, **off for every third-party marketplace** (ours would be third-party).                                                                         | `P/loading:342-346`, `P/install:357-360`       |
| Kill switches                  | `DISABLE_UPDATES`, `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` turn the pass off unless `FORCE_AUTOUPDATE_PLUGINS=1`; managed settings can lock `autoUpdate` per marketplace.                                                                                     | `P/loading:348`, `P/org:326-345`               |
| Explicit                       | `claude plugin update <plugin>@<marketplace>` (loads next session or after `/reload-plugins`); no "update everything" command.                                                                                                                                                          | `P/cli-reference:249-251`, `P/install:368-374` |

**Project scope does not distribute the files.** A plugin enabled in a committed `.claude/settings.json` from an
external source is not downloaded for collaborators; each must run
`claude plugin install <name>@<marketplace> --scope project` (`P/install:153`, `P/loading:160-171`,
`D/settings-reference:4662`). The exceptions are a **relative-path plugin inside a marketplace** and a seed directory
(`P/loading:162-164`, `P/org:102`).

**Three origins load in place, with no version check at all** (`P/loading:190-197,288`):

1. `--plugin-dir` / `--plugin-url` / `CLAUDE_CODE_PLUGIN_DIRS` (`@inline`, session-only);
2. **skills-directory plugins**: a directory with `.claude-plugin/plugin.json` under `~/.claude/skills/` or the
   project's `.claude/skills/` (`@skills-dir`) (`P/loading:63,79`);
3. a relative-path plugin in a marketplace added from a local path, which "loads its current source files at every
   session start, whatever its version string says" (`P/loading:288`).

A repository shares a plugin by "list[ing] it under `enabledPlugins` in `.claude/settings.json` or plac[ing] it under
`.claude/skills/`" (`P/loading:79`). A project skills-directory plugin loads only from the session's primary working
directory and only after the workspace trust dialog (`P/loading:83-85`).

**What the daemon can read back.** `claude plugin list --json` reports every plugin, including skills-directory ones,
with `id` (`name@skills-dir`), `version` (the manifest's, for skills-dir/inline/synced), `scope`, `enabled`,
`installPath`, `errors`, `notes`; since 2.1.289 `readFromFolder`/`folderVersion` for in-place marketplace plugins
(`P/cli-reference:302-333`). `installed_plugins.json` and `known_marketplaces.json` hold the on-disk records
(`P/loading:41-42`).

**Name collisions decide which copy runs.** Precedence by manifest name: managed-enabled id, then `--plugin-dir`, then
an installed marketplace plugin, then a skills-directory plugin, then synced (`P/loading:368-380`). An installed
marketplace copy named `hooks-daemon` would silently shadow a project's `.claude/skills/` copy.

**Policy that stops a user mod** (ours always counts as a user's unless an organisation deploys it, `M/admin:278`):

| Control                                                         | Effect on our mod                                                     | Source                                        |
| --------------------------------------------------------------- | --------------------------------------------------------------------- | --------------------------------------------- |
| `allowManagedModsOnly` (guard option, managed)                  | Does not load                                                         | `M/admin:36-57`, `M/reference:280`            |
| `allowManagedHooksOnly`, managed `disableAllHooks`              | Does not load (the daemon's settings hooks stop too under the second) | `M/reference:282-283`, `M/troubleshoot:72-73` |
| User `disableAllHooks`                                          | Does not load; also stops the daemon's settings hooks and status line | `M/overview:116`                              |
| `strictKnownMarketplaces` set without `{"source":"skills-dir"}` | Skills-directory plugins stop loading                                 | `P/org:246-248`, `D/settings-reference:4469`  |
| `--safe-mode`, `--bare`                                         | Does not load                                                         | `M/overview:115`, `M/troubleshoot:74`         |
| Anthropic remote switch                                         | Installed mods off, no local override                                 | `M/troubleshoot:39,71`                        |
| Untrusted folder                                                | Nothing loads until the trust prompt is accepted                      | `M/admin:91`, `M/troubleshoot:105-109`        |

`claude plugin test`, run in a directory without a mod, prints whether mods can load here at all (`no hooks module to load` / `hooks modules are turned off here` / `... in this process`), but not `allowManagedModsOnly`
(`M/troubleshoot:33-41`).

**The enterprise route exists.** An organisation can make our mod "its own": managed `enabledPlugins`, a managed
`directory` marketplace at an absolute path, the plugin listed by relative path and loaded in place
(`M/admin:243-249`). It then loads under `allowManagedModsOnly`.

### 1.2 The answer: ship the mod inside the daemon, deploy it as a project skills-directory plugin

The daemon is already per project, and different projects on one machine can run different daemon versions. A mod
installed from a marketplace is per machine (user scope) or needs a per-collaborator install (project scope), and
updates on its own clock, off by default for third-party marketplaces. Matching a per-project daemon version through a
marketplace is the wrong shape.

The skills-directory origin fits exactly:

- `hooks-daemon install` and `hooks-daemon upgrade` copy the mod from the daemon's own source into
  `<project>/.claude/skills/hooks-daemon-mod/`, using the same deploy-and-compare machinery that already places the
  skills there (`src/claude_code_hooks_daemon/install/skills.py`, `deploy_skills`, `_trees_match`). The copy's
  `plugin.json` carries `"version": "<daemon version>"`.
- It loads in place, so **the mod version equals the deployed daemon version by construction**: no marketplace, no
  `claude plugin install`, no `claude plugin update`, no auto-update settings, nothing extra to install. "Only one thing
  to install" holds: installing the daemon installs the mod.
- It is project-scoped and per checkout, so two projects on one machine each run their own matching mod; a git worktree
  carries its own copy.
- `claude plugin list --json` reports it as `hooks-daemon@skills-dir` with the manifest version
  (`P/cli-reference:317-319`), so the daemon can verify from outside a session what Claude Code sees.

**How a project ends up on the right version.**

1. `hooks-daemon upgrade` moves the daemon and re-deploys the mod copy in the same step. This is the "perform the
   upgrade" path the owner asked about; it needs no Claude Code command.
2. A running session keeps the module it loaded. The upgrade output and the next SessionStart say: run
   `/reload-plugins`, or start a new session. Whether a skills-directory mod also hot-reloads when its files change is
   **UNKNOWN** (probe U1).
3. The mod reports the version it is running in its handshake ([§2.4](#24-versioning-and-the-compatibility-handshake)),
   so the daemon knows when a live session still runs an old module, and says so in `health` and the status line.
4. Collaborators get the matching mod when they pull the commit that updated the daemon config and `.claude/skills/`
   (if the project commits `.claude/skills/`, as it does for the skills today). On a clone where the daemon is not
   installed, the mod finds no daemon and stays silent ([§2.5](#25-failure-behaviour)).

**How the daemon helps beyond that.**

| Situation                                                                   | Daemon response                                                                                                                                                                     |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deployed copy differs from the shipped tree (hand-edited or stale)          | `health` FAIL naming the files; `upgrade` preserves the edited copy aside, as `_preserve_replaced_skill` already does for skills, and redeploys.                                    |
| A marketplace, `--plugin-dir` or managed plugin named `hooks-daemon` exists | Loud advisory: it shadows the project copy (`P/loading:368-380`). Gives the exact `enabledPlugins` `false` entry or `claude plugin disable` command.                                |
| Live session's handshake version older than the deployed copy               | Status-line segment and SessionStart line: "mod vX loaded, vY deployed: run /reload-plugins".                                                                                       |
| Mods cannot load here (`claude plugin test` state, a policy above)          | `health` reports "mod: unavailable (<reason>)" as INFO, not a failure: the daemon works without it.                                                                                 |
| An allowlist without `skills-dir`                                           | `health` names the policy and the managed entry an admin would add (`P/org:246-248`).                                                                                               |
| Enterprise wants it under `allowManagedModsOnly`                            | Documented recipe: deploy the daemon's mod directory as a managed `directory` marketplace (`M/admin:243-262`). The daemon recognises that origin and does not deploy a second copy. |

**Routes considered and not recommended.**

| Route                                                                                                              | Why not                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Public marketplace in this repository, user-scope install                                                          | One version per machine against many daemon versions; third-party auto-update is off by default (`P/install:357-360`); updates need `claude plugin update`, which the daemon could only advise (it changes every project on the machine). Wide cross-version compatibility becomes mandatory. Keep as a documented fallback only.                                           |
| `extraKnownMarketplaces` in the project's settings with a `directory` source pointing into `.claude/hooks-daemon/` | Also loads in place (`P/loading:288`), relative paths resolve against the main checkout (`P/org:104`). But the clone is gitignored, so a collaborator without the daemon gets an Errors-tab row, and `known_marketplaces.json` is one per user (`P/loading:41`): two projects declaring the same marketplace name with different paths is **UNKNOWN** behaviour (probe U4). |
| `CLAUDE_CODE_PLUGIN_DIRS` / `--plugin-dir`                                                                         | Session-only and set by whoever launches Claude Code (`M/reference:277`); refused by `disableSideloadFlags`. Right for developing the mod in this repository, wrong for clients.                                                                                                                                                                                            |

### 1.3 What the docs do not settle

| #   | Question                                                                                                                                                                                                                                                                                                         | Live probe that settles it                                                                                                                                                                                                                                              |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| U1  | Does a project `.claude/skills/<dir>` plugin's `hooks/hooks.json` `modules` load (the docs state the origin and in-place loading, and say Claude-written mods need `skills-dir` under an allowlist, `M/admin:105`, but never show a skills-dir mod)? Does it hot-reload on change, or only at `/reload-plugins`? | Put a two-hook mod (`session.start` toast, `command.run` for `/hdprobe`) in a scratch project's `.claude/skills/probe-mod/`; start `claude`, accept trust, check `/plugin` for `1 mod active`; edit the toast text; check whether it changes without `/reload-plugins`. |
| U2  | Does `/reload-plugins` warn about prompt-cache invalidation when only a mod (no MCP server) changes? (`P/cli-reference:848` names MCP tools and LSP only.)                                                                                                                                                       | Same scratch mod; change one hook; run `/reload-plugins`; record the message.                                                                                                                                                                                           |
| U3  | Is a skills-directory plugin listed by `claude plugin list --json` with `errors` when its module fails to load?                                                                                                                                                                                                  | Break the scratch module's syntax; run `claude plugin list --json`.                                                                                                                                                                                                     |
| U4  | Two projects declaring one marketplace name with different `directory` paths: which wins, and does switching projects re-fetch?                                                                                                                                                                                  | Only needed if route 2 is ever chosen; two scratch projects, alternate sessions, read `known_marketplaces.json`.                                                                                                                                                        |
| U5  | Does an agent's Bash `claude plugin list --json` inside a session reflect the session's loaded state or only disk and settings?                                                                                                                                                                                  | Run it from inside a session with the scratch mod loaded and compare with `/plugin`.                                                                                                                                                                                    |

---

## Part 2: architecture of the single mod

### 2.1 Packaging

Source lives in this repository beside the skills it resembles:

```text
src/claude_code_hooks_daemon/mod/hooks-daemon/
├── .claude-plugin/plugin.json      name "hooks-daemon", version stamped at deploy, "types"
├── hooks/hooks.json                {"modules": ["./register.js"]}   (no "hooks" key)
├── hooks/register.js               static imports; calls each feature's install(on, ctx)
├── hooks/core/bridge.js            locate daemon, handshake, read runtime files, run CLI
├── hooks/core/features.js          the registry: id -> { install, protocolMin }
├── hooks/features/status.js        daemon presence band/status line
├── hooks/features/human-queue.js   Part 3a
├── hooks/features/session-messages.js  Part 3b
├── hooks/features/resilience.js    Part 3c (off until the owner rules)
├── types/index.d.ts                PluginState declarations
└── **/*.test.ts                    `claude plugin test`
```

Deployed to `<project>/.claude/skills/hooks-daemon-mod/`. The name must not start with `claude-` (`M/create:384`).
`userConfig` is not used: Claude Code ignores project and local `pluginConfigs` (`D/settings-reference:4788`), so all
configuration comes from `.claude/hooks-daemon.yaml` through the daemon.

Static analysis constraints shape the registry (`M/create:324-331`, `M/admin:127`): every `on('<event>', ...)` uses a
string literal, every `$` call is written in full, imports stay inside the plugin. So `register.js` registers **every
hook of every feature unconditionally**, and each hook returns `next(e)` at once when its feature is disabled. The
`hooks:`/`calls:` lines that `claude plugin validate` prints are therefore the full, reviewable surface of the mod, the
same for every project.

In this repository (self-install), development uses `claude --plugin-dir src/claude_code_hooks_daemon/mod/hooks-daemon`
with hot reload (`M/create:212-265`), not the `plugin-authoring` skill, whose `~/.claude/dev-mods/` target is outside
the project and denied here (`M/create:43`, R-WRITE-OUTSIDE-PROJECT-ROOT).

### 2.2 How the mod talks to the daemon

The daemon listens only on Unix sockets (`daemon/server.py`, `asyncio.start_unix_server`). A mod has no socket API:
only `$.fs`, `$.process`, and `$.http.fetch` over `http`/`https` (`M/api:180-197`). Adding a TCP listener to the
daemon would widen its attack surface for no gain. So:

| Direction              | Channel                                                                                                                                                                                                                                                    | Why                                                                                                                                                                                                                                                  |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| daemon → mod           | **JSON files** in the daemon's untracked state directory, `<daemon root>/untracked/mod/` (written with temp-file-and-rename by Python, so a reader never sees half a file). The mod polls with `$.fs.stat` on a `$.clock.every` timer and reads on change. | Works when the daemon process is down; cheap; inspectable; matches the daemon's existing signal-file style (awaiting-human marker, usage-pause record).                                                                                              |
| mod → daemon           | **The daemon CLI** via `$.process.run([<bin>/hooks-daemon, 'mod', <verb>, '--json', ...])`, argument list, no shell (`M/api:197`).                                                                                                                         | Python does the locking and atomic writes; the mod never writes daemon state with the non-atomic `$.fs.write` (`M/reference:189`). Used only for rare, human-paced actions (hello, a reply, a tick-off), so the CLI's start-up cost does not matter. |
| mod → daemon, hot path | Small per-session witness files written with `$.fs.write` (Part 3c only), one file per fact, read by daemon hooks that treat an unparseable file as absent.                                                                                                | A `$.process.run` per prompt would be too slow; a torn write fails safe to today's behaviour.                                                                                                                                                        |

The binary is located from `$.session.root()`: `<root>/.claude/hooks-daemon/bin/hooks-daemon` for a client,
`<root>/bin/hooks-daemon` for self-install, the same two layouts `install/bin_wrapper.py` deploys.

The mod never uses `$.store` for daemon state: it is machine-wide, shared by every project, capped at 4 MiB and not
atomic across sessions (`M/reference:190,263`, `M/interface:823-830`). Per-project state belongs to the daemon.

### 2.3 Feature registry

`hooks/core/features.js` is a static table; the daemon decides which entries are on.

```yaml
# .claude/hooks-daemon.yaml (proposed)
mod:
  enabled: true            # false: the daemon stops deploying the copy and removes a daemon-deployed one
  features:
    status: true
    human_queue: true
    session_messages: true
    resilience: false      # owner: "maybe"
```

At `session.start` the mod calls `hooks-daemon mod hello` and receives the effective feature set. Until the reply
arrives, every feature is off. A feature the daemon does not name is off, so an older daemon never sees a newer mod
switch something on.

### 2.4 Versioning and the compatibility handshake

- `plugin.json` `version` = the daemon version that deployed it (observability, `P/cli-reference:318`).
- `hooks/core/protocol.js` exports `MOD_PROTOCOL = <integer>`, bumped only when the file or CLI contract changes.
  (A custom manifest field would be stripped with a validator warning, `P/manifest-reference:120`.)
- `session.start` → `hooks-daemon mod hello --json --session <$.session.id()> --mod-version V --protocol N --cc-version <$.session.version().version> --surface <terminal|desktop|none>` (`DTS:2457`).
- Reply: `{ "ok": true, "daemon_version": "...", "protocol": {"min": 1, "max": 1}, "features": {...}, "state_dir": "...", "notices": [...] }`. The daemon writes `untracked/mod/presence/<session>.json` with what the mod
  reported, which is what `health` and the status line read.
- Outcomes: protocol in range → run the enabled features. Out of range → only `status` runs, showing
  `hooks-daemon mod vX does not match daemon vY: run /reload-plugins or hooks-daemon upgrade` with `$.ui.status`
  (`M/api:136`). No reply → [§2.5](#25-failure-behaviour).
- `/clear`, `/resume` and `/branch` keep the module loaded, so the handshake need not repeat, but they reset `$.state`
  (`M/interface:793`). The documented fix is a `classic.SessionStart` hook; the mod does not use it, because Part 5
  classes every `classic.*` hook as able to silence the daemon. Panes re-read their files on the poll timer instead,
  which survives `/clear` because module timers stop only on reload (`M/api:146`). The session id may change across
  these commands, so the timer also re-reads `$.session.id()` and re-sends `hello` when it changes.

### 2.5 Failure behaviour

| Condition                                      | Mod behaviour                                                                                                                               | Daemon behaviour                                             |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| No daemon install found under the session root | Every feature off, no UI at all (a collaborator without the daemon sees nothing).                                                           | n/a                                                          |
| CLI present, hello fails or times out          | `status` shows `hooks-daemon: not responding`; other features read files read-only and mark actions unavailable. Retries on the poll timer. | Unchanged; hooks fail as they do today.                      |
| Daemon process down, files present             | Band line `hooks daemon not running: hook protections are off` (a loud, human-facing restatement of what the status line shows).            | Unchanged.                                                   |
| A hook throws                                  | Skipped, fail open (`M/events:317-322`). No mod hook can block anything, so fail-open is always safe.                                       | Unchanged.                                                   |
| Mod crashes the hooks worker                   | Claude Code unloads it; three untraced crashes unload every non-built-in mod (`M/troubleshoot:136-146`).                                    | Presence file goes stale; `health` reports the mod not live. |
| Headless (`-p`, SDK, VS Code chat panel)       | Hooks run, nothing draws (`M/overview:199-213`); `$.ui.ask` rejects in `-p` (`DTS:2136`). UI features stay off when `surface` is none.      | Unchanged.                                                   |

### 2.6 When mods are disabled

Everything degrades to today because **the daemon never depends on the mod**:

- Every daemon output that reaches the agent today keeps reaching it through hooks unless the mod's presence for this
  very session is confirmed ([§3b](#3b-sessionstart-messages-through-the-mod)).
- Every mod action has a CLI twin (`hooks-daemon human ...`, `hooks-daemon messages ...`), so a human without the mod
  does the same thing in a terminal.
- Every resilience input from the mod is an *additional, positive* signal; its absence leaves the daemon's existing
  sentinel, cron and snapshot logic exactly as it is.

---

## Part 3: feature designs

### 3a. Human to-do and question list

**Problem.** Agents' asks to the human ("please run X", "which of A or B?") scroll away. Today the daemon has three
partial mechanisms: the `[awaiting-human]` stop marker (`handlers/stop/auto_continue_stop.py`, consumed by
`failsafe_cron_blockage_suppressor.py`), the stand-in cron, and `hooks-daemon session-actions`, which is the
**agent's** must-do list (`utils/session_action_items.py`). None records what the human is being asked.

**What the mod API offers.**

| Need                                           | API                                                                                                                  | Cite                                         |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| Sidebar list with buttons                      | A `Pane` (sidebar beside the transcript in a wide terminal, framed above the prompt otherwise), `Button`, `Markdown` | `M/interface:203-208`, `M/reference:235-242` |
| Typed reply                                    | `Input` with `onSubmit(value)`; `Select` for offered options                                                         | `M/interface:547-641`, `M/reference:241-242` |
| Always-visible count                           | The `AbovePrompt` band (shared with other mods), or `$.ui.status`                                                    | `M/interface:211-217`, `M/api:136`           |
| Open on demand, even mid-turn                  | `$.command.register({ name, immediate: true })` + `$.ui.open`                                                        | `M/api:47`, `M/interface:340`                |
| Open by itself without stealing a small screen | Auto-opened panes appear only from 144 columns (110 once opened by the user); `$.ui.toast` otherwise                 | `M/interface:342-349`                        |
| Wake the session with the answer               | `$.prompt.submit({ text })`, read "after a sentence that names your mod as the sender", waits for idle               | `M/api:142`, `DTS:2505-2515`                 |
| Reach another live session                     | `$.session.send({ to: { sessionId }, text })`                                                                        | `M/api:150`                                  |

**UX sketch.**

```text
band:  ⧗ hooks-daemon: 2 questions, 3 tasks for you   (/human)
╭ Human ─────────────────────────────────────────────────────────────╮
│ Questions (2)  Tasks (3)  Done                                     │
│ Q-0007  blocking · session 3f2a · Plan 00494 · asked 12 min ago    │
│   Ship the mod as a skills-dir plugin (A) or a marketplace (B)?    │
│   [ A ] [ B ]   Reply: ____________________________ ⏎ send         │
│ T-0012  run in your terminal:                                      │
│   hooks-daemon approve-upgrade 3.69.0 --from 3.68.2                │
│   [ ✓ done ] [ won't do ] [ copy ]                                 │
╰────────────────────────────────────────────────────────────────────╯
```

**Daemon side (works with no mod).**

- Store: `<daemon root>/untracked/human-queue/`, one JSON file per item plus an index, written by Python with a lock and
  atomic rename. Item: `id`, `kind` (`question`|`task`), `text`, `options[]`, `blocking`, `session_id`, `plan`,
  `created_at`, `status` (`open`|`answered`|`done`|`dismissed`), `answer`, `answered_via` (`mod-pane`|`cli`),
  `delivered_at`.
- CLI: `hooks-daemon human ask [--blocking] [--option X]... "<text>"`, `human task "<text>" [--command "<cmd>"]`,
  `human list [--json]`, `human reply <id> "<text>"`, `human done <id>`, `human dismiss <id>`. Agents post with Bash,
  so the same path works whether or not the mod is loaded, and no `mcp__` tool is added to every turn's tool list. (A
  registered tool would also need a `tool.call` hook, which Part 5 classes as overriding.)
- Delivery of an answer: the mod, after `human reply` succeeds, calls `$.prompt.submit({ text: "Human reply to Q-0007: <answer>" })`. The daemon's `UserPromptSubmit` handler recognises the `Q-` id, checks the item is `answered` with
  that text, and adds `additionalContext`: "Verified: Q-0007 was answered by the human through the hooks-daemon panel."
  A prompt that claims an id with no matching record gets no such line, so another mod's `asUser` text cannot pass as
  a verified answer.
- If the asking session is not live, the answer waits: the next SessionStart for that project lists answered,
  undelivered items, then marks them delivered.
- Without the mod: the status line shows the open count; SessionStart lists open items (as `systemMessage` for the
  human, `D/hooks:756`); the human uses `hooks-daemon human reply`.

**Relation to existing mechanisms.**

| Mechanism               | Change                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `[awaiting-human]` stop | The stop handler asks for a question id in the stop message (or posts the stop's question itself as a `blocking` item). A reply is a non-tick prompt, so it clears the marker exactly as a typed answer does today; `human reply` also clears it directly for that session, so the stand-in cron finds no live marker. |
| Stand-in cron           | Its ruling is posted as an `answered` item marked `answered_via: stand-in`, so the human sees what was decided in their name and can reply to overrule it.                                                                                                                                                             |
| Session actions         | Unchanged: they are the agent's list. Steps a guard reserves for the human ("ask the user to run it manually": `git reset --hard`, `approve-upgrade`, unmerged branch deletes) get a `human task` posted with the exact command, instead of a sentence in scrollback.                                                  |

**Open questions.** Should a `blocking` question also trigger `$.ui.toast` and a sound (`$.audio`)? Should items
expire? Should the pane show other sessions' items for the same project (proposed: yes, grouped, own session first)?
Does an answer to another live session go by `$.session.send` (immediate) or wait for its next prompt (simpler)?

### 3b. SessionStart messages through the mod

**Today.** SessionStart handlers return `additionalContext` that the agent reads, whether it is meant for the agent or
the human. Strings over 10,000 characters are written to a file and the model gets a path and a 2,000-character preview
(`D/hooks:951,1037`). Human-facing advisories spend agent context and still get lost in scrollback.

**What the mod offers.** A pane with `Markdown` (up to 10,000 characters per element, `M/reference:240`), buttons to
dismiss or snooze, `$.ui.toast`/`$.ui.log` for one-liners that the model does not read (`M/api:132-138`), and no effect
on session start time (the mod reads a file after the fact). `prompt.context` could inject agent-facing blocks
(`DTS:3431-3441`), but it is not proposed: agent-facing text stays in hooks, one path, working without the mod, and
changing context text costs prompt cache (`M/events:238`).

**Design.**

1. Each SessionStart advisory gains an `audience`: `agent`, `human` or `both` (default `both`, so nothing changes until
   a handler opts in).
2. The daemon always writes the human-audience messages to `untracked/mod/messages/<session>.json`, each with a stable
   key and a content hash.
3. **Phase B1, in addition:** `additionalContext` is unchanged. The mod shows the messages in a "Daemon" pane (auto
   opened only when something is new and the terminal is wide enough; a toast otherwise). Dismiss and snooze go through
   `hooks-daemon messages dismiss <key> [--until-change]`; a dismissed key with an unchanged hash is not shown again.
4. **Phase B2, instead of:** a `human`-audience message is left out of `additionalContext` only when the daemon finds
   a presence record from a compatible mod **for this session** when its SessionStart handler runs. Otherwise it is
   included as today. The worst case of the race is a duplicate, which is today's behaviour.

**Must stay in hooks.** Anything the agent must act on (the session-actions directive, cron re-establishment,
ACTION_REQUIRED tiers), anything protective, every message in sessions with no drawing surface, and every message
when the mod is absent or unconfirmed.

**Open questions.** Which current SessionStart handlers are human-only? (Candidates: upgrade available, docs/plan QA
sweep summaries, plugin advisories after acknowledgement.) The ordering of the mod's `session.start` against the
SessionStart settings hook is **UNKNOWN** (probe U6), and decides how often B2 can apply on the first start.

### 3c. Session resilience (owner: "maybe"; detailed proposal)

**Principle.** The mod is a **witness**, never a decider. It writes facts that only it can see; the daemon's existing
handlers stay the single place that decides, and treat a missing or torn witness file as "no evidence", which is
today's behaviour.

| Capability                                  | What the mod sees (cite)                                                                                                                                                                                                                                                     | Witness file the daemon reads                                                      | Daemon change                                                                                                                                                                                                                                                                                                                                                    |
| ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Exact cron-tick recognition**             | `prompt.submit` `e.origin.kind`, "a closed set, never a text prefix": `composer`, `scheduled-trigger` ("a scheduled task, routine or /loop"), `peer`, `plugin`, `unclassified`, ... (`DTS:7027-7140`). The hook observes and calls `next(e)`.                                | `untracked/mod/origin/<session>/<sha256(text)>.json` = `{kind, at}`                | `utils/cron_tick.py` gains a second positive signal. `scheduled-trigger` without a sentinel is a tick (closes the documented residual gap: agent-composed crons, `/loop`). `composer` with a sentinel is the human pasting one. No witness: today's sentinel rule.                                                                                               |
| **Zero-cost drop while blocked on a human** | Already zero-cost: the daemon blocks the `UserPromptSubmit` (`failsafe_cron_blockage_suppressor.py`). The mod adds exactness only.                                                                                                                                           | Same origin witness                                                                | The suppressor applies its existing truth table to witnessed ticks it cannot recognise today. The mod does not `{drop}` anything itself, unless probe P2 shows the settings hook runs before the mod's `prompt.submit`; then the daemon pre-computes `untracked/mod/cadence/<session>.json` = `{drop_scheduled_until, reason}` and the mod obeys that file only. |
| **Usage-pause resume by timer**             | `session.measure` after each turn and on plan-limit changes (`M/reference:121`); `$.session.usage().rateLimits` = `{kind, percentUsed, resetsAt}` (`M/reference:185`); `$.clock.after` runs between turns (`M/api:111-128`); `$.prompt.submit` waits for idle (`M/api:142`). | `untracked/mod/usage/<session>.json` = the exact windows                           | `usage_pause_gate` may use the exact snapshot. While a pause record is live, the mod sets `$.clock.after(resume_at - now)` and submits `[tick:usage-resume] ...`, which the gate already recognises. The ten-minute resume cron stays as the fallback, because timers die on reload and with the session (`M/api:146`).                                          |
| **Exact model reading**                     | `turn.step` result `usage.model`, "the model that answered", per request, with `e.agentId` for subagents (`M/events:247,268`); `$.session.model()`.                                                                                                                          | `untracked/mod/model/<session>.jsonl`, last N `{requested, answered, agentId, at}` | `model_fallback_detector` and `model_downgrade_recorder` read it as exact evidence; inference stays the fallback. The `turn.step` hook is a pass-through generator (`yield* next(e)`), observe-only.                                                                                                                                                             |

One limit to state plainly: text the ccy supervisor types through the PTY arrives as `composer`, the user's own Enter
(`DTS:7040-7042`). The origin witness cannot tell the supervisor from the human; the supervisor's own signal files stay
the only evidence for that.

**The two live probes still needed** (open questions 5 and the new ordering question from the review):

- **P1: what `origin.kind` does a `CronCreate` session-cron tick carry?** The types say `scheduled-trigger` covers "a
  scheduled task, routine or /loop" (`DTS:7065`) and do not name session crons. Probe: a `--plugin-dir` scratch mod with
  `on('prompt.submit', ($, e, next) => { $.ui.log('origin=' + e.origin.kind); return next(e) })`; create a one-shot
  `CronCreate` a minute out, start a `/loop`, type a prompt, let a background task notify; read the logged kinds. If
  session crons are `unclassified`, exact recognition fails for exactly the ticks the daemon cares about and 3c's first
  row is dropped.
- **P2: in what order do a mod's `prompt.submit` hook and the daemon's `UserPromptSubmit` settings hook run, and does
  a `$.prompt.submit` prompt reach the settings hook?** The docs place only `PreToolUse` in the chain explicitly
  (`M/events:306-313`) and say `$.prompt.submit` goes "through every hook but the calling one" (`DTS:2505-2515`). Probe:
  the same scratch mod writes a timestamped file in `prompt.submit`; a project `UserPromptSubmit` command hook writes
  another; compare, then repeat with a `$.prompt.submit` from a `$.clock.after` timer and check the settings hook saw
  it with its text intact. This decides whether witness files arrive in time, and whether the usage-pause gate and the
  awaiting-human logic see mod-submitted prompts (3a depends on that too).

Further probes for later phases: U6 (mod `session.start` against SessionStart hook order), and the review's open
question 4 (whether `$.prompt.submit` or `$.command.run` can invoke built-in slash commands such as `/reload-plugins`),
which would let the mod reload itself after an upgrade.

**Open questions for the owner.** Is the witness principle acceptable (the mod observes, the daemon decides)? Should
the mod's timer resume replace the resume cron when the mod is confirmed, or always sit beside it (proposed: beside)?

---

## Part 4: phased build order and risks

### 4.1 Phases

| Phase | Content                                                                                                                                                                                                                                                                   | Depends on           | Ships value without the mod? |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ---------------------------- |
| 0     | **Mod awareness** (Part 5) and the doc corrections. Approved; daemon-only.                                                                                                                                                                                                | none                 | Yes                          |
| 1a    | Probes U1, U2, U3, P1, P2, U6 with a throwaway `--plugin-dir` / `.claude/skills/` scratch mod in a scratch project.                                                                                                                                                       | none                 | n/a                          |
| 1b    | **Daemon-side human queue**: store, `hooks-daemon human ...` CLI, status-line count, SessionStart listing, `UserPromptSubmit` verification, stop-handler and guard integration. Smallest useful slice: it fixes "lost in scrollback" for CLI users before any mod exists. | 1a not needed        | Yes                          |
| 1c    | **The mod skeleton plus the human pane**: packaging, deploy into `.claude/skills/hooks-daemon-mod/` from install/upgrade, `mod hello` handshake and presence file, `status` feature, the human pane (list, reply, done).                                                  | 1a (U1), 1b          | n/a                          |
| 2     | SessionStart messages, phase B1 (in addition), `audience` tags, dismiss/snooze CLI.                                                                                                                                                                                       | 1c                   | Partly (tags, CLI)           |
| 3     | SessionStart phase B2 (instead of, when presence confirmed).                                                                                                                                                                                                              | 2, U6                | n/a                          |
| 4     | Resilience witnesses, only after the owner rules: origin witness first (P1, P2), then model, then usage snapshot and timer resume.                                                                                                                                        | owner ruling, P1, P2 | n/a                          |

The smallest useful **mod** slice is 1c: one pane that shows open questions and tasks and lets the human answer or
tick them, standing on a daemon-side queue that already works without it.

### 4.2 Risks

| Risk                                                                                                                       | Mitigation                                                                                                                                                                                                                     |
| -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| API churn: the types say EARLY ACCESS (`DTS:11-14`); the docs warn the API "can change between releases" (`M/create:384`). | Small surface; `claude plugin test` in CI; the handshake reports `cc-version`; any feature can be switched off in config without a release.                                                                                    |
| The mod is off for many users (managed policy, remote switch, safe mode).                                                  | Nothing depends on it (§2.6); `health` says why it is off.                                                                                                                                                                     |
| Our own mod trips our own awareness check (it hooks `prompt.submit` and `turn.step` in phase 4).                           | Exemption by provenance only: the copy at the deployed path must be byte-identical to the shipped tree of the running daemon version (`_trees_match`). Any drift and it is treated as a foreign mod, loudly.                   |
| A same-named marketplace or `--plugin-dir` copy shadows the project copy (`P/loading:368-380`).                            | Detected in Part 5's inventory and reported.                                                                                                                                                                                   |
| A committed `.claude/skills/hooks-daemon-mod/` loads for collaborators without the daemon.                                 | It finds no daemon and draws nothing (§2.5).                                                                                                                                                                                   |
| Prompt-cache cost: changing context text from a mod invalidates the cache (`M/events:238`).                                | The mod never adds context, sections or attachments; answers arrive as ordinary prompts.                                                                                                                                       |
| Per-request overhead of a `turn.step` generator (phase 4).                                                                 | Pass-through only, one small append per request; measured before it ships.                                                                                                                                                     |
| Spoofed human input: any mod can `$.prompt.submit({ asUser: true })` (`M/admin:129-141`).                                  | Answers are verified against the daemon's queue before being labelled human (3a).                                                                                                                                              |
| The mod runs as the user, unsandboxed (`M/overview:78-89`); a bug in it has the user's reach.                              | Minimal `calls:` list (`$.fs.read`, `$.fs.stat`, `$.fs.write` to `untracked/mod/` only, `$.process.run` of the daemon binary only, `$.ui.*`, `$.prompt.submit`, `$.clock.*`); reviewed through `claude plugin validate` in QA. |

---

## Part 5: daemon mod-awareness (approved item i)

### 5.1 What to read

1. **Which plugins can carry a mod.** Extend `resolve_enabled_plugins` (`src/claude_code_hooks_daemon/utils/claude_plugins.py`)
   beyond install records, which today reports `@skills-dir`, `@synced` and `--plugin-dir` plugins as unresolved
   (lines 18-21):
   - project `.claude/skills/*/.claude-plugin/plugin.json` and `~/.claude/skills/*/...` (`P/loading:63`);
   - `<config>/plugins/synced/` (`P/loading:182`);
   - `CLAUDE_CODE_PLUGIN_DIRS` from the hook's environment (`M/reference:277`);
   - `~/.claude/dev-mods/<session-id>/<name>/` for the hook's `session_id` (`M/create:43`);
   - optionally `claude plugin list --json` in `health` only (not on the hook path), for errors and the
     authoritative id list (`P/cli-reference:313-333`).
2. **Whether a plugin is a mod.** `hooks/hooks.json` (and manifest-declared hook files) with a `modules` array
   (`M/reference:32`). Today `_hook_file` rejects a file with no `hooks` object as "not a hooks file"
   (`claude_plugins.py:634-640`), so a mod-only plugin is invisible; it must return the `modules` list as well.
3. **What it hooks.** In `health` and the background inventory: `claude plugin validate --json <dir>` (the `hooks:` and
   `calls:` lines and `gatingHooks`, `M/admin:119-127`, `D/changelog:38`). The `--json` report's documented top-level
   fields are `success`, `strict`, `target`, `manifest`, `contents` (`P/cli-reference:630-636`); where the `hooks:`/
   `calls:` data sits inside `contents` is **UNKNOWN** (probe: run it on the scratch mod). On the SessionStart path, a
   static scan of the module and its relative imports for `on('<literal>'` is enough and fast, because Claude Code
   refuses to load a module whose event names are not literals (`M/create:324-331`, `M/admin:127`). Cache by file
   path, size and mtime.
4. **Its tier.** Whether it is managed or org (`prependPlugins`/`appendPlugins` in readable managed settings,
   `D/settings-reference:4790-4828`), so an organisation's own policy mod is reported but not shouted at.

### 5.2 Which hook points count as interfering

| Class                                                        | Events                                                                                                                                                         | Why (cite)                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **OVERRIDES** the daemon                                     | `tool.check`                                                                                                                                                   | Answers after the rules and non-managed `PreToolUse` hooks and can replace their decision, approving a call the daemon denied; without the built-in guard it can lift `deny` rules too (`M/events:313`, `D/permissions:572-577`, `M/admin:77,91`).                                                                                                                                                                         |
| **SILENCES** the daemon                                      | `tool.call` (unless its matcher is limited to the mod's own `mcp__<plugin>__` tools); any `classic.<Event>`; `*`                                               | A `tool.call` answer without `next` keeps non-managed `PreToolUse` hooks from running, and a rewrite happens before the daemon judges (`M/events:311`, `M/admin:87`). The classic chain is "[managed settings hooks, ...hooks modules, the other settings hooks as core]" (`DTS:956-958`), so a module that does not call `next` on `classic.Stop`, `classic.UserPromptSubmit` or any other event stops the daemon for it. |
| **ALTERS** what the daemon sees or what Claude reads from it | `prompt.submit`, `session.append`, `prompt.attachment`, `prompt.section`, `prompt.compose`, `session.compact`, `plugin.register`, `engine.create`, `turn.step` | Rewrite or drop prompts before the daemon's gates (`M/reference:76`, `M/admin:143`); rewrite stored transcript rows the daemon's Stop handlers read (`M/reference:119`); omit reminders that may carry hook context (`M/reference:82`, whether hook `additionalContext` is an attachment kind is **UNKNOWN**); refuse other mods or reshape their API (`M/reference:152-153`); swap the model (`M/events:247`).            |
| **Bypass calls** (reported, not ranked)                      | `$.fs.write`, `$.process.run`/`spawn`, `$.env.set`, `$.prompt.submit` (especially `asUser`)                                                                    | No `PreToolUse` hook or deny rule sees a mod's own calls (`M/admin:76`, `M/admin:129-141`).                                                                                                                                                                                                                                                                                                                                |

### 5.3 How loud

The owner asked for "exceptionally" loud. For any unacknowledged mod in OVERRIDES or SILENCES:

1. **SessionStart, every source** (startup, resume, clear, compact; unlike `plugin_hooks_advisor`, which skips resume):
   a block placed first, in the highest tier, aimed at both readers. To the agent through `additionalContext`, to the
   human through `systemMessage` (`D/hooks:756`): `⚠ MOD <id> CAN OVERRIDE/SILENCE THE HOOKS DAEMON: hooks <list>. Daemon denies are not final while it is enabled. Disable: <exact command>.`
2. **Status line**: a persistent red segment, `⚠ MOD OVERRIDES HOOKS: <name>`, while it stays enabled.
3. **`hooks-daemon health`**: a "Mods" section listing every mod (id, origin, tier, version, hooks, calls, class,
   acknowledgement), with FAIL for an unacknowledged OVERRIDES/SILENCES mod; plus "mods can load here" from
   `claude plugin test` (`M/troubleshoot:33-41`).
4. **`hooks-daemon upgrade`** output repeats the health findings.
5. **Acknowledgement is narrow and expires on change**: `acknowledged_mods: [{id, sha256, reason}]`. The hash covers the
   module files, so an update to the mod brings the full warning back. An acknowledged OVERRIDES/SILENCES mod still gets
   one SessionStart line and keeps the status-line segment.

ALTERS-only mods get a normal SessionStart advisory (new sessions) and a `health` WARN. Bypass calls are listed in
`health` only. A managed or org-tier mod is reported once per new session at advisory level, naming the organisation as
its owner.

The daemon cannot stop a mod and does not try (mods are not for protection, and neither is the daemon's knowledge of
them): it states the risk and gives the exact way to disable it (`"<id>": false` in `.claude/settings.local.json`,
`P/loading:158`, or `claude plugin disable`).

### 5.4 Where it surfaces

`plugin_hooks_advisor` (extended, or a sibling `mod_advisor` sharing the inventory), the status line, `health`,
`upgrade`, and `bin/hooks-daemon explain-rule` for a new rule id (for example `R-MOD-OVERRIDES-HOOKS`).

### 5.5 Docs to correct

Each states a guarantee mods break ("a daemon deny always wins"):

- `CLAUDE/ClaudeCodePlugins.md:111`
- `CLAUDE/ARCHITECTURE.md:900`
- `docs/guides/CLAUDE_CODE_PLUGINS.md:35`
- `src/claude_code_hooks_daemon/handlers/session_start/plugin_hooks_advisor.py:8` (docstring) and `:96` (the
  advisory text agents read)
- `src/claude_code_hooks_daemon/utils/claude_plugins.py:18-21` (once skills-dir and inline plugins are resolved)
- Historical release note `CLAUDE/UPGRADES/v3/v3.66.0-to-v3.67.0/release-notes/043-...md:10` stays as written; the
  next release notes carry the correction.

The corrected statement: a daemon deny wins over every settings and plugin hook, but a mod hooking `tool.check` can
approve the call anyway, and a mod answering `tool.call` or a `classic.*` event without calling `next` stops the daemon
running for it.
