# Plan 00193: Extend the `$PYTHON` guidance sweep to living docs

**Status**: Complete
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00192 eliminated the unrunnable `$PYTHON -m claude_code_hooks_daemon.daemon.cli …`
instruction from `src/` — 77 occurrences across 29 files — and installed the
`python_var_guidance` QA gate so it cannot return. That gate is scoped to
`src/` only.

**223 occurrences across 23 living documentation files remain outside that
scope.** They are the same defect: an agent that follows them runs a command
that expands to `-m: command not found`, concludes the package is not
installed, and starts "fixing" a working install (`pip install` into the wrong
environment, editing the Dockerfile, rebuilding a venv that was never broken).
Plan 00192's field report documents exactly that recovery path being started.

These are **pre-existing, not a regression** — they shipped in v3.49.1 and
every prior version. They were found during the v3.50.0 release code review and
are tracked here rather than dropped, per RELEASING.md "Review Early, Never
Drop Findings".

## Goals

- No living documentation file instructs the reader to invoke a raw interpreter
  or a `$PYTHON` variable that is never exported in their shell.
- The `python_var_guidance` QA gate covers these paths, so the class cannot
  silently return.
- Docs that legitimately define `PYTHON` as their own local shell variable
  inside a self-contained snippet keep working, and are distinguished from docs
  that hand the reader an undefined variable.

## Non-Goals

- Rewriting immutable history: `RELEASES/`, `CHANGELOG.md`, completed and
  cancelled plans, `CLAUDE/UPGRADES/v2/**` and `v3/**` (shipped upgrade guides
  describe what was true at the time), and
  `CLAUDE/AcceptanceTests/PLAYBOOK-v1-manual-archived.md`.
