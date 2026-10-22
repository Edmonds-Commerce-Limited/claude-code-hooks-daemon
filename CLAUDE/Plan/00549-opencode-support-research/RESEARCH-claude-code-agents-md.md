# Task 1.5: how far Claude Code treats `AGENTS.md` like `CLAUDE.md`

The owner asked: "I believe Claude Code itself will read AGENTS if there is no CLAUDE file? Can we confirm that AGENTS
functionality is fully equivalent in Claude Code, e.g. sub folders etc?" The owner also wants to be able to enforce
`AGENTS.md` as the canonical file.

**Short answer.** Yes. From v2.1.277, Claude Code reads `AGENTS.md` when no `CLAUDE.md` is found. The support is
**not fully equivalent**, though. It comes from a built-in plugin (`cc-plugin-agents-md@builtin`) layered on the native
`CLAUDE.md` loader, not from the loader itself. In the default mode, **one `CLAUDE.md` anywhere at or above the working
directory switches off every `AGENTS.md`, nested ones included**. Nested `AGENTS.md` files load only through the Read
tool or an `@`-mention, where a nested `CLAUDE.md` also loads on Write, Edit and single-file Bash reads.
`InstructionsLoaded` hooks do not fire for `AGENTS.md`. The robust "AGENTS.md canonical" layout is a `CLAUDE.md` shim
containing `@AGENTS.md` in **every** directory that has an `AGENTS.md`, not just at the root.

The claim in `RESEARCH-dual-tool-repos.md` §1 finding 2 ("reads `AGENTS.md` only when no `CLAUDE.md`, `.claude/CLAUDE.md`
or `CLAUDE.local.md` exists in the working directory or above it", v2.1.277+) is **VERIFIED** (probes a, c, c6, g2 and i
below). That file does not cover the nested-directory consequences recorded in §4.

## 1. Evidence base

| Source                                                                                                            | What it is                                                                                                                                                                    |
| ----------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `remote-docs/code.claude.com/docs/en/memory.md` (fetched 2026-10-17)                                              | Vendored copy of https://code.claude.com/docs/en/memory. The `## AGENTS.md` section is L359-481                                                                               |
| `remote-docs/code.claude.com/docs/en/changelog.md` (fetched 2026-10-17)                                           | Vendored copy of the changelog                                                                                                                                                |
| Installed CLI `claude --version` = **2.1.308**                                                                    | Used for every probe                                                                                                                                                          |
| Plugin source in `/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`, byte offset ≈277,465,984 | The minified JS of the `cc-plugin-agents-md` hooks module, carved out of the 2.1.308 binary (excerpt kept at `untracked/scratch/agentsmd-probe-out/plugin-src-b-excerpt.txt`) |
| About 40 local probe runs, no model calls (§3)                                                                    | Fixtures under `/tmp/agentsmd-probe-J1jc` and `/tmp/agentsmd-probe-iFFs` (deletion was denied by the permission system; remove by hand)                                       |

### Changelog entries (vendored `changelog.md` line → release)

| Release              | Line  | Entry                                                                                                                                                        |
| -------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **2.1.277** (Sep 18) | L2281 | "Added AGENTS.md support: in a project with no CLAUDE.md, Claude Code reads AGENTS.md instead; change it under 'Project instructions' in `/config`"          |
| 2.1.281 (Sep 23)     | L1977 | AGENTS.md support extended to Bedrock, Vertex, Foundry, LLM gateways and sessions with telemetry disabled                                                    |
| 2.1.285              | n/a   | Plugin ID renamed `agents-md@builtin` → `cc-plugin-agents-md@builtin`. Both IDs are read from 2.1.285 on (`memory.md` L416). Not found as a changelog line   |
| 2.1.290 (Oct 5)      | L1071 | "Fixed a subdirectory's AGENTS.md not being attached when a file under it is @-mentioned"                                                                    |
| 2.1.290              | L993  | Fixed a `CLAUDE.md`, rule or `AGENTS.md` symlinked outside the working directories loading despite `blockReadsOutsideWorkingDirectories` or a Read deny rule |
| 2.1.280              | n/a   | `/memory` and `/context` list a directly read `AGENTS.md` from this release on (`memory.md` L618)                                                            |

The rename date and the 2.1.280 behaviour come from the docs only. No changelog line was found for either.

## 2. How it is built (plugin source, 2.1.308)

The plugin is a hooks module registered on these events: `session.start, prompt.context, command.run, session.compact, prompt.submit, turn.start, turn.complete, agent.spawn, tool.call, prompt.mention`. It also appears in the `plugins`
array of the stream-json `init` message, and the debug log line is `hooks module cc-plugin-agents-md@builtin loaded`.
What the code does:

