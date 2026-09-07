# Plan 00340: release review followups v3621

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.62.1 release's blocking code-review gate produced findings beyond the
six confirmed defects that were fixed before tagging. This plan holds the
remainder, so nothing is dropped — the project's standing rule that a
non-blocking finding becomes a follow-up plan rather than a note in a report
nobody re-reads.

Source report: `untracked/agent-reports/260907-release-review-opus.md`, which
also lists a reproduction script per finding under `untracked/scratch/`. Those
are gitignored, so each finding below restates its reproduction rather than
relying on the path surviving.

## Goals

- Decide what the supervisor's blind Enter should do when a modal dialog is on
  screen, on evidence rather than reasoning.
- Remove the duplicated `_walk_into`, which this release had to patch twice.
- Close two upgrade-script robustness gaps in `config_preserve.sh`.

## Non-Goals

- Re-litigating the v3.62.1 bump. PATCH follows this project's own semver table
  (no new handlers, no new config options, all changes bug/security fixes); the
  reviewer's dissent is recorded in Delivery below.
- Re-opening the six defects fixed before tagging. They shipped with tests.

## Tasks

### Phase 1: The resubmit Enter versus a modal dialog

- [ ] ⬜ **Task 1.1**: Reproduce, do not reason. `Decision.WOULD_RESUBMIT`
  presses Enter when the machine is in `AWAIT_COMPACTING`, the session is
  keystroke-idle and the input line is modelled empty. A Claude Code MODAL
  dialog — a permission prompt, a plan-approval prompt, a trust-folder prompt —
  satisfies all three, and Enter there CONFIRMS the highlighted default. The
  codebase already knows Enter confirms dialogs: that is what `confirm_enters`
  and `_MODEL_CONFIRM_DELAY_SECONDS` exist for. Drive a real Claude Code over a
  PTY (the Plan 00339 probes under `untracked/scratch/tui_*.py` are the rig),
  open a permission prompt, and observe what attempt 2 does.
- [ ] ⬜ **Task 1.2**: If it confirms a dialog, find a signal the supervisor can
  read that says one is on screen. Note what was already ruled out: the
  human-input-blockage marker is written from a Stop event's `STOPPING BECAUSE:`
  text, so it does not fire for a UI prompt.
- [ ] ⬜ **Task 1.3**: Weigh against the existing mitigations before changing
  anything — ESC is always attempt 1, so any dialog that dismisses on ESC is
  gone before an Enter can fire; dry-run is the default; the decision is logged
  with its own reason.

### Phase 2: Deduplicate `_walk_into`

- [ ] ⬜ **Task 2.1**: `docs_qa/checks/module_doc_budget.py` and
  `docs_qa/checks/source_tree_markdown.py` carry near-identical `_walk_into`
  functions. The v3.62.1 bundle had to apply the same fix to both, which is the
  standard warning that the next fix will miss one. They differ only in the
  `scope_exclude_globs` tail, so a shared helper taking an optional predicate
  covers both.

### Phase 3: `config_preserve.sh` robustness

- [ ] ⬜ **Task 3.1**: `resolve_old_default_config` leaks a temp file per run,
  and uses a handed-over `HOOKS_DAEMON_OLD_DEFAULT_CONFIG` SILENTLY whenever the
  file exists — it warns only when the path is missing. A stale export from an
  earlier run in the same shell is therefore used as the upgrade baseline
  without a word. Record a version or timestamp in the handover and warn on a
  mismatch.
- [ ] ⬜ **Task 3.2**: Three sites capture the CLI with `2>&1` into a command
  substitution that is then parsed as JSON. The exit code is checked first, so
  this only bites when the CLI SUCCEEDS and also writes to stderr — at which
  point `json.loads` fails and the upgrade reports "Failed to write merged
  config" for a run that actually worked. Capture the two streams separately.

### Phase 4: A heredoc whose redirect follows the opener

- [ ] ⬜ **Task 4.1**: `cat <<'X' > doc.md` is denied while `cat > doc.md <<'X'`
  is allowed. `_QUOTED_HEREDOC_BODY_PATTERN` requires a newline immediately
  after the delimiter, so the first spelling is not recognised as a heredoc at
  all and its raw body is scanned. Same for a delimiter containing a non-word
  character. Pre-existing, and the same family as the brace-group regression
  fixed in v3.62.1.
- [ ] ⬜ **Task 4.2**: If not fixing, say so in the handler's `get_claude_md`
  guidance — an agent that hits this needs to know which spelling works.

## Success Criteria

- [ ] The modal-dialog question is answered by observation, and whatever it
  implies is either shipped or recorded as a deliberate accepted risk.
- [ ] `_walk_into` exists once.
- [ ] A stale config-preservation baseline cannot be used silently.
- [ ] Both heredoc redirect spellings agree, or the difference is documented
  where an agent will actually read it.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00340-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: the v3.62.1 release code-review gate.
- **Versioning dissent, recorded rather than resolved**: the reviewer argued the
  v3.62.1 bundle reads as MINOR under general semver — it adds a decision family
  to a deployed artefact, inverts an allowlist in a priority-10 handler (with a
  new false-positive class), changes config-preservation semantics and adds a
  second-pass re-exec of the upgrade script. It shipped as PATCH because this
  project's semver table keys on features versus fixes: MINOR is "new
  handlers/features, config options", PATCH is "bug fixes, security patches,
  docs", and the bundle contains no new handler, feature or config option. The
  disagreement is about the table, not about the bundle, so it belongs here.
