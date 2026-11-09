# Plan 00589: explain rule covers plugin handlers

**Status**: In Progress
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #171

## Overview

Every deny ends with "Full detail: `hooks-daemon explain-rule <ID>`", and the
generated CLAUDE.md lists the rules of handlers loaded through the `plugins:`
config section. Yet `explain-rule` answers "unknown rule ID" for exactly those
rules (reproduced on `main` with a scratch project whose `plugins:` entry loads
one handler declaring `R-DEMO-PLUGIN-RULE`; `PluginLoader` loads it, the lookup
does not see it).

Cause: `rule_explain/lookup.py` `discover_handler_rules(include_project_handlers=True)`
adds the library package and `project_handlers:`, never the plugin loader.
`explain-handler` shares the lookup and the gap.

## Goals

- `explain-rule` and `explain-handler` resolve a rule or handler loaded through
  `plugins:`, using the same loader the daemon uses.
- A plugin that fails to load degrades to "contributes no rules", logged, never
  breaking the lookup for library and project handlers.

## Non-Goals

- Changing plugin loading itself, or the block-report fingerprint index (it
  keeps the library-only default).

## Tasks

### Phase 1: Lookup covers plugins

- [ ] 🔄 **Task 1.1**: RED tests: a `plugins:` handler's rule resolves through
  `explain-rule` and its handler through `explain-handler`; a broken plugin entry
  leaves library lookups working. GREEN: collect plugin handler classes beside
  `_project_handler_classes()` under the same opt-in. Release note.

## Success Criteria

- [ ] The issue's reproduction resolves `R-DEMO-PLUGIN-RULE` on `main`.
- [ ] Release-bound consequence recorded as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- delivery commit hash -->
