# Task 4.2: the AGENTS.md-only layout and an opt-in `multi_harness` mode

Intended path: `ANALYSIS-multi-harness-mode.md` in the plan folder. The Write tool refused that path from a
sub-agent, so the analysis was written here. The coordinator should move it.

The owner: "my understanding was that Claude Code will read AGENTS directly IF there is no CLAUDE.md file, so the work
would be to ensure there are no CLAUDE.md files and ONLY AGENTS.md files. I envisage an explicit opt-in to a 'multi
harness' mode for hooks daemon where this kind of rule would then kick in. Standard projects only using Claude Code
would have no changes, but projects explicitly opting into multi harness support would then get these kinds of checks."

**Short answer.** The owner is right. An AGENTS.md-only repository works in Claude Code 2.1.277+ at the root, and
nested `AGENTS.md` files load on Read. **A user-level `~/.claude/CLAUDE.md` does NOT switch it off**, not even when
the repository sits under `$HOME` (new probe H1, §1.2). The layout is **fragile, not broken**. A small set of other
files and settings silently switch it off: a `CLAUDE.local.md`, any `CLAUDE.md` above the repository (e.g.
`~/CLAUDE.md`), `/init`, `/memory`, a user or managed `claude-md` mode, and old Claude Code versions. Against the shim
it also loses nested loading on Write, Edit and Bash, and the `InstructionsLoaded` hook. Every one of those failures is
**detectable** by the daemon at SessionStart, and the two functional gaps can be **closed by the daemon**: a
`.claude/rules/` file for Claude-only content, and a handler that attaches nested `AGENTS.md` on Write and Edit. So the
recommendation is that `multi_harness` mode enforces the owner's AGENTS-only layout by default, with those
compensations, and accepts the shim as a declared alternative (§2.3). This amends rulings Q1.2, Q1.3 and Q1.5 and
widens M4 (§4).

Short names as in `FINDINGS.md`. AMD = `RESEARCH-claude-code-agents-md.md`; probe letters (a, c, d3, g2, ...) are AMD
§3. `memory.md` = vendored `remote-docs/code.claude.com/docs/en/memory.md` (fetched 2026-10-17). SRC = the
`cc-plugin-agents-md@builtin` source carved from the 2.1.308 binary
(`untracked/scratch/agentsmd-probe-out/plugin-src-b.txt` and `plugin-src-b-excerpt.txt`).

---

## 1. What an AGENTS.md-only repository gets in Claude Code 2.1.308

"AGENTS-only" here means: no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the repository, at any depth,
and none in any directory above it.

### 1.1 How the switch works (SRC)

The launch hook's test is `isClaudeProject`. It is true if the engine's instruction list already holds a
project-or-local CLAUDE file at or above the session root (`Hgr` = `isClaudeFileOnWalk`, which requires
`kind === "project" || kind === "local"`), or if `fs.ancestors({names: ["CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"]})` finds any. When it is true, the plugin adds no `AGENTS.md` files at launch. The nested function
(`ee()`) also returns nothing, for the whole session. When it is false, the plugin runs `fs.ancestors({names: ["AGENTS.md", ".claude/AGENTS.md"]})` and splices the results into the engine's `instructionFiles`. A user-level
`CLAUDE.md` has `kind` "user", so `Hgr` does not count it. Whether the host's `fs.ancestors` would still match
`~/.claude/CLAUDE.md` as the `.claude/CLAUDE.md` of the ancestor `~` could not be read from the source, so it was
probed (§1.2).

### 1.2 New probe for this task: user-level and home-directory files (2.1.308, `/context`, no auth)

The earlier probe h2 put the user `CLAUDE.md` in a throwaway `CLAUDE_CONFIG_DIR` that was **not** an ancestor of the
repository, so it did not settle the common case of a repository under `$HOME`. This probe sets `HOME` to a temp
directory instead, so the config dir defaults to `$HOME/.claude`, as on a real machine. Fixture
`/tmp/agentsmd-home-GuQZ`; outputs in `untracked/scratch/agentsmd-probe-out-home/`.