- Changing any CLI behaviour. This is a documentation-accuracy plan.
- The deliberate references that EXPLAIN the trap rather than instruct it —
  `CLAUDE.md` ("do not expect `$PYTHON` to be set — it never is in your
  shell"), `CLAUDE/development/RELEASING.md` and
  `CLAUDE/development/CLIENT-MODE-TESTING.md`. These must survive the sweep.

## Context & Background

### Inventory

The plan opened with "223 occurrences across 23 files", counted by grepping for
the literal string `PYTHON`. That figure was wrong **in kind**, not merely in
count: it measured one spelling of the defect. The defect is "documentation
hands the reader a command that cannot run", and it has **four** spellings —
the fourth being not a document at all, but a script printing to the operator:

| Variant                                   | What it is                                                                                                                    | Found  |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------ |
| 1. `$PYTHON` / `$VENV_PYTHON`             | Never exported to a reader's shell; line expands to `-m …` → `command not found`                                              | 297    |
| 2. `<python> -m …daemon.cli`              | A PATH `python3` cannot import the package (`include-system-site-packages = false`)                                           | (in 1) |
| 3. `untracked/venv/bin/python` \| `…/pip` | The **retired pre-v3.7.0 venv layout**. Venvs are fingerprint-keyed since v3.7.0, so this directory exists on no live install | 65     |
| 4. The same, PRINTED at runtime by `.sh`  | Installer / upgrader / worktree scripts echo commands to the operator; `.sh` was outside the scanned suffixes entirely        | 9      |

Each variant was invisible to the search that found the previous one. Variant 3
names a real-looking path rather than an unset variable, so it *looks* runnable
and greps clean for `PYTHON` — it was the single largest group. Variant 4 is not
in a document at all: it is emitted at runtime, and was found only by
provisioning the client fixture and reading what the installer actually printed.

`CLAUDE/development/RELEASING.md` and `CLAUDE/development/CLIENT-MODE-TESTING.md`
are the deliberate explanatory references listed under Non-Goals — verified and
marked exempt in place, not rewritten.

### Severity is not uniform

Three of these carry more weight than their counts suggest:

- `CLAUDE/CodeLifecycle/{General,Bugs,Features}.md` are marked **MANDATORY** in
  `CLAUDE.md` and are read before every code change. Their daemon-restart
  verification step — the single most important check in the project — is
  currently written as an uncopyable command.
- `CLAUDE/LLM-INSTALL.md` and `CLAUDE/LLM-UPDATE.md` are what an agent reads
  when a project is *already* in a broken or half-installed state. That is the
  worst possible moment to hand it a command that fails.
- `docs/guides/GETTING_STARTED.md` is a new user's first contact.

### Not every occurrence is a defect

Some snippets define `PYTHON` locally before using it, which is correct and
self-contained:

```bash
PYTHON="$(resolve_venv_python /workspace)"
"$PYTHON" -m pytest …
```

The sweep must distinguish "the doc defines it" from "the doc assumes the
reader has it". Only the latter is broken. A blind find-and-replace would
damage the former.

## Tasks

### Phase 1: Classify

- [x] ✅ **Task 1.1**: For every occurrence, classify as (a) instructs the
  reader to run an undefined `$PYTHON` — DEFECT, (b) defines `PYTHON` locally
  in the same snippet — KEEP, (c) explains the trap — KEEP.
- [x] ✅ **Task 1.2**: Record the counts per class so the QA gate's exemption
  list can be written from evidence rather than guessed.

### Phase 2: Remediate

- [x] ✅ **Task 2.1**: Fix the three MANDATORY CodeLifecycle docs first — they
  gate every code change in the project.
- [x] ✅ **Task 2.2**: Fix the recovery-path docs (`LLM-INSTALL.md`,
  `LLM-UPDATE.md`, `SELF_INSTALL.md`), which are read when things are already
  broken.
- [x] ✅ **Task 2.3**: Fix the remaining `CLAUDE/**` docs.
- [x] ✅ **Task 2.4**: Fix `docs/**` and `examples/**` (user-facing).
- [x] ✅ **Task 2.5**: Where a doc genuinely needs a raw interpreter (pytest,
  ad-hoc scripts), use the canonical resolver pattern rather than inventing a
  path — see `CLAUDE/development/RELEASING.md` Step 12.0 for the worked form.
- [x] ✅ **Task 2.6**: Replace hand-rolled venv/install recipes with their SSoT
  scripts — `setup_worktree.sh`, `install_version.sh`, `upgrade_version.sh`,
  and the `handlers` / `health` / `repair` / `list-venvs` CLI subcommands.
  Several docs also told the reader to `cd .claude/hooks-daemon`, which
  `daemon_location_guard` blocks.

### Phase 3: Lock it in

- [x] ✅ **Task 3.1**: Extend `scripts/qa/check_python_var_guidance.py` to cover
  `CLAUDE/**`, `docs/**` and `examples/**`, with explicit exemptions for the
  history paths in Non-Goals and the class-(b)/(c) occurrences found in Phase 1.
- [x] ✅ **Task 3.2**: Confirm the gate FAILS on a reintroduced occurrence — the
  widened gate was observed RED at 297, then 61, then 2 before reaching 0, and
  the new variant-3 rule was written test-first (3 failing tests → pass).
- [x] ✅ **Task 3.3**: Full QA green (14/14); daemon restarts RUNNING.
- [x] ✅ **Task 3.4**: Give the gate a test file — it shipped with none, which is
  why its `src/`-only scope went unchallenged. `tests/unit/qa/test_check_python_var_guidance.py`
  covers all three variants, the exemption semantics, and locks the real trees
  clean via `TestRepositoryIsClean`.
- [x] ✅ **Task 3.5**: Cover `scripts/**` and `.sh` files. Provisioning the client
  fixture showed the installer PRINTS variant 2 at completion, and
  `setup_worktree.sh` printed the literal `$PYTHON -m …` variant-1 form — runtime
  guidance reaches the operator exactly like a doc, but `.sh` was outside the
  scanned suffixes. The `.sh` rule fires only on an output statement that shows a
  COMMAND (`-m …daemon.cli`, or an escaped `\$PYTHON`); a diagnostic reporting an
  already-resolved interpreter is legitimate and must not be flagged.

### Phase 4: Verify where it matters

- [x] ✅ **Task 4.1**: Rebuilt the client fixture and scanned every client-visible
  doc. 478 raw hits → 29 outside immutable history → 3 real defect groups, all
  fixed (below). Everything else is exempt history or an inline-marked
  explanatory mention.
- [x] ✅ **Task 4.2**: Executed the corrected commands verbatim from the client
  tree — `status`, `health`, `handlers`, `list-venvs`, `config`, `check`,
  `plan-qa --sweep`, and the installer's own printed `Daemon management:` block.
  All run. This is what surfaced Plan 00194 (below).
- [x] ✅ **Task 4.3**: Removed the blanket path-exemption on the skill wrappers.
  It was silencing five `echo` lines that told the operator to run
  `$PYTHON -m …daemon.cli` instead of the wrapper. The `.sh` output-statement
  rule separates their legitimate invocations from their printed guidance, so
  the exemption was unnecessary — **a path exemption silences a whole file;
  prefer a rule that can tell the two apart.**
- [x] ✅ **Task 4.4**: Fixed two hardcoded legacy defaults shipping to every
  client: `CLAUDE/AcceptanceTests/validation/test-helpers.sh` defaulted to
  `/workspace/untracked/venv/bin/python` — this repo's OWN path, in the retired
  layout, in a client project where neither exists — and
  `CLAUDE/UPGRADES/upgrade-template/verification.sh` hand-rolled venv resolution
  with a legacy fallback. Both now use the deployed wrapper.

### Phase 5: Close the client-install scope hole

- [x] ✅ **Task 5.0**: A client install clones the ENTIRE repo to
  `.claude/hooks-daemon/`, so repo-root `README.md`, `BUG_REPORTING.md`,
  `CONTRIBUTING.md`, `CLAUDE.md` and the daemon's own `.claude/skills/` +
  `.claude/agents/` all ship to clients — yet every one of them sat OUTSIDE the
  scan roots. Added `.claude` to `_DEFAULT_SCAN_ROOTS` and introduced
  `_DEFAULT_SCAN_FILES` for the four repo-root docs. That surfaced 38 further
  violations, all now fixed: README.md (14), BUG_REPORTING.md (5),
  `configure/SKILL.md` (5), `mode/SKILL.md` (4), `transcript-inspector.md` (4),
  `release-agent.md` (4), `CLAUDE.md` (2, inline-marked as reference).
- [x] ✅ **Task 5.1**: Fixed the five skill launchers the gate could NOT flag,
  because their defects live in assignments rather than output statements.
  `configure`, `mode` and `optimise` each carried a two-branch guard on the
  RETIRED `untracked/venv/bin/python` layout; `optimise` then fell through to a
  bare `python3` that cannot import the package at all, and `acceptance-test`
  referenced `$PYTHON` having never defined it. All five now resolve the
  deployed wrapper with an explicit fail-fast else.

### Phase 6: Act on the client-mode verification findings

Every claim was reproduced in the client fixture before acting, fixed with TDD,
and re-verified end-to-end. Full write-ups in `JOURNAL/` (2026-08-01).

- [x] ✅ **Task 6.0**: `init-project-handlers` emitted a handler with no
  `get_claude_md()`, so `validate-project-handlers` rejected the daemon's OWN
  scaffold → "PROJECT PROTECTION DEGRADED" from the documented first step.
- [x] ✅ **Task 6.1**: That message cited `CLAUDE/UPGRADES/v2/`, unresolvable in
  a client. Added `utils.cli_command.daemon_path()` as the one anchor point for
  daemon-owned paths in reader-facing text; major version derived, not pinned.
- [x] ✅ **Task 6.2**: `cmd_start` forked without flushing stdio, so `restart`
  printed the stop lines twice with the same pid. Block-buffered only — it
  corrupted exactly the captured output tooling parses.
- [x] ✅ **Task 6.3**: `test-project-handlers` assumed pytest, a dev-only extra
  no client has. Now fails fast with the pip command. Rejected shipping pytest
  to every client: it drags black/mypy/bandit/twine in for an optional workflow.
- [x] ✅ **Task 6.4**: `scripts/run-qa-runner.sh` used a bare `python3` and died
  with `ModuleNotFoundError` — the failure `docs/QA-RUNNER-SETUP.md` warns
  about, in the wrapper that doc recommends — then reported it as "QA checks
  found issues", disguising a failure to run as a finding. Now uses
  `resolve_venv.sh` and exits 2 on resolver failure.
- [x] ✅ **Task 6.5**: Non-existent documented commands: `validate-config` (real
  name `config-validate`, takes a path), `--version`, `status --verbose`; plus
  `health` wrongly documented as reporting the interpreter. Fixed in `health.md`,
  `troubleshooting.md` and the skill dispatch table (which routed the wrong name).
- [x] ✅ **Task 6.6**: `troubleshooting.md` taught `pkill -f hooks-daemon` twice
  — unscoped, so in a shared PID namespace it kills other projects' daemons,
  what the daemon's own enforcement scopes by project root to avoid. Its
  rollback recipe also `cd`-ed into the blocked daemon dir and used a bare
  `git checkout`, leaving the venv on the other version's dependencies.
- [x] ✅ **Task 6.7**: `dummy-client-repo.sh destroy` reported a clean teardown
  while ORPHANING the fixture daemon — an unanchored `stop` resolved the DOGFOOD
  project, said "Daemon not running", and teardown deleted the tree around a
  live daemon. Plan 00194's CWD-vs-anchor bug, biting for real. Fixed with
  `--project-root` plus a `verify_dummy_daemon_stopped` post-condition; a
  contract test now rejects any unanchored CLI invocation in that script.

### Phase 7: Residual gate coverage

- [x] ✅ **Task 7.1**: The `.sh` rule fired only on output statements, so a
  hardcoded legacy venv path in a NON-output shell line (an assignment or
  default, as in Task 4.4) was ungated. Resolved with **both** halves of the
  choice: an assignment-aware rule (`_LEGACY_VENV_PATH`, checked before the
  output-statement skip) plus the existing inline marker for genuine
  resolvers. The new rule surfaced 14 occurrences the old one structurally
  could not see — 6 real silent fallbacks to the retired pre-v3.7.0 layout
  (including in `scripts/qa/run_all.sh` itself), 8 legitimate. See Decision 4.

## Dependencies

- Depends on: Plan 00192 (Complete) — provides `bin/hooks-daemon`,
  `utils/cli_command.py` and the `python_var_guidance` gate this plan extends.

## Technical Decisions

### Decision 1: Extend the existing gate rather than add a second one

**Context**: Phase 3 could add a separate docs-only checker.

**Options Considered**:

1. New checker for docs — a second regex and exemption list to keep in sync
   with the first; they will drift.
2. Widen `check_python_var_guidance.py`'s path scope and exemption list.

**Decision**: Option 2. One gate, one pattern, one exemption list. The gate
already distinguishes exempt paths; this is a scope change, not new logic.
**Date**: 2026-07-31

### Decision 2: A gate's SCOPE is part of its contract and must be tested

**Context**: Plan 00192 shipped `python_var_guidance` scoped to `src/` only,
with no test file. It passed every release gate while 297 occurrences of the
exact defect it exists to prevent sat in `CLAUDE/`, `docs/` and `examples/`.
That is the direct answer to "how did this get through QA": **a gate only ever
checks what you point it at**, and nothing asserted where this one pointed.

**Decision**: Widening the scope is necessary but not sufficient. The gate now
has a test file whose `TestRepositoryIsClean` case runs it against its real
default roots — so a future narrowing of `_DEFAULT_SCAN_ROOTS` is a *test
failure*, not a silent loss of coverage. Exemptions are same-line and must state
their reason inline, so silencing a finding is visible in the diff.
**Date**: 2026-08-01

### Decision 3: Take BOTH halves of the Task 7.1 choice, not one

**Context**: Task 7.1 framed the residual gap as a choice — an assignment-aware
rule *or* inline-marker exemptions for the genuine resolvers.

**Options Considered**:

1. Marker-only — cheap, but locks nothing: the next unmarked assignment is
   invisible again. It treats the symptom (today's known sites) not the class.
2. Rule-only — locks the class, but then flags the resolvers that must probe
   the retired layout in order to migrate away from it.
3. Both — the rule fires on any `untracked/venv/bin/` in a shell line
   regardless of statement kind; the same-line marker is how a genuine prober
   declares itself, in the diff, with its reason.

**Decision**: Option 3. The two are complements, not alternatives — the rule
supplies the coverage and the marker supplies the escape hatch that keeps the
coverage honest. Running it found 14 sites, 6 of them real silent fallbacks to
a path that exists on no live install. Each became a fail-fast, so "the
resolver is missing" now says so instead of degrading into "no such file"
against a retired path. Site-by-site breakdown in JOURNAL/26-08-01.
**Date**: 2026-08-01

## Success Criteria

- [ ] Every class-(a) occurrence is corrected; class-(b)/(c) are intact.
- [ ] `python_var_guidance` covers `CLAUDE/**`, `docs/**`, `examples/**` and has
  been observed failing on a reintroduction.
- [ ] Client fixture shows no undefined-variable instructions in shipped docs.
- [ ] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                   | Impact | Probability | Mitigation                                                                              |
| ------------------------------------------------------ | ------ | ----------- | --------------------------------------------------------------------------------------- |
| Blind find-and-replace breaks self-contained snippets  | Medium | High        | Phase 1 classifies before Phase 2 edits; class-(b) snippets are explicitly preserved    |
| Sweep silently rewrites the docs that EXPLAIN the trap | Medium | Medium      | Named in Non-Goals and asserted in Task 3.1's exemption list                            |
| Gate exemptions become a dumping ground                | Low    | Medium      | Exemptions must cite the class from Phase 1 evidence, not be added to silence a failure |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Plan created from the v3.50.0 release code-review finding; inventory measured
  at 223 occurrences across 23 files.
- Phases 1–3 delivered: 297 variant-1/2 occurrences and 65 variant-3 occurrences
  corrected across 30 files; gate widened to `CLAUDE/`, `docs/`, `examples/` and
  given its first test file; QA 14/14; daemon RUNNING.
- Phases 4–6 delivered at `73b76462` / `56f5e732`: client-fixture verification
  found 38 doc violations, 5 skill launchers and 7 real client-mode bugs.
- Phase 7 delivered: assignment-aware `_LEGACY_VENV_PATH` rule closes the
  residual class (Decision 3). QA 14/14; daemon RUNNING.
