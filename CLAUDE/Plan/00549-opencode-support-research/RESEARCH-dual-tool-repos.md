# RESEARCH: Dual-tool repositories (opencode + Claude Code)

Plan 00549, Task 1.3. Research only.

**Sources and versions.** opencode source is the clone at `/workspace/untracked/repos/opencode`, HEAD
`c93aaae37157d785f76a8e9a9243a6560e286468` (2026-10-21). `packages/cli/package.json` says **2.1.2**. The tag
`github-v1.2.27` belongs to the GitHub Action, not to the CLI. **The v1 → v2 boundary matters for this topic.**
Commit `44b6938b2a` ("removed packages/opencode", 2026-07-20) deleted the v1 implementation. Tags `v2.0.0`..`v2.1.2`
contain that commit and `v1.19.3` is the last v1 tag. File paths below without a prefix are relative to the clone at
HEAD. v1 behaviour is cited as `v1.19.3:<path>`.

Claude Code behaviour comes from the vendored docs under `/workspace/remote-docs/code.claude.com/docs/en/`, fetched
2026-10-17. The main one is `memory.md`, from https://code.claude.com/docs/en/memory.

Prior art: Plan 00292 (`CLAUDE/Plan/Completed/00292-codex-cli-dual-host-research/`) covered Codex.
`RESEARCH-codex-lifecycle.md` §8 there records that Codex treats `AGENTS.md` as its `CLAUDE.md` analogue. This
document does not repeat that work.

Verdict labels used here:

- **sees**: opencode reads the file and interprets it as intended.
- **sees wrongly**: opencode reads it, but parses or uses it differently.
- **does not see**: opencode never reads it.

---

## 1. Headline findings

1. **opencode v2 does NOT read `CLAUDE.md` at all.** The opencode docs say it does (`packages/web/src/content/docs/rules.mdx`
   L77-103 describe a "Claude Code Compatibility" fallback: `CLAUDE.md` when no `AGENTS.md`, plus `~/.claude/CLAUDE.md`).
   That was true in v1 (`v1.19.3:packages/opencode/src/session/instruction.ts` L60-68, L122-133). In v2 the only
   auto-discovered instruction filename is `AGENTS.md` (`packages/core/src/config/plugin/instruction.ts` L41, L55, L87;
   `packages/core/src/tool/plugin/read.ts` L16). The CLI comment is explicit: "`.claude is only read for skills`"
   (`packages/cli/src/server-process.ts` L126-130). `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT` (documented in
   `cli.mdx` L684) is no longer read anywhere in v2. **The docs and the code disagree. Trust the code.** As a result,
   an opencode v2 session in this repository gets **no project instructions**: no root `CLAUDE.md`, no `<hooksdaemon>`
   guidance section and no nested `CLAUDE.md`.