| #           | Fixture                                                                    | Memory Files at launch                               | Verdict                                                                                   |
| ----------- | -------------------------------------------------------------------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| H0          | `HOME=T`, repo `T/code/repo/AGENTS.md`, no user file                       | Project `AGENTS.md`                                  | Control                                                                                   |
| **H1**      | `HOME=T`, **`T/.claude/CLAUDE.md`**, repo `T/code/repo/AGENTS.md`          | User `T/.claude/CLAUDE.md` **+** Project `AGENTS.md` | **The user-level file does not disable AGENTS.md, even when the repo is under `$HOME`**   |
| H1 (nested) | H1 plus `sub/AGENTS.md`, `@sub/file.txt` mention, transcript inspected     | `sub/AGENTS.md` attached (`hook_additional_context`) | Nested loading also survives a user `CLAUDE.md`                                           |
| **H2**      | `HOME=T`, **`T/CLAUDE.md`** (home-root file), repo `T/code/repo/AGENTS.md` | Project `T/CLAUDE.md` **only**                       | **`~/CLAUDE.md` disables every AGENTS.md in every repo under `$HOME`** (same as probe g2) |
| H3          | `HOME=T/h3home` with `.claude/CLAUDE.md`, repo outside `$HOME`             | User `CLAUDE.md` + Project `AGENTS.md`               | Same as h2                                                                                |