- **Launch (`prompt.context`).** In the default `claude-md-or-agents-md` mode it runs
  `fs.ancestors({names: [CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md]})` from the working directory. If **any**
  ancestor has one (`isClaudeProject`), it adds nothing. Otherwise it runs `fs.ancestors({names: [AGENTS.md, .claude/AGENTS.md]})` and splices those files into the engine's own `instructionFiles` list. That is why they appear
  in `/context` as `Project` rows, exactly like `CLAUDE.md`.
- **Nested (`tool.call` with filter `{tool:"Read"}`, and `prompt.mention`).** The function `ee()` returns nothing at
  all when `isClaudeProject` is true. Otherwise it walks from the read file up to the session root, drops directories
  that hold a `CLAUDE.md` (`outsideClaudeDirs`), and returns the result as tool-result `context`. In the transcript
  that context is a `hook_additional_context` attachment headed `Contents of …/AGENTS.md`. A nested `CLAUDE.md` is a
  native `nested_memory` attachment instead.
- **Read only.** The `tool.call` registration filters on `tool:"Read"` and re-checks `r.tool!=="Read"`. Write, Edit and
  Bash `cat` never trigger it. Native nested `CLAUDE.md` loads on Write and Edit (changelog L1238) and on single-file
  Bash `cat`/`head`/`sed -n` (L785; `memory.md` L156).
- **Off switches.** `CLAUDE_CODE_SIMPLE` or `CLAUDE_CODE_DISABLE_ATTACHMENTS` turns nested loading off. The
  `claude-md` mode registers no loader. `managed-only` drops instruction files.
- **Bookkeeping.** `session.compact` resets the "already given" set, so nested files reload on demand after
  compaction. `agent.spawn` (forks) inherits the parent's given set. A built-in reset command clears it.
- **Settings scope.** The debug log says the plugin reads `pluginConfigs` "in user, --settings or managed settings
  (project settings are not read)".

## 3. Empirical probes

**Method.** The child `claude` CLI is **not logged in** (`claude auth status` → `loggedIn:false`), so no model call
could run. The canary-listing approach in the brief therefore was not possible. Two auth-free observations replaced it.
Both are more exact than a model's self-report:

1. **Launch-time set.** `claude -p --model haiku "/context"`, a local command, prints a **Memory Files** table.
2. **Lazy set.** `claude -p --model haiku --session-id <uuid> "@sub/file.txt summarise"`. The API call fails, but
   `@`-mention attachments are computed locally and written to `~/.claude/projects/<dir>/<uuid>.jsonl`. The probe
   inspected the `instructions` (launch), `nested_memory` (native nested `CLAUDE.md`) and `hook_additional_context`
   (plugin `AGENTS.md`) attachments.

Fixtures were built under `mktemp -d /tmp/agentsmd-probe-XXXX` (`/tmp/agentsmd-probe-iFFs`), each one a `git init`
repository. There was no `/etc/claude-code`, no `~/.claude/CLAUDE.md` and no user hooks. Each file held a unique
`CANARY_*` token. Scripts: `untracked/scratch/agentsmd-probe/run.sh` and `run2.sh`. Raw outputs:
`untracked/scratch/agentsmd-probe-out/` (`summary.txt`, `summary2.txt` and the per-case files).

`and-mode` means `--settings '{"pluginConfigs":{"cc-plugin-agents-md@builtin":{"options":{"instructionFiles":"claude-md-and-agents-md"}}}}'`.

### 3a. Launch-time (`/context` Memory Files)

