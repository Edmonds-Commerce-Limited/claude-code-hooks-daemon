# Plan 00192: Replace `$PYTHON` guidance with real bash wrapper UX

**Status**: Not Started
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon instructs agents to run `$PYTHON -m claude_code_hooks_daemon.daemon.cli …`
in 17 source locations, 12 of them handlers that inject the string directly into
agent-visible block reasons and `get_claude_md()` guidance. `$PYTHON` is **not set**
in an agent's Bash shell, and the PATH `python3` cannot import the module because the
daemon lives in an isolated fingerprint-keyed venv. Every such instruction therefore
expands to `-m claude_code_hooks_daemon.daemon.cli …` and fails with
`-m: command not found`.

The failure is silent-by-confusion rather than loud: an agent that cannot run
`plan-qa --sweep` concludes the feature is *uninstalled* and abandons it, when the
feature is present and working. This was diagnosed from exactly that
misdiagnosis — an agent reported plan QA as missing; it was fully functional via
`untracked/venv-workspace-py311-81c29529/bin/python`.

Agents must never be handed a raw interpreter invocation. The project already has
the correct pattern in two places: `pipe_blocker` resolves and prints an **absolute**
path to `scripts/echd-capture`, and `skills/hooks-daemon/scripts/daemon-cli.sh` is a
fully general `"$PYTHON" -m …cli "$@"` forwarder. The fix is to make every emitted
command a real, runnable, absolute path resolved at handler runtime.

## Goals

- No agent-facing string in `src/` contains a literal `$PYTHON`.
- Every emitted daemon-CLI command is an absolute path that runs as printed, in
  both self-install mode and a normal client install.
- A wrapper is reachable in self-install mode without network access.
- The deployed `hooks-daemon` skill documents plan QA.

## Non-Goals

- Changing any daemon CLI subcommand behaviour or output.
- Rewriting the venv resolution logic (`scripts/lib/resolve_venv.sh` is correct).
- Removing `$PYTHON` from historical records (`RELEASES/`, `CHANGELOG.md`,
  completed plans) — those are immutable history.

## Context & Background

Verified ground truth in a live agent shell (2026-07-31):

| Check                                          | Result                                               |
| ---------------------------------------------- | ---------------------------------------------------- |
| `$PYTHON` in agent Bash                        | unset                                                |
| `python3 -c "import claude_code_hooks_daemon"` | `ModuleNotFoundError`                                |
| Real interpreter                               | `untracked/venv-workspace-py311-81c29529/bin/python` |
| `plan-qa --sweep` via that interpreter         | works (exit 1, 1 advisory finding)                   |

Structural gaps found:

1. **`daemon-cli.sh` is unreachable in self-install mode.** It is not deployed
   (`.claude/skills/` has no `hooks-daemon/`), and it resolves the venv via
   `$DAEMON_DIR/scripts/lib/resolve_venv.sh`, which does not exist under
   `.claude/hooks-daemon/` in self-install mode. It also performs a network
   self-bootstrap per invocation (marker-cached), which is unacceptable for a
   hot-path command such as `plan-qa --lint`.
2. **`daemon.sh` at repo root is stale.** It hardcodes the legacy
   `untracked/venv/bin/python` rather than the fingerprint-keyed venv that
   `CLAUDE.md` declares canonical, exposes only a curated subcommand list rather
   than forwarding, and is mode `rwx--x--x`.
3. **The skill has zero plan-QA coverage** — `rg 'plan-qa' src/…/skills/` returns
   nothing.

### Affected source sites

Handlers injecting `$PYTHON` into agent-visible text: `plan_qa_edit`,
`plan_qa_commit_gate`, `plan_qa_sweep`, `daemon_location_guard`,
`daemon_restart_verifier`, `task_tdd_advisor`, `project_handler_load_checker`,
`plan_workflow_asset_checker`, `hook_registration_checker`,
`background_process_tracker`, `markdown_table_formatter`, `project_loader`.