This matches `memory.md` L380 ("Don't count, and keep loading alongside `AGENTS.md`: your `~/.claude/CLAUDE.md`, your
organization's managed `CLAUDE.md`, and `.claude/rules/` files"). The #1 risk the coordinator flagged is therefore
**refuted** for `~/.claude/CLAUDE.md`. It is **confirmed** for `~/CLAUDE.md`, which is a much rarer file but a real one.
Claude Code itself treats `~/CLAUDE.md` as a Project file of every repository under the home directory.

### 1.3 Gets and loses, point by point

| Point                                           | AGENTS-only repository (default `claude-md-or-agents-md` mode)                                                                                                                                                                                                                                                                                                                | Evidence                                          |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Root loading at launch                          | **Gets it.** Every `AGENTS.md` / `.claude/AGENTS.md` from cwd up to `/`, listed as `Project` in `/context`, like `CLAUDE.md`. Interactive sessions show `no CLAUDE.md found; AGENTS.md loaded: …`                                                                                                                                                                             | a, c5, d2, g; SRC; `memory.md` L384               |
| Launch from a subdirectory                      | Gets the ancestors and the cwd file (d2). But a `CLAUDE.md` in the launch directory or any ancestor drops them all (d3, d4)                                                                                                                                                                                                                                                   | d2, d3, d4                                        |
| Nested loading on **Read** and **`@`-mention**  | **Gets it**, including every intermediate level (d6). Delivered as `hook_additional_context` on the tool result, not as a `nested_memory` instruction file. `@`-mention attach needs 2.1.290+                                                                                                                                                                                 | d, d6, H1; changelog L1071                        |
| Nested loading on **Write / Edit / Bash read**  | **Loses it.** The plugin's `tool.call` filter is `{tool:"Read"}`. A native nested `CLAUDE.md` loads on Write, Edit and single-file `cat`/`head`. So an agent that edits `src/x/foo.py` without reading it first never sees `src/x/AGENTS.md`. SOURCE-DERIVED, not observed (no model run)                                                                                     | SRC; changelog L1238, L785; `memory.md` L385      |
| `@path` imports inside `AGENTS.md`              | **Gets it** (f). Difference: an import from outside the working directory is never prompted for; it loads only if external imports were already approved                                                                                                                                                                                                                      | f; `memory.md` L386, L438                         |
| `InstructionsLoaded` hook                       | **Loses it.** Fires nothing for a directly read `AGENTS.md` (3c case a). No daemon handler subscribes to the event today (it is named only in `handlers/registry.py`, `constants/events.py`, `core/handler_bases.py` and `config/models.py`, none of them a subscriber), so nothing in the daemon breaks. What is lost is the only positive "it loaded" signal a hook can get | AMD §3c; `memory.md` L436                         |
| User-level `~/.claude/CLAUDE.md`                | **Does not disable it.** Loads alongside, also for repos under `$HOME`, launch and nested (H1). `~/.claude/AGENTS.md` is not read (h1)                                                                                                                                                                                                                                        | H1, H3, h1, h2; `memory.md` L380                  |
| `~/CLAUDE.md` or any `CLAUDE.md` above the repo | **Disables it**, silently, for every repo below. Typical sources: a home-root `CLAUDE.md`, a monorepo or "workspace" parent folder with a `CLAUDE.md`                                                                                                                                                                                                                         | g2, H2                                            |
| `CLAUDE.local.md` (personal, gitignored)        | **Disables it** for that developer only, silently; no `AGENTS.local.md` replacement exists                                                                                                                                                                                                                                                                                    | i, i2; `memory.md` L389                           |
| Managed policy                                  | The managed `CLAUDE.md` loads alongside (does not count). A managed or user `instructionFiles: "claude-md"` (or `managed-only`) removes every `AGENTS.md`                                                                                                                                                                                                                     | c3; `memory.md` L380, L402                        |
| `.claude/rules/`                                | **Loads alongside and does not count** (j). Unconditional rules load at launch; path-scoped rules load on Read, Write, Edit and Bash read, and fire `InstructionsLoaded`. **This is the Claude-only channel an AGENTS-only repo can still use** (§3.4)                                                                                                                        | j, 3c case j; `memory.md` L198, L219              |
| `/init`                                         | **Hazard.** It always writes a `CLAUDE.md` (reads `AGENTS.md` only with `CLAUDE_CODE_NEW_INIT=1`). One `/init` in an AGENTS-only repo switches every `AGENTS.md` off for everyone once committed. Not probed (needs a model)                                                                                                                                                  | `memory.md` L476-480                              |
| `/memory`                                       | Lists a directly read `AGENTS.md` (2.1.280+). **Hazard:** it also lists "project CLAUDE.md entries for files that don't exist yet", and selecting one creates it, with the same effect as `/init`. Docs only                                                                                                                                                                  | `memory.md` L576, L618                            |
| Compaction                                      | Root: SOURCE-DERIVED yes. The plugin splices `AGENTS.md` into `instructionFiles` on every `prompt.context`, and `session.compact` resets its "given" set so nested files reload on the next Read. Native root `CLAUDE.md` is re-read from disk after `/compact` (`memory.md` L636). **Not probed** (needs a model)                                                            | SRC; `memory.md` L636                             |
| Subagents and forks                             | Same as `CLAUDE.md`: subagents that load project instructions load these; forks inherit the given set                                                                                                                                                                                                                                                                         | SRC `agent.spawn`; `memory.md` L386               |
| `--add-dir`                                     | **Loses it**: an added directory's `AGENTS.md` never loads, even with `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD`                                                                                                                                                                                                                                                          | `memory.md` L437                                  |
| `claude-md-and-agents-md` setting               | User, `--settings` or managed scope only; a project setting is ignored (c4). Not needed for AGENTS-only; it matters only where a `CLAUDE.md` also exists                                                                                                                                                                                                                      | c2, c4; `memory.md` L404                          |
| Versions and session types                      | Needs 2.1.277+ (2.1.290+ for the `@`-mention fix); no `AGENTS.md` before 2.1.281 on Bedrock, Vertex, Foundry, gateways or with telemetry off; not in the first session after upgrading from ≤ 2.1.276; off under `CLAUDE_CODE_SIMPLE` (nested also under `CLAUDE_CODE_DISABLE_ATTACHMENTS`); off if the plugin is disabled in `/plugin`                                       | changelog L2281, L1977; `memory.md` L420-428; SRC |
| HTML-comment stripping, `claudeMdExcludes`      | Docs say `claudeMdExcludes` applies. Stripping UNVERIFIED. Neither probed                                                                                                                                                                                                                                                                                                     | `memory.md` L386; AMD §6                          |

### 1.4 Cheap probes still worth running (in order)

1. **Done in this task:** the `~/.claude/CLAUDE.md` case (H1). Settled: it does not disable AGENTS.md.
2. **Model-dependent behaviour without a login.** Point `ANTHROPIC_BASE_URL` at a local stub HTTP server that logs
   each request body and returns a canned assistant message (and a canned `tool_use` where needed). The request body
   then shows exactly which instruction text reached the model. That settles, with no account: nested `AGENTS.md` on
   Write, Edit and Bash `cat` (expected absent); root `AGENTS.md` after `/compact` (expected present); what `/init`
   writes. UNVERIFIED that `-p` accepts a stub base URL with no auth; `ANTHROPIC_API_KEY=dummy` should satisfy it.
3. **`/memory` on an AGENTS-only repo:** is a `CLAUDE.md` row offered, and does selecting it create the file? Needs an
   interactive PTY, but no model.
4. **A gitignored `.claude/rules/personal.md`:** confirm it loads beside `AGENTS.md`. This is the proposed
   replacement for `CLAUDE.local.md` (§3.3). Expected yes, since rules are plain files (j).
5. **The daemon's nested-attach handler** (§3.4): confirm that a PostToolUse `additionalContext` on Write and Edit
   reaches the model, and that it is not duplicated when the plugin also attaches the same file on a later Read.

---

## 2. AGENTS-only against the shim (`CLAUDE.md` = `@AGENTS.md`)

### 2.1 Point by point

| Point                                          | AGENTS-only                                        | Shim in every directory with an `AGENTS.md`                                        |
| ---------------------------------------------- | -------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Root launch load                               | Yes (2.1.277+)                                     | Yes, every version (f2)                                                            |
| Nested on Read / `@`                           | Yes (plugin context attachment)                    | Yes (native `nested_memory`, k)                                                    |
| Nested on Write / Edit / Bash read             | **No** (closable by the daemon, §3.4)              | Yes (native)                                                                       |
| `InstructionsLoaded`                           | **No**                                             | Yes (`include`, 3c f2)                                                             |
| `~/.claude/CLAUDE.md`                          | Unaffected (H1)                                    | Unaffected                                                                         |
| `~/CLAUDE.md` / parent `CLAUDE.md`             | **Disables everything**                            | Unaffected: native loads both (e)                                                  |
| `CLAUDE.local.md`                              | **Disables everything** for that developer         | Unaffected: native loads it beside the shim                                        |
| User/managed `claude-md` mode                  | **Disables everything**                            | Unaffected (the shim is a `CLAUDE.md`)                                             |
| Old versions, Bedrock < 2.1.281, first session | **Nothing loads**                                  | Unaffected                                                                         |
| `/init`, `/memory`                             | **Creating a `CLAUDE.md` silently flips the repo** | Harmless: they edit the shim, and a drift check catches shared content added there |
| `--add-dir`                                    | Not loaded                                         | Loaded (native)                                                                    |
| Claude-only content                            | `.claude/rules/*.md` (§3.4)                        | Below the import in the shim                                                       |
| Files per directory                            | One                                                | Two; the shim can drift (AMD §5 check (c))                                         |
| opencode, Codex                                | Read `AGENTS.md`                                   | Read `AGENTS.md`; opencode ignores `CLAUDE.md` (DUAL §1)                           |
| Owner's stated rule ("ONLY AGENTS.md")         | Meets it                                           | Does not                                                                           |

### 2.2 The pattern

The shim is **robust by construction**: it needs no plugin, no version and no setting, and nothing a developer adds
switches it off. AGENTS-only is **correct only while a set of conditions holds**, and every violation fails
**silently**: the session just runs without instructions. With nothing else in place that would breach the owner's
no-silent-fallback rule. But every condition in the AGENTS-only column is either a file on disk, a settings value or a
version. The daemon can read all of them at SessionStart, and it can deny the edits that would create the bad files.
That turns "fragile and silent" into "fragile and loud". The remaining functional losses are nested Write/Edit loading
and `InstructionsLoaded`. The first can be closed (§3.4). The second costs nothing today, because no handler uses it.

### 2.3 Recommendation

**`multi_harness` mode enforces AGENTS-only by default, and accepts `shim` as a declared alternative.** One key,
`instruction_layout: agents-only | shim`, default `agents-only` when the mode is on.

- **Why AGENTS-only by default.** It is the owner's direction. It has one file per directory and no drift surface,
  which is SYNC's main lesson: copies drift, and the shim is a second file. And the daemon can make every one of its
  failure modes loud (§3.3). In a pure-Claude project those failures would be silent; in an opted-in project they are
  not, which is the point of opting in.
- **Why keep `shim` as an option and not ban it.** Some teams need instructions in sessions the fallback does not
  serve: Bedrock or Vertex on old versions, pinned Claude Code below 2.1.290, or developers who must keep a
  `~/CLAUDE.md` (H2). The daemon cannot fix those, only report them. For such a team the shim is the only
  silent-failure-free layout. It also gives the daemon positive `InstructionsLoaded` evidence. The checks differ by
  layout (§3.3). Projects that ran the Q1 migration under the old ruling keep working by declaring `shim`.
- **Not both at once in one repository.** A mixed tree is exactly the d3/d4/k failure: one `CLAUDE.md` silences every
  unshimmed `AGENTS.md`. The layout is declared once, and the checks enforce that single layout.

---

## 3. The `multi_harness` mode

### 3.1 Opt-in shape, and how it relates to M4's `hosts:`

M4 already rules a `hosts:` key, default `claude-code` only. The owner's "multi harness" is that same switch seen from
the project's side. Two keys would be two truths, so the proposal is **one block**, where `hosts:` lives inside it:

```yaml
# .claude/hooks-daemon.yaml
multi_harness:
  enabled: true                    # the explicit opt-in; absent or false = today's behaviour exactly
  hosts: [claude-code, opencode]   # M4's key, moved here; claude-code is implicit and cannot be removed
  instruction_layout: agents-only  # or: shim
  agents_md_max_bytes: 30000       # budget under Codex's 32 KiB project_doc_max_bytes (SYNC §2)
```

- `enabled: false` (or no block) is the **standard Claude-Code-only project**. A top-level `hosts:` without the block
  is rejected by config validation with a message naming the block. That way two shapes never coexist.
- `hosts` can list `codex` before the daemon has an adapter for it. Then the mode delivers the layout, size budget and
  instruction checks for it, and the startup report says the host has instructions but no guards. That is honest about
  what is enforced.
- Plans 3 to 6 (the opencode plugin, rendering, autonomy) deploy only when `opencode` is in `hosts`. Plan 2 (the
  layout and its checks) needs only `enabled: true`.

### 3.2 Non-opted projects: zero change

This is the contract, and it is testable as such. With the mode off, a project gets: no new handler is active; no new
SessionStart lines; no advisories about `AGENTS.md`, `CLAUDE.local.md` or parent files; no generated files (no
`AGENTS.md`, no `.claude/rules/` additions, no `opencode.json`, no `.opencode/`); no git hooks; no change to the
`<hooksdaemon>` block's location or content; and the installer still writes `CLAUDE/Plan/CLAUDE.md` as today
(`install/plan_workflow.py` L291-299). The new handlers are registered disabled and gated on the config flag, not just
quiet. An integration test should install into a fixture with the mode off and assert a byte-identical tree and
identical SessionStart output against the previous release.

This **retracts** ruling Q1.2 (new installs default to `AGENTS.md` plus shims) and the "one-line advisory" half of
Q1.5 (§4).

### 3.3 What switches on when opted in

Each item notes the layout it applies to (A = agents-only, S = shim).

**Layout checks (SessionStart report and commit gate).**

| Check                                                                                                                     | A                                                               | S                       | When                 |
| ------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------- | -------------------- |
| Any tracked `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md`, any depth                                              | **deny commit**; report                                         | n/a                     | commit, SessionStart |
| A `CLAUDE.md` beside an `AGENTS.md` that does not import it; an `AGENTS.md` with no shim (AMD §5 (a), (b))                | n/a                                                             | **deny commit**; report | commit, SessionStart |
| Shared content in a shim (AMD §5 (c))                                                                                     | n/a                                                             | report; deny on commit  | commit               |
| An untracked `CLAUDE.local.md` or `CLAUDE.md` on disk in the repo (personal file)                                         | **loud SessionStart error** naming the file and the fix         | report                  | SessionStart         |
| `CLAUDE.md` / `.claude/CLAUDE.md` / `CLAUDE.local.md` in any ancestor above the git root (g2, H2)                         | **loud SessionStart error** (instructions are OFF this session) | info                    | SessionStart         |
| Effective `instructionFiles` mode from `~/.claude/settings.json` and managed settings is `claude-md` or `managed-only`    | **loud error**                                                  | info                    | SessionStart         |
| Claude Code version < 2.1.290, `CLAUDE_CODE_SIMPLE` or `CLAUDE_CODE_DISABLE_ATTACHMENTS` set, plugin disabled in settings | **loud error** (or a warning for the nested-only switches)      | n/a                     | SessionStart         |
| `AGENTS.md` over `agents_md_max_bytes` (root plus the files concatenated on the root-to-cwd path, as Codex does)          | deny commit; report                                             | same                    | commit, SessionStart |
| A generated per-harness file out of sync with its source (D1 ledger)                                                      | deny commit; report                                             | same                    | commit, SessionStart |

The SessionStart checks use only facts the daemon can already read: files on disk, the user and managed settings
JSON, and the Claude Code version, which `contract_staleness` already reads. A `--settings` flag is not visible to it;
the report says so once rather than claim certainty.

**Edit guards (PreToolUse, Write/Edit, plus the Bash redirect detection the daemon already has).**

- A: **deny creating** any `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` anywhere in the repository. The deny
  names the target: `AGENTS.md` for shared content, `.claude/rules/<name>.md` for Claude-only content, and a gitignored
  `.claude/rules/personal.md` for personal notes. This also covers `/init` and `/memory` when they write through the
  tools. UNVERIFIED whether they do; if they write natively, the SessionStart and commit checks catch the file instead.
- S: deny shared content added to a shim (E1), and deny an edit to a generated file, naming its source (E1).
- A and S: the Claude-only content guard on `AGENTS.md` (E2: Claude tool names, `CLAUDE_*` variables, `@` imports of
  `.claude/` files). It uses one token-list classifier, shared with the migrate command (RULINGS Q1.4).
- `validate_instruction_content` (today: `CLAUDE.md` and `README.md` only, L207-208) extends to `AGENTS.md` when the
  mode is on.

**Git hooks.** M1 unchanged. Opt-in `core.hooksPath`, offered as part of enabling the mode. It runs the same commit
gates for commits made by opencode, Codex or a human, since those never pass through Claude's PreToolUse.

**Generated per-harness config.** Plan 5 (D1), only for hosts listed in `hosts`. Every generated file is recorded in
the md5 ownership ledger and checked for drift (above).

### 3.4 Delivering the daemon's own guidance in this mode

Today `ClaudeMdInjector` (`core/claude_md_injector.py`) writes the `<hooksdaemon>` block into the root `CLAUDE.md`
(118,604 bytes for this repository) and auto-commits it. In the mode:

1. **The shared part goes into `AGENTS.md`** inside the same `<hooksdaemon>` delimiters. It is the compact,
   host-neutral form required before any of this ships (RULINGS Q1.6): rule IDs with one-line rules, neutral tool
   vocabulary ("file-write tools", "the shell tool"), and depth behind `bin/hooks-daemon explain-rule`. It must fit the
   size budget together with the project's own text. The injector refuses (loud, non-zero, no partial write) if it
   would not.
2. **The Claude-only part goes into `.claude/rules/hooks-daemon.md`** (A), generated, unconditional and with no
   `paths:` field. Rules load at launch beside `AGENTS.md` without counting as a CLAUDE file (j, `memory.md` L380), they
   are re-read like project instructions, they fire `InstructionsLoaded`, and opencode does not read `.claude/rules/`
   (FINDINGS §2 "Shared config"). Examples of Claude-only content: Task/Agent dispatch rules, status line, crons,
   `/goal`. In S it goes below the import in the root shim instead. The daemon already deploys `.claude/rules/` files
   (`install/directory_role_rules.py`), so this is an existing channel, not a new kind of write.
3. **Nested gap closure (A).** A new PostToolUse handler on Write and Edit (and on Bash single-file reads, where the
   daemon already parses the path). For the touched file, it attaches every `AGENTS.md` between that file's directory
   and the root that this session has not yet seen, as `additionalContext`. The handler keeps its own "given" set per
   session, cleared on compaction. That restores the native trigger set the plugin lacks (§1.3). Unprobed (§1.4 item 5).
   An alternative, generated path-scoped rules that `@`-import each nested `AGENTS.md`, also gets native triggers, but
   it adds a generated file per directory and a duplication risk. Not recommended.
4. **Positive load verification (A).** No hook fires for `AGENTS.md`. But the rules file from item 2 fires
   `InstructionsLoaded`, so a small handler can confirm that project instructions loaded this session. If the
   SessionStart checks passed and yet no `AGENTS.md` effect is observable, it reports. This is the evidence the shim
   gave for free.
5. **The daemon's own nested files.** The installer writes `CLAUDE/Plan/CLAUDE.md` into clients (`plan_workflow.py`
   L291-299). In A it writes `CLAUDE/Plan/AGENTS.md` instead. In this repository the 12 nested `CLAUDE.md` files
   (including `.claude/agents/CLAUDE.md` and `.claude/skills/CLAUDE.md`) become `AGENTS.md`. The two under `.claude/`
   instead become `.claude/rules/` path-scoped files or `README.md`: they are Claude-only, and a loose
   `.claude/skills/CLAUDE.md` is already a phantom skill in opencode (DUAL §8). A `.claude/skills/AGENTS.md` would be
   no better, so it is not an option there.