| #   | Fixture (cwd)                                                                 | Loaded at launch                       | Verdict                                                                                            |
| --- | ----------------------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------------------------------------- |
| a   | `AGENTS.md` only                                                              | `AGENTS.md`                            | Fallback works                                                                                     |
| b   | `CLAUDE.md` only                                                              | `CLAUDE.md`                            | Baseline                                                                                           |
| c   | both at root                                                                  | `CLAUDE.md` only                       | **CLAUDE.md wins, AGENTS.md dropped**                                                              |
| c2  | both, and-mode                                                                | `CLAUDE.md`, then `AGENTS.md`          | Both, CLAUDE first                                                                                 |
| c3  | `AGENTS.md` only, `--settings` instructionFiles=`claude-md`                   | nothing                                | The mode switch works                                                                              |
| c4  | `AGENTS.md` only, `claude-md` mode in the **project** `.claude/settings.json` | `AGENTS.md`                            | **Project settings ignored**. A repository cannot choose the mode                                  |
| c5  | `.claude/AGENTS.md` only                                                      | `.claude/AGENTS.md`                    | Supported                                                                                          |
| c6  | `AGENTS.md` + `.claude/CLAUDE.md`                                             | `.claude/CLAUDE.md` only               | `.claude/CLAUDE.md` counts as a CLAUDE file                                                        |
| d   | root + `sub/` `AGENTS.md`, cwd=root                                           | root `AGENTS.md`                       | Nested not eager (correct)                                                                         |
| d2  | same, cwd=`sub/`                                                              | root and `sub/` `AGENTS.md`            | Ancestor walk works                                                                                |
| d3  | root `CLAUDE.md` + `sub/AGENTS.md`, cwd=`sub/`                                | root `CLAUDE.md` only                  | **Ancestor CLAUDE.md suppresses the AGENTS.md in the cwd itself**                                  |
| d4  | root `AGENTS.md` + `sub/CLAUDE.md`, cwd=`sub/`                                | `sub/CLAUDE.md` only                   | **Root AGENTS.md dropped** because cwd has a CLAUDE.md                                             |
| d4b | same, cwd=root                                                                | root `AGENTS.md`                       | The result depends on where you launch                                                             |
| e   | root + `sub/` `CLAUDE.md`, cwd=`sub/`                                         | both                                   | Native baseline                                                                                    |
| f   | `AGENTS.md` with `@docs/extra.md`                                             | `AGENTS.md`, `docs/extra.md`           | `@` imports expanded                                                                               |
| f2  | `CLAUDE.md` = `@AGENTS.md` + text                                             | `CLAUDE.md`, `AGENTS.md`               | Shim works                                                                                         |
| f2b | f2 in and-mode                                                                | `CLAUDE.md`, `AGENTS.md` (once)        | No duplicate                                                                                       |
| f3  | `CLAUDE.md` → `AGENTS.md` symlink, and-mode                                   | `CLAUDE.md` (once)                     | No duplicate                                                                                       |
| g   | `AGENTS.md` in the parent **above the git root** + repo `AGENTS.md`           | parent and repo `AGENTS.md`            | The walk passes the git root. A stray `~/AGENTS.md` would load                                     |
| g2  | `CLAUDE.md` in the parent above the git root + repo `AGENTS.md`               | parent `CLAUDE.md` only                | **A stray `CLAUDE.md` above the repo (e.g. `~/CLAUDE.md`) silently disables the repo's AGENTS.md** |
| h1  | `CLAUDE_CONFIG_DIR=<tmp>` holding `AGENTS.md`                                 | project `AGENTS.md` only               | **No user-level AGENTS.md** (`~/.claude/AGENTS.md` is not read)                                    |
| h2  | `CLAUDE_CONFIG_DIR=<tmp>` holding `CLAUDE.md`, project `AGENTS.md`            | User `CLAUDE.md` + project `AGENTS.md` | A user `CLAUDE.md` does not count (matches `memory.md` L380)                                       |
| i   | `AGENTS.md` + `CLAUDE.local.md`                                               | `CLAUDE.local.md` only                 | **A personal local file disables the team AGENTS.md**                                              |
| i2  | `AGENTS.md` + `AGENTS.local.md` + `AGENTS.override.md` + `.agents/AGENTS.md`  | `AGENTS.md` only                       | No local or override variant (matches L387)                                                        |
| j   | `AGENTS.md` + `.claude/rules/style.md`                                        | rule + `AGENTS.md`                     | Rules do not count and load alongside                                                              |

`/root/.claude` was never modified. Probe h used a throwaway `CLAUDE_CONFIG_DIR`, which worked because `/context`
needs no auth.

### 3b. Lazy / nested (`@`-mention, transcript attachments)

| #   | Fixture (cwd=root)                                                                                               | `@` target      | Nested context injected                                                          |
| --- | ---------------------------------------------------------------------------------------------------------------- | --------------- | -------------------------------------------------------------------------------- |
| d   | root + `sub/` `AGENTS.md`                                                                                        | `sub/file.txt`  | `sub/AGENTS.md` as `hook_additional_context` (plugin)                            |
| d6  | root, `x/` and `x/y/` `AGENTS.md`                                                                                | `x/y/file.txt`  | `x/AGENTS.md` and `x/y/AGENTS.md` (plugin): all intermediate levels              |
| d3  | root `CLAUDE.md` + `sub/AGENTS.md`                                                                               | `sub/file.txt`  | **nothing**                                                                      |
| d3  | same, and-mode                                                                                                   | `sub/file.txt`  | `sub/AGENTS.md` (plugin)                                                         |
| d5  | root `AGENTS.md`; `sub/` has `CLAUDE.md` and `AGENTS.md`                                                         | `sub/file.txt`  | `sub/CLAUDE.md` only (native `nested_memory`)                                    |
| e   | root + `sub/` `CLAUDE.md`                                                                                        | `sub/file.txt`  | `sub/CLAUDE.md` (native `nested_memory`)                                         |
| k   | root `CLAUDE.md`=`@AGENTS.md`; `sub/CLAUDE.md`=`@AGENTS.md` + `sub/AGENTS.md`; `sub2/AGENTS.md` with **no** shim | `sub/file.txt`  | `sub/CLAUDE.md` + `sub/AGENTS.md`, both native `nested_memory` (import expanded) |
| k   | same                                                                                                             | `sub2/file.txt` | **nothing**. An unshimmed nested AGENTS.md is invisible under a root shim        |

