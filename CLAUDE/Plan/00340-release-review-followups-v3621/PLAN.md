# Plan 00340: release review followups v3621

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Reproduce, do not reason. **Done — the risk is
  CONFIRMED.** Drove a real Claude Code v2.1.263 over a PTY with the `/model`
  picker open, which states the bindings itself: "Enter to set as default · s
  to use this session only · Esc to cancel". A bare Enter answered "Set model
  to Opus 5 and saved as your default for new sessions" — a persisted change
  the human never asked for. ESC answered "Kept model as Opus 5". So a blind
  Enter does confirm a modal's highlighted default, and ESC does dismiss it.

- [x] ✅ **Task 1.2**: Find a signal saying a dialog is on screen. **Not
  needed — superseded by 1.3.** The ordering fix removes the hazard without
  needing to detect the dialog at all, which is better than screen-scraping a
  TUI whose rendering is not a contract.

- [x] ✅ **Task 1.3**: Weigh against the existing mitigations. **Done, and the
  gap was in PROXIMITY, not ordering.** ESC was already attempt 1, so any
  dialog open when the episode began was dismissed before an Enter could fire.
  What the full `escape_after_seconds` left open was a dialog appearing AFTER
  that escape: it was still on screen a whole minute later when the Enter
  fired. `_RESUBMIT_FOLLOW_SECONDS` (2.0s) now paces a resubmit behind its own
  escape instead, so an Enter is always closely preceded by a dismissing ESC.
  Verified on the same rig that the pairing stays correct for the other cases:
  with text in the box, ESC-pause-Enter still SUBMITS it (one ESC does not
  clear the box); Enter on an empty box is a no-op; with a dialog open,
  ESC-pause-Enter leaves the default unconfirmed.

  **Deliberately not done: a single new "escape then enter" decision.** The
  decision names and payloads are the worker→host protocol, and the host NEVER
  hot-reloads — a new worker talks to the OLD host until the ccy session
  restarts. That host would reject an unknown decision value, or paste a raw
  ESC as literal text. Shortening an interval needs no agreement from either
  side, which is why it was chosen over the cleaner-looking refactor.

### Phase 2: Deduplicate `_walk_into`

- [x] ✅ **Task 2.1**: **Done.** `corpus.walk_into` is now the one copy, with
  `corpus.OWN_EXCLUDED_DIR_NAMES` beside it — that constant was duplicated too.
  `module_doc_budget` passes its `scope_exclude_globs` prune as the
  `also_prune` predicate; `source_tree_markdown` passes nothing. The shared
  semantics are unit-tested once in `test_corpus.py`; each check's own test
  now asserts the WIRING through its real walk (`_iter_module_doc_paths` /
  `_iter_markdown_paths`) rather than poking a private helper, so a check that
  quietly stopped calling the shared function would fail.

- [x] ✅ **Task 2.2**: **Found and fixed while doing 2.1** —
  `repo_hygiene`'s `ignored-plan-document` rule flagged
  `__pycache__/probe_walk.cpython-311.pyc` as a silently-ignored plan
  document. Plans keep probe scripts, and importing one writes bytecode beside
  it: gitignored, untracked, so inside the rule's set without being a document
  at all, and the remediation it offers (anchor the pattern so the file gets
  tracked) is actively wrong for bytecode. Excluded `__pycache__`/`.pyc`/`.pyo`
  only — an ignored `.py` probe is still a real silent loss and is still
  flagged, which is pinned by a test.

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