### 3.5 The migrate command

`bin/hooks-daemon multi-harness enable` (the only way in), with `--dry-run` as the default and `--apply` to act. It
replaces the earlier `migrate-agents-md` name, because enabling the mode and migrating are one act.

1. Writes the `multi_harness:` block. Prints the plan: every file to move, create or delete, and every byte that
   changes place.
2. Moves each `CLAUDE.md`'s shared content to a sibling `AGENTS.md`. Claude-only content (the classifier) goes to
   `.claude/rules/` (A) or stays in the shim (S). The `<hooksdaemon>` block is regenerated, not moved.
3. A: `git rm` each `CLAUDE.md`; S: rewrites it as a shim.
4. Offers the M1 git hooks and, per listed host, the D1 renders.
5. **Refuses**, non-zero and naming the file, on any of these: a `CLAUDE.local.md` (A); an ancestor `CLAUDE.md` above
   the git root (A, since instructions would be off for that user immediately); a size-budget breach; a classifier
   result it cannot place; a dirty tree. It never drops content: the dry run lists every source byte range and its
   destination, and `--apply` verifies the total afterwards.
6. `multi-harness disable` is the inverse. It restores `CLAUDE.md` from `AGENTS.md` and the rules file. Leaving the
   mode is as explicit as entering it.