Generator/error surfaces: `daemon/docs_generator.py` (emits 13 occurrences into
the resident `CLAUDE.md` block), `daemon/playbook_generator.py`,
`daemon/cli_acceptance_tests.py`, `daemon/cli.py`, `utils/error_formatter.py`.

## Tasks

### Phase 1: Shared resolver utility

- [ ] ⬜ **Task 1.1**: Write failing tests for a `daemon_cli_command()` utility that
  returns a runnable absolute invocation for the current install mode.
  - [ ] ⬜ Self-install mode resolves to the fingerprint-keyed venv interpreter.
  - [ ] ⬜ Client-install mode resolves to the deployed wrapper path.
  - [ ] ⬜ Fails loudly (never returns a `$PYTHON` literal) when no venv resolves.
- [ ] ⬜ **Task 1.2**: Implement the utility to pass, with named constants (no magic
  strings) and full type annotations.

### Phase 2: Self-install wrapper

- [ ] ⬜ **Task 2.1**: Write failing tests for a no-network wrapper reachable in
  self-install mode that forwards all arguments to the daemon CLI.
- [ ] ⬜ **Task 2.2**: Implement the wrapper; verify `plan-qa --sweep` runs through it.
- [ ] ⬜ **Task 2.3**: Repoint or retire `daemon.sh` (stale legacy venv path, odd
  permissions); ensure exactly one canonical root entry point.

### Phase 3: Swap all emission sites

- [ ] ⬜ **Task 3.1**: Add a QA check that fails when a literal `$PYTHON` appears in
  any agent-facing string under `src/` (guards against regression).
- [ ] ⬜ **Task 3.2**: Convert the 12 handler sites to the resolver utility.
- [ ] ⬜ **Task 3.3**: Convert the 5 generator/error surfaces.
- [ ] ⬜ **Task 3.4**: Regenerate `.claude/HOOKS-DAEMON.md` and the resident
  `CLAUDE.md` block; confirm zero `$PYTHON` occurrences remain.

### Phase 4: Skill coverage for plan QA

- [ ] ⬜ **Task 4.1**: Add a `plan-qa.md` page to the deployed skill covering
  `--sweep`, `--lint <file>`, `--check-staged`, and `--json`.
- [ ] ⬜ **Task 4.2**: Reference it from `SKILL.md` "Available Commands".

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Full QA: `./scripts/qa/run_all.sh`.
- [ ] ⬜ **Task 5.2**: Daemon restart + status RUNNING.
- [ ] ⬜ **Task 5.3**: Dogfood — confirm a fresh session's injected guidance contains
  only runnable commands, executed verbatim as printed.

## Technical Decisions

### Decision 1: Resolve at runtime rather than document a variable

**Context**: The current guidance assumes the agent's shell exports `$PYTHON`. It
never does — only the daemon's own bash entry points set it internally.

**Options Considered**:

1. Document how to set `$PYTHON` — pushes venv complexity onto every agent and
   every client project's docs; still breaks when the fingerprint changes.
2. Emit an absolute resolved path at runtime — matches the proven `echd-capture`
   pattern already used by `pipe_blocker`.

**Decision**: Option 2. The daemon knows its own interpreter; the agent should
never have to. Guidance must be copy-paste runnable.
**Date**: 2026-07-31

## Success Criteria

- [ ] `rg '\$PYTHON' src/` returns no agent-facing occurrences.
- [ ] A QA check fails the build if a literal `$PYTHON` is reintroduced.
- [ ] `plan-qa --sweep` runs verbatim as printed in injected guidance, in
  self-install mode.
- [ ] Deployed skill documents plan QA.
- [ ] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                        |
| -------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------- |
| Resolver differs between self-install and client install | High   | Medium      | Parity tests covering both modes, mirroring `test_venv_resolver_parity_matrix.py` |
| Regenerated `CLAUDE.md` churns in client repos           | Low    | High        | Expected and desirable — it replaces broken guidance; note in release notes       |
| Wrapper network bootstrap reintroduced on hot path       | Medium | Low         | Self-install wrapper explicitly has no bootstrap stanza; covered by test          |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Plan created; root cause verified against a live agent shell.