2. **Claude Code now reads `AGENTS.md` natively, from v2.1.277** (`memory.md` L359-391). By default it reads
   `AGENTS.md` only when no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` exists in the working directory or
   above it. A `CLAUDE.md` with `@AGENTS.md` works on every version (`memory.md` L444, L449-459). **`AGENTS.md` as the
   canonical file is therefore the only instruction layout that both tools read with no per-user setup.**
3. **The only `.claude/` content opencode v2 reads is `skills/`.** It reads project `.claude/skills/`,
   `~/.claude/skills/` and the `.agents/skills/` equivalents (`packages/core/src/config/plugin/compatibility.ts`
   L42-55; `packages/core/src/config/discovery.ts` L69-70, L129-143). `.claude/agents`, `.claude/commands`,
   `.claude/rules`, `.claude/settings*.json`, `.mcp.json` and the hooks are all invisible to it.
4. **Skills are the one shared format, and they mostly port.** opencode accepts `name`, `description`, `metadata` and
   `disable-model-invocation` in skill frontmatter and ignores other keys (`packages/core/src/config/plugin/skill-file.ts`
   L10-15). Several Claude-only features silently degrade:
   - `allowed-tools`, `argument-hint` and `user-invocable` are ignored.
   - `$ARGUMENTS` and `CLAUDE_*` variables are not expanded inside skills.
   - **Any loose `.md` file at the top level of a skills root becomes a skill** (`skill-scan.ts` L34-37). This
     repository's `.claude/skills/CLAUDE.md` would therefore surface as a phantom skill named `CLAUDE`.
5. **None of the daemon's protections reach an opencode session today.** The protections that look like commit-time
   protections are all Claude Code `PreToolUse` handlers keyed on a Bash `git commit`. Examples:
   `conflict_marker_commit_gate`, `docs_qa_commit_gate`, `plan_qa_commit_gate`, `guard_config_commit_gate` and the
   `sensitive_content` commit scan. This repository has **no git hooks installed**: `.git/hooks` holds only `*.sample`
   files and `core.hooksPath` is unset. So the only tool-neutral enforcement is GitHub CI
   (`.github/workflows/qa.yml`, `release-gate.yml`) plus the plain scripts the daemon ships (`mkplan.bash`,
   `bin/hooks-daemon`), which an opencode agent can run but is never forced to.

---

## 2. What each tool reads

### 2.1 opencode v2.1.2: config files and directories

**Config discovery** (`packages/core/src/config/discovery.ts` L59-145):

- Project config files are named `opencode.json` and `opencode.jsonc` (L12).
- Starting at the location directory, opencode walks upward with `fs.up({ targets: ["."] })` (L80). No `stop` is
  passed, so the walk goes to the filesystem root (`packages/util/src/fs-util.ts` L170-187). In **every ancestor** it
  probes `.claude`, `.agents`, `.opencode`, `opencode.jsonc` and `opencode.json` (L85). Global roots are filtered
  out (L102-108).
- How each kind of entry is used:
  - `direct`: the `opencode.json(c)` files, loaded as config documents (L124).
  - `project`: each `.opencode/` directory, loaded as a config directory (L125-128).
  - `claude`: `~/.claude` plus every project `.claude/`. These are compatibility roots and are used only for skills
    (L129-137).
  - `agents`: `~/.agents` plus every project `.agents/`, also compatibility roots for skills (L138-143).
- Global sources:
  - the system directory: `/etc/opencode`, `/Library/Application Support/opencode` or `%ProgramData%\opencode`
    (L28-32);
  - macOS MDM plists (L35-40);
  - the global config directory (`global.config`, `~/.config/opencode` per the docs, `config.mdx` L47);
  - `~/.claude` and `~/.agents` (L68-75).
- Load order and precedence (`packages/core/src/config.ts` L220-290), lowest to highest:
  1. managed policies;
  2. well-known org config;
  3. the global directory;
  4. `OPENCODE_CONFIG` (explicit);
  5. project `opencode.json(c)`;
  6. project `.opencode/`;
  7. `OPENCODE_CONFIG_CONTENT`;
  8. managed settings, which win.
- Environment switches (`packages/cli/src/server-process.ts` L121-133):
  - `OPENCODE_CONFIG_DIR` and `OPENCODE_DISABLE_PROJECT_CONFIG` / `OPENCODE_CONFIG_PROJECT_DISABLE`.
  - `OPENCODE_DISABLE_CLAUDE_CODE` or `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`: either one drops the `.claude` roots.

**Inside a config directory** (`.opencode/`, the global config directory or the system directory), these
subdirectories are scanned:

| Subdirectory                                                         | Purpose                                                | Citation                                                                                   |
| -------------------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `agent/`, `agents/` (`**/*.md`), `mode/`, `modes/` (`*.md`, primary) | Agents                                                 | `packages/core/src/config/plugin/agent.ts` L21-26, L163-174                                |
| `command/`, `commands/` (`**/*.md`)                                  | Slash commands                                         | `packages/core/src/config/plugin/command.ts` L140, L152-168                                |
| `skill/`, `skills/`                                                  | Skills                                                 | `packages/core/src/config/plugin/skill.ts` L86-91                                          |
| `plugin/`, `plugins/`                                                | Local JS/TS plugins                                    | `packages/core/src/plugin/source-directory.ts` L7; `config/plugin/source.ts` L57           |
| `themes/`                                                            | TUI themes                                             | `packages/tui/src/theme/discovery.ts` L7                                                   |
| `tools/`                                                             | Custom tools, per the docs (`custom-tools.mdx` L20-21) | **UNVERIFIED in v2**: no scanner for a `tool(s)` directory found under `packages/core/src` |

**Top-level `opencode.json` keys** (`packages/schema/src/config.ts` L28-113) include:

- `model`, `default_agent`, `permissions` (an ordered `{action, resource, effect}` array), `policies`, `agents`;
- `mcp` (`{timeout, servers}`), `skills` (extra paths or URLs), `commands`, `instructions` (paths, globs or URLs);
- `plugins`, `references`, `formatter`, `lsp`, `compaction`, `providers`, `experimental`.

v1 key spellings (`permission`, `agent`, `mode`, `plugin`, `tools`, `mcp.<name>`) are migrated by
`packages/core/src/config/normalize.ts` L118-298.

**Instructions** (`packages/core/src/config/plugin/instruction.ts`):

- **Global:** `<global.config>/AGENTS.md` (L41, L78-82).
- **Project:** **every** `AGENTS.md` from the location directory up to the walk's stop directory is loaded and stacked
  (L54-55, L84-94). The stop directory is `$HOME` when the location is under `$HOME`, otherwise the project root (L40).
  This differs from v1, where the first match won and the walk stopped at the worktree
  (`v1.19.3:.../instruction.ts` L122-133).
- **Configured:** `instructions` entries.
  - Relative globs are matched upward from the location to the project root (`fs.globUp`, L98-110).
  - Absolute and `~/` paths are supported (L99-104).
  - `http(s)` URLs are fetched once per config load, with a 5 s timeout (L143-171).
- **Lazy, by subdirectory:** after a successful `read` tool call, `AGENTS.md` files between the read file and the
  location root are injected as session instructions (`packages/core/src/tool/plugin/read.ts` L82-103). This is the
  opencode equivalent of Claude Code's on-demand loading of nested `CLAUDE.md` files. It looks for `AGENTS.md` only.
- **No `@import` expansion.** The docs say opencode "doesn't automatically parse file references in `AGENTS.md`" and
  suggest `instructions` instead (`rules.mdx` L137-147). No import parser exists in `instruction.ts`.

**MCP:** configured only in `opencode.json` under `mcp.servers.<name>`, in one of two forms:

- `{type:"local", command:[...], environment, cwd}`;
- `{type:"remote", url, headers, oauth}`.

The schema is `packages/schema/src/mcp.ts` L26-60. **`.mcp.json` is never read**: no occurrence of the string in any
`packages/**/*.ts`.

**Tool names** (`packages/core/src/tool/plugin/*.ts`, `export const name`): `read`, `write`, `edit`, `patch`, `glob`,
`grep`, `shell`, `webfetch`, `websearch`, `skill`, `subagent`, `todowrite`, `question`. The v1 names `bash` and `task`
migrate to `shell` and `subagent` (`packages/core/src/v1/config/migrate.ts` L29-30).

### 2.2 Claude Code

From the vendored docs (`memory.md`, `settings-reference.md`, `sub-agents.md`, `plugins*.md`):

- **Instructions:**
  - managed `CLAUDE.md`, `~/.claude/CLAUDE.md`, `./CLAUDE.md` or `./.claude/CLAUDE.md`, and `CLAUDE.local.md`;
  - nested `CLAUDE.md` loaded on demand;
  - `@path` imports, relative to the importing file, at most 4 hops, skipping code spans and fences (`memory.md`
    L110-122);
  - `.claude/rules/**/*.md`, unconditional or scoped by a `paths:` glob (`memory.md` L176-219);
  - `~/.claude/rules/`;
  - `AGENTS.md` per §1 finding 2 (v2.1.277+). Claude Code does **not** read anything under `.agents/` (`memory.md`
    L387).
- **Settings:** `.claude/settings.json` (shared), `.claude/settings.local.json`, `~/.claude/settings.json` and
  managed settings. These carry hooks, permissions (`Tool(specifier)` rules), `statusLine`, `enabledPlugins`,
  `plansDirectory`, `env` and so on.
- **Agents:** `.claude/agents/*.md` and `~/.claude/agents/`. Frontmatter includes `name`, `description`, `tools` (a
  comma list), `model` (an alias such as `sonnet`/`opus`/`haiku`/`inherit`, or a full ID), `color`, and so on.
- **Skills:** `.claude/skills/<name>/SKILL.md` and `~/.claude/skills/`. Frontmatter includes `allowed-tools`,
  `argument-hint`, `disable-model-invocation`, `user-invocable` and `model`. Bodies may use `$ARGUMENTS` and
  `${CLAUDE_SKILL_DIR}`.
- **Commands:** `.claude/commands/*.md`, legacy and now merged with skills.
- **MCP:** `.mcp.json` (`mcpServers.<name> = {command, args, env}` or `{type:"http", url}`) plus the settings files.
- **Plugins:** marketplaces and `enabledPlugins`.

---

## 3. Collisions and divergences

| Surface                                    | Claude Code                                                                 | opencode v2                                                                     | Shared file? | Effect in a dual repo                                                                                  |
| ------------------------------------------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------ |
| Root instructions                          | `CLAUDE.md`; `AGENTS.md` only if no `CLAUDE.md` (v2.1.277+)                 | `AGENTS.md` only (all ancestors stacked)                                        | `AGENTS.md`  | Must be `AGENTS.md`-canonical for opencode to see anything                                             |
| Imports                                    | `@path` expanded                                                            | **Not expanded**: `@path` arrives as literal text                               | n/a          | Content reached through `@` in `CLAUDE.md` is invisible to opencode; list it in `instructions` instead |
| Nested instructions                        | nested `CLAUDE.md`, and nested `AGENTS.md` when that dir has no `CLAUDE.md` | nested `AGENTS.md` after `read`                                                 | `AGENTS.md`  | Nested docs must also be `AGENTS.md`, or listed in `instructions`, which loads them **eagerly**        |
| Path-scoped rules                          | `.claude/rules/*.md` with `paths:`                                          | none                                                                            | no           | opencode can only load them unconditionally via `instructions`, losing the scoping                     |
| Skills                                     | `.claude/skills/*/SKILL.md`                                                 | the same dirs plus `.opencode/skills`, `.agents/skills`                         | **yes**      | Shared, with degradation (§3.1)                                                                        |
| Agents                                     | `.claude/agents/*.md`                                                       | `.opencode/agent(s)/**/*.md`                                                    | no           | Must be duplicated or generated; the frontmatter is incompatible (§3.2)                                |
| Commands                                   | `.claude/commands/*.md` (and skills)                                        | `.opencode/command(s)/**/*.md`                                                  | no           | Must be duplicated; templates are mostly compatible (§3.3)                                             |
| Permissions                                | `permissions.allow/deny/ask: ["Bash(git *)", "Edit(//tmp/**)"]`             | `permissions: [{action:"shell", resource:"git *", effect:"allow"}]`             | no           | Different tool vocabulary and shape; must be translated                                                |
| MCP                                        | `.mcp.json` `mcpServers`                                                    | `opencode.json` `mcp.servers`, `command` is an array, `environment`             | no           | Must be duplicated or generated                                                                        |
| Hooks                                      | `settings.json` `hooks` → shell forwarders                                  | JS/TS plugins in `.opencode/plugins/` (Task 1.1)                                | no           | Entirely separate mechanism                                                                            |
| Model IDs                                  | aliases (`sonnet`) or `claude-…` IDs                                        | `provider/model[#variant]` required (`packages/schema/src/config/model.ts` L18) | n/a          | A Claude `model: sonnet` fails opencode's schema                                                       |
| Status line, output styles, plansDirectory | settings keys                                                               | none                                                                            | no           | Claude-only                                                                                            |

### 3.1 Skills: same files, different readers

- **Frontmatter.** opencode keeps `name`, `description`, `metadata["opencode/autoinvoke"]` and
  `disable-model-invocation`. `disable-model-invocation: true` becomes `autoinvoke: false` (`skill-file.ts` L44-50).
  Unknown keys are ignored. Frontmatter with unquoted colons, which Claude Code accepts, is retried through a
  sanitiser (`packages/core/src/config/markdown.ts` L24-39).
- **Lost under opencode:**
  - `allowed-tools`, a per-skill tool grant;
  - `argument-hint` and `user-invocable`;
  - `model`;
  - `$ARGUMENTS` and `${CLAUDE_SKILL_DIR}` / `$CLAUDE_PROJECT_DIR` substitution. The skill tool emits the raw body
    plus a "Base directory for this skill" line (`packages/core/src/skill.ts` L36-53). No substitution code was found;
    treat it as **UNVERIFIED that no substitution happens elsewhere**.
- **Loose top-level markdown.** In a skills root, any `.md` at depth 0 that is not inside a skill directory becomes a
  skill whose ID is the filename (`skill-scan.ts` L34-37, `skill-file.ts` L44-47). Directories holding a `SKILL.md`
  stop the descent (L29-33), so supporting files such as `hooks-daemon/optimise.md` are safe.
- **Duplicate roots.** Pointing `.opencode/skills` at `.claude/skills` (for example with a symlink) loads each skill
  twice, through two plugins: `ConfigSkillPlugin` and `ConfigCompatibilityPlugin`. Which copy wins is **UNVERIFIED**.
  Do not do it: `.claude/skills` is already read.

### 3.2 Agents: incompatible frontmatter

- **Native schema.** opencode's native agent schema has `model`, `request`, `system`, `description`, `mode`, `hidden`,
  `color`, `steps`, `disabled` and `permissions` (`packages/schema/src/config/agent.ts` L11-26).
- **Legacy decode.** Any other frontmatter key, such as Claude's `name`, switches the file to the v1 decoder
  (`packages/core/src/config/plugin/agent.ts` L185, L195-202). In the v1 decoder `tools` must be an **object** of
  booleans (`packages/core/src/v1/config/agent.ts` L21). A Claude `tools: Read, Glob, Grep` string fails it, the
  decode returns nothing, and the **agent is silently dropped** (`agent.ts` L203).
- **Model field.** A Claude `model: sonnet` would also fail the model selection pattern.
- **Name and prompt.** opencode takes the agent name from the file path (L179-183) and the body becomes `system`.
- **Tool vocabulary.** Even in a translated agent, the names differ: `Read` vs `read`, `Bash` vs `shell`, `Task` vs
  `subagent`.

### 3.3 Commands

The opencode command schema is `template`, `description`, `agent`, `model`, `subagent` and `subtask`
(`packages/schema/src/config/command.ts` L7-14).

- **Placeholders:** `$ARGUMENTS`, `$1..$n` and shell interpolation with `` !`cmd` `` (`command.ts` L185-246). These
  match Claude Code's command placeholders.
- **Frontmatter:** Claude-only keys (`allowed-tools`, `argument-hint`) are ignored, because unknown fields are
  dropped by `Schema.Class` decode (**UNVERIFIED** that the decode is non-strict). A `model:` alias makes the
  command fail to decode.

---

## 4. Single-source-of-truth strategies

| Strategy                                                                                                    | Claude Code                                                                                                                                                      | opencode v2                                                                                                                       | Verdict                                                                                                                 |
| ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **A. `AGENTS.md` canonical; `CLAUDE.md` = `@AGENTS.md` plus Claude-only extras**                            | Reads `CLAUDE.md`, expands the import (all versions)                                                                                                             | Reads `AGENTS.md`                                                                                                                 | **Works for both today.** This is what the Claude docs recommend (`memory.md` L449-459)                                 |
| B. `AGENTS.md` only, no `CLAUDE.md`                                                                         | Reads it natively on v2.1.277+. Not before that, and not with the built-in plugin disabled (`memory.md` L420-428). `InstructionsLoaded` hooks do not fire (L436) | Reads it                                                                                                                          | Works, but loses `InstructionsLoaded`, which this daemon registers, and depends on the version                          |
| C. `CLAUDE.md` canonical; `opencode.json` `"instructions": ["CLAUDE.md", ...]`                              | Unchanged                                                                                                                                                        | Reads it eagerly. `@` imports are not expanded, and nested and `.claude/rules` files must each be listed and load unconditionally | Works for root content only. Leaks Claude-specific guidance (tool names, `Task`, hooks) into opencode                   |
| D. Symlink `AGENTS.md` → `CLAUDE.md` (or the reverse)                                                       | Reads once (`memory.md` L446)                                                                                                                                    | Reads the target                                                                                                                  | Works, but the content is identical for both tools. No room for tool-specific sections. Symlinks are fragile on Windows |
| E. Generated files (one source rendered into `CLAUDE.md`, `AGENTS.md`, `.opencode/agents`, `opencode.json`) | Yes                                                                                                                                                              | Yes                                                                                                                               | The only route for **agents, permissions and MCP**, which have no shared format                                         |
| F. `.agents/skills/` as the neutral skills root                                                             | **UNVERIFIED**. Claude docs say `.agents/` is not read for instructions (`memory.md` L387); skills not checked                                                   | Reads it                                                                                                                          | Prefer `.claude/skills`, which both tools read                                                                          |

**Recommendation for the epic to evaluate:**

- Use A for instructions.
- Keep `.claude/skills` as the shared skills root.
- Generate (E) `.opencode/agents/*.md`, an `opencode.json` `permissions` block and `mcp.servers` from the Claude
  sources.
- Use `opencode.json` `instructions` globs only for the rules files that must apply always.
- This repository's `CLAUDE.md` has no `@` imports today (no `@…​.md` line in it), so A means moving content, not
  rewriting imports.

---

## 5. This repository, item by item

Inventory as of `dfdf77c8e`. There is no `AGENTS.md`, `.mcp.json`, `opencode.json(c)`, `.opencode/` or `.agents/`.
There is no `.claude/commands/`.

| Item                                                                                                                                                                                | What it is                                                                                            | opencode v2                                                                                                                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `CLAUDE.md` (≈118 KB, tracked)                                                                                                                                                      | Root instructions plus the generated `<hooksdaemon>` section (`core/claude_md_injector.py`)           | **does not see**                                                                                                                                                                                                                                                                   |
| 12 nested `CLAUDE.md` (`CLAUDE/`, `CLAUDE/Plan/`, `CLAUDE/development/`, `docs/`, `src/`, `tests/`, 4 under `src/claude_code_hooks_daemon/…`, `.claude/agents/`, `.claude/skills/`) | Directory-scoped instructions                                                                         | **does not see** (the read tool looks for `AGENTS.md` only)                                                                                                                                                                                                                        |
| `.claude/rules/*.md` (10 files, all with `paths:`)                                                                                                                                  | Path-scoped pointer rules from `install/directory_role_rules.py`                                      | **does not see**                                                                                                                                                                                                                                                                   |
| `.claude/settings.json` (tracked)                                                                                                                                                   | 30 hook events → `.claude/hooks/<event>` forwarders, `permissions.deny Edit(//tmp/**)…`, `statusLine` | **does not see**. No hook, deny rule or status line applies                                                                                                                                                                                                                        |
| `.claude/settings.local.json` (tracked here)                                                                                                                                        | `enabledPlugins` (defence-before-fix), allow rules, `plansDirectory: ./CLAUDE/Plan`                   | **does not see**. The DBF plugin's skills and agents are unavailable                                                                                                                                                                                                               |
| `.claude/hooks/*` (49 files)                                                                                                                                                        | Shell forwarders to the daemon socket                                                                 | **does not see** (never invoked)                                                                                                                                                                                                                                                   |
| `.claude/agents/*.md` (12 agents)                                                                                                                                                   | `name` + `tools: <comma list>` + `model: sonnet/opus/haiku`                                           | **does not see**. If copied or symlinked into `.opencode/agents/`, all 12 are **silently dropped** (§3.2)                                                                                                                                                                          |
| `.claude/agents/CLAUDE.md`                                                                                                                                                          | Directory doc                                                                                         | does not see. Via a `.opencode/agents` symlink it would become an agent named `CLAUDE` whose system prompt is the doc (no frontmatter → valid native decode)                                                                                                                       |
| `.claude/skills/<8 skills>/SKILL.md`                                                                                                                                                | acceptance-test, configure, docs-optimise, docs-qa, hooks-daemon, issue-sdlc, mode, release           | **sees**, partly **wrongly**. Names and descriptions load. `allowed-tools` and `argument-hint` are ignored. 7 files use `$ARGUMENTS` and/or `CLAUDE_*` variables that are not expanded. The bodies tell the agent to use Claude tool names and Claude-only behaviour (Task, hooks) |
| `.claude/skills/CLAUDE.md`                                                                                                                                                          | Directory doc                                                                                         | **sees wrongly**: becomes a phantom skill `CLAUDE` with no description (`skill-scan.ts` L34-37). Likely behaviour; confirm by running opencode                                                                                                                                     |
| `.claude/hooks-daemon.yaml`, `.claude/hooks-daemon/`, `.claude/project-handlers/`                                                                                                   | Daemon config, vendored daemon (client installs) and project handlers                                 | Inert data to opencode. The daemon only acts through Claude events                                                                                                                                                                                                                 |
| `.claude/ccy/`, status line                                                                                                                                                         | ccy PTY supervisor (wraps `claude`)                                                                   | does not see (Claude-specific launcher)                                                                                                                                                                                                                                            |
| `.claude/HOOKS-DAEMON.md`, `REMOTE-DOCS.md`                                                                                                                                         | Generated docs                                                                                        | does not see unless listed in `instructions`                                                                                                                                                                                                                                       |
| `CLAUDE/` tree (PlanWorkflow.md, QA.md, Plan/, …)                                                                                                                                   | Ordinary documentation                                                                                | Readable as files on request. Nothing auto-loads it                                                                                                                                                                                                                                |
| `CLAUDE/Plan/mkplan.bash`, `bin/hooks-daemon`, `bin/echd-capture`                                                                                                                   | Shell entry points                                                                                    | **Tool-neutral**: an opencode agent can run them if told to. Nothing makes it                                                                                                                                                                                                      |
| `~/.claude/skills`, `~/.claude/CLAUDE.md`                                                                                                                                           | User level                                                                                            | skills: **sees**. `CLAUDE.md`: **does not see** (v2)                                                                                                                                                                                                                               |

**Net effect:** an opencode v2 session started in `/workspace` today has the 8 skills (plus the phantom `CLAUDE`
skill), opencode's built-in agents and defaults, and **none** of the project's instructions, permissions, agents or
guards.

---

## 6. Deploy and install changes for an opencode-capable client (list only)

These are the things the installer writes today (modules under `src/claude_code_hooks_daemon/install/`), with what
an opencode-capable repository would additionally need:

01. **Instruction section.** `core/claude_md_injector.py` writes `<hooksdaemon>` into `CLAUDE.md`. It needs an
    `AGENTS.md` target (or a separate generated file listed in `opencode.json` `instructions`), with tool names
    rendered per host (`Write`/`Edit` vs `write`/`edit`/`patch`, `Bash` vs `shell`).
02. **Hook wiring.** `settings_merge.py` and `forwarder_generator.py` (`.claude/settings.json` hooks plus
    `.claude/hooks/*` forwarders) need an opencode counterpart: a deployed `.opencode/plugins/<daemon>.ts` that talks
    to the daemon socket, plus a merge into `opencode.json` `plugins`. Mechanism is Task 1.1 / 2.1.
03. **Agents.** `agent_assets.py` deploys to `.claude/agents/`. It would need a renderer to `.opencode/agents/*.md`
    with native frontmatter: `description`, `mode: subagent`, `model: provider/model`, a `permissions` array. Its
    md5 ownership ledger would need a second namespace.
04. **Skills.** `skills.py` deploys to `.claude/skills/`, which opencode already reads. It needs an audit of skill
    bodies for Claude-only tool names and variables. Directory docs such as `CLAUDE.md` must not sit loose in a skills
    root.
05. **Rules.** `directory_role_rules.py` writes `.claude/rules/*.md` with `paths:`. opencode has no equivalent.
    Options are to fold the rules into the `AGENTS.md` section, or to list them in `instructions` (eager).
06. **Core docs and the plan workflow.** `core_docs.py` and `plan_workflow.py` (`CLAUDE/PlanWorkflow.md`,
    `CLAUDE/Plan/` scaffolding, `mkplan.bash`) are tool-neutral files. The `plansDirectory` setting in
    `settings.local.json` has no opencode equivalent.
07. **Permissions.** Daemon-managed deny rules (for example `Edit(//tmp/**)`) need translating to `opencode.json`
    `permissions: [{action:"edit", resource:"/tmp/**", effect:"deny"}]`.
08. **Client-owned asset manifest.** `client_owned_assets.py` would list the new `.opencode/` paths and the generated
    `AGENTS.md` section.
09. **Bin wrapper.** `bin_wrapper.py` (`bin/hooks-daemon`) and the `remote-docs`/`reference-repos` CLIs are already
    host-neutral.
10. **Claude-only pieces.** `ccy_supervisor.py`, the status line and `relay_deploy.py` have no opencode role, except
    that the relay could serve a plugin transport (Task 2.3).
11. **Optional git hooks.** `pre-commit` and `commit-msg` hooks that invoke the existing commit gates would cover
    every tool (see §7). Today the daemon only *fixes the permissions* of client git hooks
    (`handlers/post_tool_use/git_hooks_executable_fixer.py`). It does not install any.
12. **Upgrade guides.** `upgrade_guides.py` and the `CLAUDE/UPGRADES` docs would need host-aware steps.

---

## 7. Tool-neutral layers: what already covers opencode

| Layer                                                                                                                                             | Present here?                                                       | Covers opencode?                                                   |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Git hooks (`.git/hooks`, `core.hooksPath`)                                                                                                        | **No**: only `*.sample` files, `core.hooksPath` unset               | n/a. **No protection lives in git hooks today**                    |
| Daemon "commit gates" (conflict markers, docs QA, plan QA, guard config, sensitive content, R-STAGED-LINT-FAILURE)                                | Yes, as **Claude `PreToolUse` Bash handlers** matching `git commit` | **No**. An opencode `shell` running `git commit` bypasses them all |
| Destructive-git, sed, pipe and stash blockers                                                                                                     | Claude `PreToolUse` handlers                                        | **No**                                                             |
| GitHub CI (`.github/workflows/qa.yml`: black, ruff, mypy, pyright, `llm_qa.py` docs_qa/plan_qa/changed tests, bandit, deptry; `release-gate.yml`) | Yes                                                                 | **Yes**. It runs on push and PR whatever tool authored the change  |
| `mkplan.bash` git-config counter (`hooksdaemon.latestPlanNumber`), `bin/hooks-daemon` CLIs, `scripts/qa/llm_qa.py`                                | Yes                                                                 | **Usable** by opencode, not enforced                               |

**Implication for the epic:** the cheapest tool-neutral protection is to re-host the existing commit-gate logic as
real git hooks. It is already pure functions over staged content. This would protect opencode, humans and every
other agent without any opencode integration. It complements, and does not replace, a `tool.execute.before`-style
opencode plugin for the pre-execution guards.

---

## 8. Gaps and unverified items

- The `.opencode/tools/` custom-tool directory is documented but no v2 scanner was found. **UNVERIFIED.**
- Whether opencode v2 expands `$ARGUMENTS` in skills, and which copy wins when the same skill ID loads from two
  roots. **UNVERIFIED.**
- Whether Claude Code reads `.agents/skills/`. **UNVERIFIED.** It was not checked against the vendored skills docs,
  which are not vendored.
- The phantom `CLAUDE` skill and the silent drop of Claude-format agents are derived from code reading. They were not
  observed by running opencode.
- The v1 (≤ v1.19.3) behaviour differs: it had a `CLAUDE.md` fallback and first-match instructions. Users still on v1
  would see this repository's root `CLAUDE.md`. Version pinning matters for any support claim.
