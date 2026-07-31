# Plan 00192: Replace `$PYTHON` guidance with real bash wrapper UX

**Status**: Complete
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon instructs agents to run `$PYTHON -m claude_code_hooks_daemon.daemon.cli …`
in 77 places across 29 source files, 12 of them handlers that inject the string
directly into agent-visible block reasons and `get_claude_md()` guidance. `$PYTHON` is **not set**
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

Independently corroborated by a field report from a **separate client install**
(client-a infra repo, ccy/Podman, daemon v3.49.0) — see
`FIELD-REPORT-client-a-v3.49.0.md` in this folder. That report reproduces the
same root cause on a different layout, Python version and venv fingerprint,
confirming this is install-independent rather than a quirk of self-install mode.

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
4. **`daemon-cli.sh` is not git-worktree-aware** (field report). It walks up from
   `pwd` for `.claude/hooks-daemon.yaml`, which IS present in a worktree, then
   anchors `DAEMON_DIR` there — but `.claude/.gitignore:3` ignores
   `hooks-daemon/`, so `scripts/lib/resolve_venv.sh` exists only in the main
   checkout. Result: exit 5, "canonical library missing". Worktrees are a common
   agent workflow, so this compounds the primary bug. **A real code defect, not
   a docs defect.**
5. **No console entry point.** `pyproject.toml` declares no `[project.scripts]`
   (verified), so nothing named `hooks-daemon` / `plan-qa` exists on `PATH` and
   there is no fallback when the documented invocation fails.
6. **`init.sh` deliberately does not export the interpreter** (verified,
   `init.sh:502-503`): it resolves into `PYTHON_CMD` and comments that this is
   intentional because the hot path uses system `python3`. That decision is
   correct and should stand — which confirms the bug is purely that the
   documentation is **written from inside the wrapper scripts' variable scope**
   and handed to a reader who is not in that scope.

### Affected source sites

**29 files under `src/` contain a literal `$PYTHON`** (`rg -l '\$PYTHON' src/`).
Of those, 12 are handlers injecting it into agent-visible block reasons or
`get_claude_md()`: `plan_qa_edit`, `plan_qa_commit_gate`, `plan_qa_sweep`,
`daemon_location_guard`, `daemon_restart_verifier`, `task_tdd_advisor`,
`project_handler_load_checker`, `plan_workflow_asset_checker`,
`hook_registration_checker`, `background_process_tracker`,
`markdown_table_formatter`, `project_loader`.

Generator/error surfaces: `daemon/docs_generator.py` (emits 13 occurrences into
the resident `CLAUDE.md` block), `daemon/playbook_generator.py`,
`daemon/cli_acceptance_tests.py` (hardcodes `_CLI_PREFIX`), `daemon/cli.py`,
`utils/error_formatter.py`.

The remainder are `src/**/*.md` docs (`skills/hooks-daemon/*.md`,
`src/CLAUDE.md`, `strategies/tdd/CLAUDE.md`) that are shipped to client projects
and read by agents, so they are in scope too.

### Why this is worse than an unrunnable command

The field report documents the recovery behaviour it provokes. Having seen
`ModuleNotFoundError`, an agent reasonably concludes the package is not
installed and tries to fix that: `pip install claude-code-hooks-daemon` (wrong
environment, blocked by PEP 668), editing the container Dockerfile, or building
a new venv — **all of which damage a working installation whose venv was never
broken**. The report exists because exactly that path was started before being
caught.

Two messages make this worse by firing precisely when the agent is already in
trouble: `daemon_location_guard` (redirecting an agent that has `cd`'d into the
daemon dir — its three remedy commands all fail) and
`project_handler_load_checker` (reporting *degraded security protection*, whose
diagnostic command also fails). A real, security-relevant degradation cannot be
investigated by following the printed instructions.

## Tasks

### Phase 0: Client-mode test fixture (DONE — enables every later phase)

