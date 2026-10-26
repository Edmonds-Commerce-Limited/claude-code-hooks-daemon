# Plan 00552: conflict marker hook bricking

**Status**: Complete
**Created**: 2026-10-26
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A git merge, rebase or stash pop in a client project can leave conflict markers in the files the daemon owns:

- the hook stubs in `.claude/hooks/`;
- `.claude/init.sh`;
- `.claude/settings.json`.

A bash script that hits a `<<<<<<<` line fails to parse and exits 2. Claude Code reads a hook's exit 2 as **block**. So instead of failing open, every event is blocked, including UserPromptSubmit, and the session cannot take a prompt. The owner hit this in a client project: PostToolUse, PostToolBatch and UserPromptSubmit all failed with "syntax error near unexpected token `<<<'", and the status line reported `settings.json is not valid JSON`. A local repro confirms exit 2 for both a conflicted stub and a conflicted sourced `init.sh\`.

The defence comes in layers:

- stubs that fail open when `init.sh` does not parse;
- an installer-written `.gitattributes` that stops git writing markers into daemon-owned files at all;
- a terminal-runnable repair verb that restores a broken install in one command.

## Goals

- **Exit 2 only by intent.** A corrupted `init.sh` never makes a hook stub exit 2. The stub fails open with a non-blocking message that names the broken file and the repair command.
- **No markers in daemon-owned files.** A merge conflict on a daemon-owned file leaves one side intact on disk, with no markers. The installer and upgrade write `.gitattributes` `-merge` rules for those paths.
- **One-command repair from outside the session.**
  - It redeploys the stubs and `init.sh` from the installed templates.
  - It checks every hook with `bash -n`.
  - It reports whether `settings.json` parses.
  - It reconciles `settings.json` only when a human runs it explicitly. This respects Plan 00175: the daemon never rewrites settings.json on its own.
- **Documented recovery.** The manual steps live in docs/guides/TROUBLESHOOTING.md, for the case where the stub itself is conflicted.

## Non-Goals

- Making a conflicted stub repair itself. A file with markers in it cannot parse at all; `.gitattributes` and the repair verb cover that case.
- Automatically rewriting `settings.json` from a hook (Plan 00175).
- Regenerating the forwarders through the generator, which is Plan 00421 Task 5.2. Coordinate on stub template edits, because both plans touch the same files.

## Tasks

### Phase 1: Fail open on a corrupt `init.sh`

- [x] ✅ **Task 1.1**: Write failing tests first: a stub whose `init.sh` contains conflict markers must exit 0, emit a non-blocking error naming the file and the repair command, and never exit 2. Cover every event stub, and UserPromptSubmit and Stop in particular.
- [x] ✅ **Task 1.2**: Add the `bash -n` guard to the stub template(s) and regenerate the deployed stubs. Measure the hot-path cost: the relay hot path runs before `init.sh`.

### Phase 2: Prevent markers

- [x] ✅ **Task 2.1**: The installer and upgrade write or merge a managed block in the project `.gitattributes` with `-merge` for `.claude/hooks/**` and `.claude/init.sh`. Decide on `settings.json` and record the decision. Tests: an install creates the block; a re-install is idempotent; any user lines already in the file survive.
- [x] ✅ **Task 2.2**: Add an integration test with a real git repo: two branches change a stub, the merge conflicts, and the file on disk has no markers and passes `bash -n`.

### Phase 3: Repair verb

- [x] ✅ **Task 3.1**: Add a `repair-install` verb, or extend `repair` (prior art: Plan 00456). It redeploys the stubs and `init.sh`, runs `bash -n` on every hook, and validates `settings.json` (`reconcile-settings` only with an explicit flag). It must run with no working session and no running daemon.
- [x] ✅ **Task 3.2**: Make the Phase 1 error message and the status line's "settings.json is not valid JSON" both name the repair command. The parse-guard message names `repair-install`. No daemon status-line code emits "settings.json is not valid JSON", so it is most likely Claude Code's own text and there was nothing to change. The daemon does print "is not valid JSON" from `settings_merge.py` and the CLI, but not on the status line. Journalled as a decision.

### Phase 4: Docs

- [x] ✅ **Task 4.1**: Write the TROUBLESHOOTING recovery section, covering terminal steps, rebase ours/theirs inversion, `claude --resume`, and the release-notes entry.

## Success Criteria

- [x] A conflict-marked `init.sh` gives a non-blocking hook result on every event, proven by tests (`tests/unit/install/test_forwarder_init_parse_guard.py`, 135 cases).
- [x] A real-git merge conflict on a daemon-owned file leaves a file that parses, proven by an integration test (`tests/integration/test_gitattributes_merge_conflict.py`).
- [x] The repair verb restores a corrupted install from a terminal, proven by a test (`tests/unit/install/test_repair_install.py`).
- [x] Release-bound consequences (new `.gitattributes` block, new verb, stub change) are recorded in `CLAUDE/UPGRADES/UNRELEASED/release-notes/003-conflict-marker-hook-bricking.md`.

## Delivery & Milestones

- Phase 1 (parse guard): merge `a5a2e6970`; magic-value fix `1b8c527bf`.
- Phase 2 (`.gitattributes` block): merge `b5c7d834c`.
- Phases 3-4 (`repair-install`, troubleshooting): merge `5612cce6d`.
- Full gate on `65e8baf03`: 158631 passed. The only failures are the 8 `test_relay_repair` `setsid` cases, which pass alone and also failed on the gate before Phase 1 (ledger 00474 N541). The dependency check passed once the QA venv was synced to `uv.lock`.