7. Never run by an upgrade (RULINGS Q1.1). This repository dogfoods it first (Q1.6).

### 3.6 Fail-loud behaviour

- Every condition in §3.3's SessionStart rows that **turns instructions off this session** is reported as an error in
  the session banner and in `bin/hooks-daemon status`. It is not a once-per-day advisory. The message names the file
  or setting and the exact fix.
- **No silent compensation by default.** The daemon could inject `AGENTS.md` through SessionStart context when it
  detects the fallback is off. `memory.md` warns that this duplicates content when the fallback works, and it would be
  a silent fallback. Proposed: only behind an explicit `on_fallback_disabled: inject` key, off by default, and the
  banner still states that it fired.
- Config errors (unknown layout, `hosts` without `claude-code`, a top-level `hosts:`) fail the daemon's config load
  loudly, like any other invalid config.
- A guidance block that does not fit the budget refuses to write (§3.4.1). It never truncates.

---

## 4. Amendments the rulings need

| Ruling                            | Today                                                                             | Amend to                                                                                                                                                                                                                                                                                                                                                   |
| --------------------------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Q1 headline**                   | "Migrate by explicit per-project command"                                         | "Enabling `multi_harness` mode is the only route; `multi-harness enable` is that command (dry run by default)"                                                                                                                                                                                                                                             |
| **Q1.2**                          | New installs default to `AGENTS.md` plus shims; `layout: claude-md-only` opts out | **Retract.** New installs are unchanged (`CLAUDE.md`). The installer *offers* the mode; it never defaults to it. `layout: claude-md-only` is dropped (mode off is that)                                                                                                                                                                                    |
| **Q1.3**                          | "The shape is the shim, root and nested"                                          | "`instruction_layout: agents-only` (default in the mode; no CLAUDE files anywhere; Claude-only content in `.claude/rules/`; nested Write/Edit gap closed by a daemon handler) or `shim` (declared alternative). Never mixed." Cite H1 (user `CLAUDE.md` is harmless) and H2/g2/i (what is not)                                                             |
| **Q1.4**                          | Claude-only content stays in the shim                                             | "...stays in the shim (S) or moves to `.claude/rules/hooks-daemon.md` / project rule files (A)"                                                                                                                                                                                                                                                            |
| **Q1.5**                          | Checks enforced where the layout exists; one-line advisory elsewhere              | "Checks run **only** when the mode is on. Off = zero output." Add the per-layout check table (§3.3), including the ancestor, `CLAUDE.local.md`, mode-setting and version checks                                                                                                                                                                            |
| **Q1.6**                          | Compact neutral guidance before migration                                         | Unchanged. Add: the Claude-only remainder goes to `.claude/rules/hooks-daemon.md` in A                                                                                                                                                                                                                                                                     |
| **Q1.7**                          | Refuse on `CLAUDE.local.md`, a shadowing parent `CLAUDE.md`, size                 | Unchanged. Add: refuse on a classifier result it cannot place, and on a dirty tree. Add the `disable` inverse                                                                                                                                                                                                                                              |
| **M4**                            | Top-level `hosts:`, default `claude-code`                                         | `hosts` lives **inside** `multi_harness:`. With the mode off, the project is Claude-Code-only and unchanged. A top-level `hosts:` is a config error. The "no opencode protection" startup line M4 describes fires only when the mode is on and `opencode` is listed but not deployed; with the mode off, nothing is reported (retracts its always-on half) |
| **M1**                            | Git hooks opt-in for existing clients, offered for new                            | "Offered as part of `multi-harness enable`; never installed with the mode off." The once-per-session "commit gates are Claude-Code-only" line also only shows in the mode                                                                                                                                                                                  |
| **FINDINGS §4 Q1 row, §5 plan 2** | Shims; new-install default; drift checks with advisory fallback                   | Rewrite plan 2 as "`multi_harness` mode: config block, layout checks, guards, guidance delivery (§3.4), enable/disable command, zero-change test". Item 3 (shims) becomes "layout per §2.3". This is Task 4.3's job                                                                                                                                        |
| **FINDINGS §6 item 9**            | Nested Write/Edit/Bash unprobed                                                   | Add the stub-`ANTHROPIC_BASE_URL` probe method (§1.4 item 2) and note H1 settled the user-level question                                                                                                                                                                                                                                                   |

Q2, Q3, Q4, M2, M3 and M5 need no change. M5 (naming) gains one data point: "multi harness" is the owner's own term
for the opt-in, which leans toward option (b)'s vocabulary without requiring the rename.

---

## 5. Gaps

- No model-backed run: nested Write/Edit/Bash, compaction, `/init` and `/memory` behaviour are from source and docs.
  §1.4 item 2 gives an auth-free method.
- The PostToolUse nested-attach handler (§3.4.3) and the `InstructionsLoaded` verification (§3.4.4) are designs. Their
  feasibility in Claude Code's PostToolUse context and de-duplication against the plugin are unprobed.
- Whether `/init` and `/memory` create `CLAUDE.md` through the Write tool (and so through the daemon's guard) or
  natively is unknown.
- Probe fixtures under `/tmp/agentsmd-home-GuQZ` (including a throwaway `.claude/projects` transcript) remain; remove
  by hand.