- [x] ✅ **Task 0.1**: Automate provisioning of a real client-mode install at
  `untracked/dummy-client-repo/` via `scripts/dummy-client-repo.sh`, driving the
  PRODUCTION installer (`scripts/install_version.sh`) rather than synthesised
  state — the v3.10.0 SEV-1 escaped because a gate faked install state.
  - [x] ✅ `create` / `status` / `cli` / `python` / `destroy` subcommands.
  - [x] ✅ Isolated by a dedicated `HOSTNAME` so it never collides with the
    dogfood daemon (verified: dogfood PID 459 untouched).
  - [x] ✅ FAIL FAST if the install leaves no RUNNING daemon.
- [x] ✅ **Task 0.2**: Reproduce this plan's bug in true client mode — confirmed
  **9 unrunnable `$PYTHON` lines** in the fresh client's generated `CLAUDE.md`.

### Phase 1: Shared resolver utility (DONE)

Chosen shape (Decision 2): a deployed `bin/hooks-daemon` wrapper, emitted as an
absolute path.

- [x] ✅ **Task 1.1**: Failing tests for `daemon_cli_command()` — RED confirmed
  via `ImportError`.
  - [x] ✅ Self-install resolves to `{project_root}/bin/hooks-daemon`.
  - [x] ✅ Client install resolves to
    `{project_root}/.claude/hooks-daemon/bin/hooks-daemon`.
  - [x] ✅ Regression guard: emitted string never contains `$`, `PYTHON`, or
    `-m claude_code_hooks_daemon`.
- [x] ✅ **Task 1.2**: `utils/cli_command.py` implemented — named constants, full
  annotations, 13 tests green.

### Phase 2: The wrapper (template + deploy DONE; installer wiring REMAINS)

- [x] ✅ **Task 2.1**: Failing tests for the wrapper template and its deployment.
- [x] ✅ **Task 2.2**: `install/templates/hooks-daemon` implemented — shellcheck
  clean, no network access, anchors to its OWN location (`$0`) rather than CWD.
  Verified live: restarted the dogfood daemon through it.
- [x] ✅ **Task 2.3**: `install/bin_wrapper.py` deploy function — overwrite-on-run,
  chmod 0o755, never world-writable, mirroring `_deploy_mkplan`.
- [x] ✅ **Task 2.4**: Drift guard — the tracked self-install copy must match the
  bundled template byte-for-byte.
- [x] ✅ **Task 2.5**: Wired `deploy_bin_wrapper()` into BOTH paths —
  `install_version.sh` Step 10b (fresh installs) and `upgrade_version.sh`
  Step 13b (existing installs, which is what delivers the fix to projects that
  predate it). Verified end-to-end by rebuilding the client fixture: wrapper
  deployed executable at
  `.claude/hooks-daemon/bin/hooks-daemon`, byte-identical to the template, and
  reports `Daemon: RUNNING`.
- [x] ✅ **Task 2.6**: Retired the stale root `daemon.sh` — now a thin deprecation
  shim that forwards every subcommand to `bin/hooks-daemon`, so `bin/hooks-daemon`
  is the single canonical entry point. Mode corrected `rwx--x--x` → 755. The two
  bespoke log verbs with a CLI equivalent (`logs-tail`, `logs-all`) are
  translated; `logs-clear` has none, so it says so and exits 2 rather than
  pretending. The deprecation notice goes to **stderr**, never stdout, so
  anything capturing output is unaffected.

**Anchoring to `$0` also fixes gap 4 for free.** Verified A/B from an unrelated
CWD: `daemon-cli.sh` exits 1 with "Not in a hooks daemon project", while
`bin/hooks-daemon` resolves the venv and reaches the daemon CLI.

### Phase 3: Swap all emission sites (DONE)

- [x] ✅ **Task 3.1**: `scripts/qa/check_python_var_guidance.py` — 14th QA gate,
  fails the build if the pattern returns. Exempts the resolver module itself,
  mirroring how `check_canonical_callers` exempts `resolve_venv.sh`. RED run
  enumerated **77 violations across 29 files**.
- [x] ✅ **Task 3.2**: 12 handler sites converted. Module-level constants became
  functions (the wrapper path depends on install mode, known only after startup).
- [x] ✅ **Task 3.3**: 5 generator/error surfaces converted.
- [x] ✅ **Task 3.4**: Markdown shipped to clients now names the wrapper. Four
  troubleshooting snippets invoked a RAW interpreter rather than the CLI; those
  became proper subcommands (`health`, `list-venvs`, `config-validate`), so no
  guidance tells an agent to run raw python at all.
