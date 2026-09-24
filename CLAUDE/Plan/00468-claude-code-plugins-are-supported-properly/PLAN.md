# Plan 00468: claude code plugins are supported properly

**Status**: In Progress
**Created**: 2026-09-24
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Dogfooding the Defence Before Fix plugin (Plan 00467) showed that the daemon
barely knows Claude Code plugins exist. A plugin-support audit
([report](../00467-recommend-the-defence-before-fix-plugin-to-client-projects/subagent-reports/260924-plugin-audit-opus-5-5.md))
found 8 defects, 3 of them release-blocking, and 16 gaps:

- The shipped settings template would have enabled the plugin in every
  client.
- Plugin agents are invisible to the read-only dispatch logic.
- The markdown formatter would rewrite installed plugin files.
- `lsp_enforcement` claims an LSP is available on the strength of an
  environment variable.
- Plugin hooks bypass the daemon's hooks policy without a word.

The owner's direction was: "we have to support plugins properly … no known
defects". So every finding is fixed here. Each P and G number below is the
audit's numbering.

Most findings need the same missing piece: one resolver for the Claude
config directory and the plugins enabled in it (G13). That resolver comes
first, and the other fixes build on it.

## Goals

- No daemon default ships a plugin to a client, and a test enforces it.
- The daemon knows which plugins are enabled, at which scope, and what
  agents, skills, hooks and LSP servers they bring. Every handler that
  reasons about agents, skills, hooks or LSP uses that knowledge.
- No daemon walker or guard edits, lints or misjudges an installed plugin
  or the Claude config directory.
- A client can read how the daemon and Claude Code plugins coexist.

## Non-Goals

- Recommending a plugin to clients. That is Plan 00467 Phase 2, and it
  stays gated on owner sign-off.
- The daemon's own `plugins:` handler modules. G5 only fixes the name clash.

## Tasks

### Phase 1: nothing plugin-related ships to clients (P1, G6)

- [x] ✅ **Task 1.1**: Move the dogfood install to local scope. The two
  plugin keys are now in the tracked `.claude/settings.local.json`, which no
  installer ships, and `.claude/settings.json` is restored byte-for-byte to
  its content before the install.
- [x] ✅ **Task 1.2**: A test fails when the shipped settings template carries
  `enabledPlugins` or `extraKnownMarketplaces`, on every install and upgrade
  route (shell copy, three-way merge, Python generator). Review
  `plansDirectory` under the same rule. Add a SELF_INSTALL.md line saying
  that `.claude/settings.json` ships to clients (G6). **Decided (unattended,
  2026-09-24)**: `plansDirectory` is dogfood-only (the plan workflow is
  opt-in and its directory configurable), so it moved to
  `settings.local.json` and the test covers it too.

### Phase 2: one resolver for the config dir and enabled plugins (G13, P2, P6, P7, G11, G12, G14, G15)

- [x] ✅ **Task 2.1**: `claude_config_dir()`, and an enabled-plugins resolver
  that reads `installed_plugins.json` and `enabledPlugins` per scope, honours
  `projectPath` for project scope, and lists each plugin's agents, skills,
  hooks and LSP servers. `project_containment` (G10's docstring) and every
  later task use it.
- [x] ✅ **Task 2.2**: `subagent_tool_resolution` gains a plugin tier with
  scoped ids (P2). A YAML failure falls back to a lenient frontmatter parser
  (P6). The resolver returns the frontmatter, so `agent_isolation_advisor`
  honours `isolation: worktree` (P7). The size blocker's path is sanitised
  (G12).
- [x] ✅ **Task 2.3**: The LSP exclude advice and skill-reference checks
  derive the config dir (G11). `skill-scan` knows plugin and user skills
  (G14). `tool-report` sums enabled plugins' always-on cost (G15).
  **Decided (unattended, 2026-09-24)**: `check_skill_references.py` keeps
  its `ccy` name exclusion beside the derived one, because `.claude/ccy/`
  also holds tracked supervisor files that CI does not scan today.
- [x] ✅ **Task 2.4**: File the upstream DBF issue: both agents lack `Write`
  but are told to write a report. Filed as
  [Defence-Before-Fix/claude-plugin#3](https://github.com/Defence-Before-Fix/claude-plugin/issues/3).

### Phase 3: walkers and path guards leave plugin trees alone (P3, P4, G8, G10, G16)

- [ ] ⬜ **Task 3.1**: `format-markdown`, `housekeeping` and
  `find-comment-blocks` walk git-visible files through the shared helper from
  00466 N9, and always exclude an in-project config dir (P3).
- [x] ✅ **Task 3.2**: `markdown_organization` classifies the raw path
  before resolving it: the Claude config dir is exempt from the project
  layout rules, and the memory policy is unchanged (P4). A plugin root is
  recognised by `.claude-plugin/plugin.json` or `marketplace.json`, and its
  component markdown is allowed (G8).
- [ ] ⬜ **Task 3.3**: An advisory on writes under the installed plugin cache
  or marketplaces (G16). `project_containment` reads the Claude home per
  session (G10).

### Phase 4: plugin hooks and LSP plugins (G1, G2, G7, G9, P5)

- [ ] ⬜ **Task 4.1**: A SessionStart advisory, and a `health` line, name
  each enabled plugin that ships hooks, singling out PreToolUse hooks and
  their `updatedInput` power, with a per-plugin acknowledgement (G1, G2).
  Document the limit in the security docs.
- [ ] ⬜ **Task 4.2**: `settings_repair` re-reads before it replaces, and the
  writer count is corrected (G7). `daemon_sync_after_merge` and
  `merge_qa_report` judge the repository the command ran in, using 00464's
  resolver once it merges (G9).
- [ ] ⬜ **Task 4.3**: `lsp_enforcement` enforces only when an enabled LSP
  plugin covers the searched language. Its advice names installing a
  code-intelligence plugin (P5).

### Phase 5: documentation (G3, G4, G5, P8)

- [x] ✅ **Task 5.1**: Vendor the Claude Code plugin and hooks docs with
  `remote-docs add` (G3). Add a "Claude Code plugins alongside the daemon"
  section and fix the hook-source and environment tables (G4). Separate
  "daemon plugin" from "Claude Code plugin" everywhere (G5). The canonical
  home is `CLAUDE/ClaudeCodePlugins.md`, with a human summary at
  `docs/guides/CLAUDE_CODE_PLUGINS.md`. Task 4.1's security-docs note should
  link to it rather than restate the `updatedInput` limit.
- [ ] ⬜ **Task 5.2**: P8 is 00422 N24 (the orchestrator simulation says
  "would have been denied" for Bash). Confirm Plan 00463's fix covers it, or
  fix it here.

## Success Criteria

- [ ] Every P1–P8 and G1–G16 finding is fixed, with a RED-first test where
  code changed, or corrected with the reasoning recorded.
- [ ] A fresh install and an upgrade from the last tag deliver no plugin
  keys.
- [ ] Every release-bound consequence is in `CLAUDE/UPGRADES/UNRELEASED/`
  before the status flips.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00468-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened from the Plan 00467 plugin audit; Task 1.1 landed with it.