### 3c. `InstructionsLoaded` hook (`--settings` hook appending stdin to a log, then `/context`)

| Fixture               | Events                                                               |
| --------------------- | -------------------------------------------------------------------- |
| a (`AGENTS.md` only)  | **none**                                                             |
| b (`CLAUDE.md`)       | `CLAUDE.md` Project `session_start`                                  |
| f2 (shim)             | `CLAUDE.md` `session_start` + `AGENTS.md` Project **`include`**      |
| j (rules + AGENTS.md) | `.claude/rules/style.md` only. The AGENTS.md beside it fires nothing |

**Not tested empirically, for lack of auth.** Whether a nested `AGENTS.md` loads on Write, Edit or Bash `cat`. The
plugin source (Read-only filter) and the docs (`memory.md` L385, "with the Read tool") agree that it does not. `/init`
output was not tested either: it needs a model. The docs say `/init` only reads `AGENTS.md` when
`CLAUDE_CODE_NEW_INIT=1` (`memory.md` L476-480), and it always produces a `CLAUDE.md`, never an `AGENTS.md`.

## 4. Equivalence table: `CLAUDE.md` vs `AGENTS.md` read by the plugin (2.1.308, default mode)

| Feature                                                      | `CLAUDE.md`                                   | `AGENTS.md` (direct)                                                                                                           | Evidence                   |
| ------------------------------------------------------------ | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | -------------------------- |
| Root file loaded at launch                                   | yes                                           | yes, **only if no CLAUDE file at or above cwd**                                                                                | a, c, g2; docs L363-366    |
| `.claude/` variant                                           | `.claude/CLAUDE.md`                           | `.claude/AGENTS.md`                                                                                                            | c5, c6                     |
| Ancestor walk (cwd up to `/`, past the git root)             | yes                                           | yes                                                                                                                            | d2, g                      |
| Coexistence with CLAUDE.md                                   | n/a                                           | **no** (needs user-level `claude-md-and-agents-md`)                                                                            | c, c2, d3, d4              |
| Nested lazy load                                             | Read, Write, Edit, single-file Bash read, `@` | **Read and `@` only**                                                                                                          | d, d6; source; L785, L1238 |
| Nested load when any CLAUDE file at/above cwd                | yes                                           | **no, never** (default mode)                                                                                                   | d3, k                      |
| Nested dir holding both files                                | its CLAUDE.md                                 | skipped                                                                                                                        | d5                         |
| How nested content arrives                                   | `nested_memory` (instruction file)            | `hook_additional_context` on the tool result                                                                                   | d vs e                     |
| `@path` imports                                              | yes                                           | yes                                                                                                                            | f; L386                    |
| External-import approval dialog                              | prompts                                       | loads only if already approved, never prompts                                                                                  | L438 (docs only)           |
| HTML-comment stripping                                       | yes                                           | UNVERIFIED                                                                                                                     | n/a                        |
| `claudeMdExcludes`                                           | yes                                           | yes (docs)                                                                                                                     | L386 (not probed)          |
| Local personal variant                                       | `CLAUDE.local.md`                             | **none** (`AGENTS.local.md` ignored). A `CLAUDE.local.md` disables AGENTS.md                                                   | i, i2                      |
| Override variant                                             | n/a                                           | `AGENTS.override.md` ignored                                                                                                   | i2                         |
| User-level file                                              | `~/.claude/CLAUDE.md`                         | **none**                                                                                                                       | h1, h2                     |
| Managed policy file                                          | `/etc/claude-code/CLAUDE.md`, `claudeMd` key  | **none** (managed stays CLAUDE.md)                                                                                             | docs L69, L308             |
| `.claude/rules/`                                             | loads                                         | loads alongside (does not count)                                                                                               | j                          |
| `InstructionsLoaded` hook                                    | fires                                         | **does not fire** (fires `include` when imported via a shim)                                                                   | 3c                         |
| `--add-dir` + `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` | loads                                         | does not load                                                                                                                  | L437 (docs only)           |
| Listed in `/context` and `/memory`                           | yes                                           | yes, from 2.1.280                                                                                                              | a; L618                    |
| Survives `/compact`                                          | root re-read, nested on demand                | plugin resets "given", nested reload on Read                                                                                   | source; L636               |
| Subagents                                                    | per docs                                      | same: files that load for subagents load, forks inherit                                                                        | L386; source `agent.spawn` |
| Project can choose the mode                                  | n/a                                           | **no**: user, `--settings` or managed only                                                                                     | c4; debug log; L404        |
| Disable switches                                             | n/a                                           | `/plugin` disable, `claude-md` mode, `CLAUDE_CODE_SIMPLE`, `CLAUDE_CODE_DISABLE_ATTACHMENTS` (nested), versions before 2.1.277 | source; L420-428           |
| Generated by `/init`                                         | yes                                           | no (it reads AGENTS.md only with `CLAUDE_CODE_NEW_INIT=1`)                                                                     | L476-480                   |