- [x] ✅ **Task 3.5**: Regenerated docs — self-install `CLAUDE.md` and
  `.claude/HOOKS-DAEMON.md` both at **0**.

Fixed en route: `daemon_location_guard` hardcoded
`PYTHON=/workspace/untracked/venv/bin/python` — the legacy venv AND this repo's
path, shipped to every client. Two tests asserted the OLD broken behaviour and
now pin the new contract. A Bandit B608 false positive (prose reading "delete
from" next to a new f-string) was reworded, not suppressed.

### Phase 4: Skill coverage for plan QA (DONE)

- [x] ✅ **Task 4.1**: Added `skills/hooks-daemon/plan-qa.md` covering `--sweep`,
  `--lint <file>`, `--check-staged` and `--json`, plus what the clean output
  looks like, the disabled-workflow message, and where policy lives
  (`plan_workflow.qa`). Every command is the deployed wrapper path, with the
  self-install variant noted once rather than duplicated per snippet.
- [x] ✅ **Task 4.2**: Referenced from `SKILL.md` under "Available Commands".

### Phase 5: Dual-mode verification

Every check runs in BOTH modes. Self-install alone cannot verify this class of
bug — the field report came from a client install whose layout differs.

- [x] ✅ **Task 5.1**: QA **14/14 PASSED**, 10,749 tests, 95.2% coverage.
- [x] ✅ **Task 5.2**: Daemon restart + RUNNING (self-install), performed
  *through the new wrapper*.
- [x] ✅ **Task 5.3**: Client fixture rebuilt against committed code — its
  generated `CLAUDE.md` went **9 → 0**.
- [x] ✅ **Task 5.4**: Commands copied verbatim from the client's `CLAUDE.md`
  execute — `status` and `plan-qa --sweep` both return real CLI responses, no
  exit 127, no `-m: command not found`.
- [x] ✅ **Task 5.5**: CWD-independence verified A/B from an unrelated directory:
  `daemon-cli.sh` exits 1 ("Not in a hooks daemon project") while
  `bin/hooks-daemon` resolves and reaches the CLI.

Both daemons verified RUNNING and isolated afterwards (dogfood + fixture).

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

- [x] ✅ `rg '\$PYTHON' src/` returns no agent-facing occurrences (77 → 0).
- [x] ✅ A QA check fails the build if a literal `$PYTHON` is reintroduced
  (`python_var_guidance`, gate 12 of 14).
- [x] ✅ `plan-qa --sweep` runs verbatim as printed in injected guidance, in
  **both** self-install mode and the client fixture.
- [x] ✅ Deployed skill documents plan QA (`plan-qa.md` + `SKILL.md` entry).
- [x] ✅ Full QA passes (14/14, 10,749 tests, 95.2% coverage); daemon restarts
  RUNNING.

## Risks & Mitigations

| Risk                                                     | Impact | Probability | Mitigation                                                                        |
| -------------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------------------------- |
| Resolver differs between self-install and client install | High   | Medium      | Parity tests covering both modes, mirroring `test_venv_resolver_parity_matrix.py` |
| Regenerated `CLAUDE.md` churns in client repos           | Low    | High        | Expected and desirable — it replaces broken guidance; note in release notes       |
| Wrapper network bootstrap reintroduced on hot path       | Medium | Low         | Self-install wrapper explicitly has no bootstrap stanza; covered by test          |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Plan created; root cause verified against a live agent shell — `90b38f16`
- Phase 0: client-mode fixture automated, standard practice documented — `367b4cc0`
- Phase 1+2: resolver utility + deployed `bin/hooks-daemon` wrapper — `93a412fb`
- Task 2.5: wrapper deployment wired into install AND upgrade — `3b58c9df`
- Phase 3: all 77 emission sites swapped + `python_var_guidance` gate — `51ceb4ee`
- Verified 9 → 0 in a real client install — `3a4f5975`
- Phase 4 + Task 2.6: skill plan-QA page; `daemon.sh` retired to a shim — this commit