**Verdict.** Root-level parity is good when no `CLAUDE.md` exists anywhere on the path. The support is **not
equivalent** for sub-folders, for coexistence with `CLAUDE.md`, for hooks, or for user, managed and local scopes. It is
a fallback, not a peer.

## 5. What enforcing "`AGENTS.md` canonical" would take

Claude Code itself does not offer any repository-level way to force `AGENTS.md`: the mode is ignored in project
settings (c4). The workable designs:

1. **Shim pattern, root and nested (recommended).** Each directory with an `AGENTS.md` gets a `CLAUDE.md` whose first
   line is `@AGENTS.md`, followed optionally by Claude-only extras. Probe k shows this restores native behaviour: launch,
   nested `nested_memory` on Read, Write, Edit and Bash, `InstructionsLoaded` (`include`), and every version. It also
   keeps opencode working, since opencode reads `AGENTS.md` (see `RESEARCH-dual-tool-repos.md` option A). Symlinks work
   too (f3), but fail on Windows and refuse Edit through the link (`memory.md` L467-470).

2. **A daemon check, "agents-md canonical".** This would be a new handler or `docs_qa` check, plus a commit gate, that
   flags:

   - (a) an `AGENTS.md` whose directory has no `CLAUDE.md` while any `CLAUDE.md` exists at or above it (probes d3 and
     k: it would be invisible to Claude Code);
   - (b) a `CLAUDE.md` beside an `AGENTS.md` that does not import it (`@AGENTS.md` outside a code span);
   - (c) a shim `CLAUDE.md` carrying shared content that belongs in `AGENTS.md` (divergence);
   - (d) a committed `CLAUDE.local.md` (i);
   - (e) optionally, `CLAUDE.md`/`AGENTS.md` above the git root. The daemon cannot change this, but it could warn at
     SessionStart (g, g2).

   A SessionStart advisory could also report the effective mode and the "first session after upgrade" caveat
   (`memory.md` L426).

3. **Do not rely on the plugin's fallback for this repository.** This repository has a root `CLAUDE.md` and 12 nested
   ones (`RESEARCH-dual-tool-repos.md` L270). Under the fallback, any `AGENTS.md` added without a shim is silently
   ignored. The daemon also depends on `InstructionsLoaded`, which only fires through a shim.

4. **The user-level `claude-md-and-agents-md` setting** (`~/.claude/settings.json` `pluginConfigs`) makes both load and
   nested `AGENTS.md` load on Read. It cannot be committed with a repository, and it still misses Write, Edit and Bash
   triggers and `InstructionsLoaded`. It suits individual developers, not enforcement. Provisioning it is possible only
   at user or managed scope.

5. **Migration of the 12 nested `CLAUDE.md` files.** Each would become `AGENTS.md` plus a one-line shim. The daemon's
   own `.claude/agents/CLAUDE.md` and `.claude/skills/CLAUDE.md` are Claude-only, and opencode would not want them.

## 6. Gaps

- No model-backed run (child CLI not logged in). The nested Write, Edit and Bash behaviour comes from source and docs,
  not from observation.
- HTML-comment stripping, `claudeMdExcludes` on `AGENTS.md`, the external-import approval difference and `--add-dir`
  were not probed.
- The plugin source is minified 2.1.308 code carved from the binary. Identifiers may change between releases.
- The probe transcripts remain under `/root/.claude/projects/-tmp-agentsmd-probe-*` (ordinary session files created by
  the probe runs, not configuration).
