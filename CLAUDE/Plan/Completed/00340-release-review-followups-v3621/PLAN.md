# Plan 00340: release review followups v3621

**Status**: Complete
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

- [x] ✅ **Task 3.1**: **Done, and the leak was narrower than reported.**
  Step 10 already had a positional `rm`, so the leak is every early exit
  between Step 5 and Step 10 — and that `rm` also deleted Layer 1's handover,
  a file Layer 2 does not own. Ownership is now explicit:
  `cleanup_old_default_config` removes only a path carrying this module's own
  mktemp prefix, called from Layer 2's EXIT trap; Layer 1 removes its own
  preserved baseline in its EXIT trap.

  For staleness, the stamp is the OWNING PROCESS (`HOOKS_DAEMON_OLD_DEFAULT_PID`),
  not a version or timestamp. A version cannot be checked — post-checkout,
  Layer 2 has no independent idea of which version it is upgrading from, so a
  stale pair would be self-consistent. What a leftover export cannot fake is a
  live owner: Layer 1 waits for Layer 2, so the documented path always has one.
  The baseline is still USED (the resolver's contract is to fail open, and a
  false negative — no `ps`, a recycled PID — must not break the documented
  path); it just cannot be used silently.

- [x] ✅ **Task 3.2**: **Done.** `run_with_split_streams` captures the two
  streams apart and `relay_cli_diagnostics` passes stderr through to the user,
  so the payload stays parseable without the warnings disappearing. Applied to
  all five captures, not the three named: the two `python -c` blocks had the
  same shape, and one of them compared its output to the literal `"OK"`, so any
  stderr line would have reported a successful write as a failure. The JSON now
  reaches those blocks on a herestring rather than a pipe — a pipe would run
  the helper in a subshell, where its two variables are set and thrown away.

  A static guard covers the file as a whole, because the rule is general and
  the next `2>&1` added to a captured CLI call would be the same defect under
  a different function name.

### Phase 4: A heredoc whose redirect follows the opener

- [x] ✅ **Task 4.1**: **Fixed.** The opener line may now carry anything after
  the delimiter (`[^\n]*`), and the delimiter charset is `[\w.\-]+` so
  `<<'EOF-1'` and `<<'END.MD'` are recognised. Widening the delimiter made the
  closer's missing anchor matter, so it gained a `(?![\w.\-])` lookahead — a
  body line reading `EOFDATA` was closing an `EOF` heredoc early and exposing
  everything after it.

  **Caught while fixing**: the blanking rewrite drops whatever it does not
  capture, and the opener line's trailing text is usually a REDIRECT. Erasing
  it would have hidden `cat <<'EOF' > /etc/hosts` from `project_containment` —
  a hole opened by the fix itself. The tail is captured and re-emitted, with a
  test: blanking a body must remove no evidence except the body.

- [x] ✅ **Task 4.2**: **Done anyway, as reassurance rather than a warning.**
  `pipe_blocker`'s guidance already used one spelling; it now says explicitly
  that the redirect's position makes no difference and that a punctuated
  delimiter counts, so an agent who met the old behaviour does not carry the
  wrong lesson forward.

## Success Criteria

- [x] The modal-dialog question is answered by observation, and whatever it
  implies is either shipped or recorded as a deliberate accepted risk.
- [x] `_walk_into` exists once.
- [x] A stale config-preservation baseline cannot be used silently.
- [x] Both heredoc redirect spellings agree, or the difference is documented
  where an agent will actually read it.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00340-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: the v3.62.1 release code-review gate.
- **Phase 1** — `6d0aad13` pulls the supervisor's blind Enter in behind its own
  escape (`_RESUBMIT_FOLLOW_SECONDS`), shrinking the modal-confirm window from
  60s to one poll.
- **Phase 2** — `346b8d84` gives both tree-walking docs-QA checks one shared
  `corpus.walk_into`, and fixes the `repo_hygiene` false positive that surfaced
  while doing it.
- **Phase 3** — `3a9fab9f` splits the upgrade CLI's streams so a diagnostic
  cannot corrupt the JSON payload, and gives the diff baseline an owner so it
  is neither leaked nor silently stale.
- **Phase 4** — `c9dfd4a8` recognises a heredoc whose redirect follows the
  delimiter, and keeps that redirect visible to the handlers that judge it.
- **Versioning dissent, recorded rather than resolved**: the reviewer argued the
  v3.62.1 bundle reads as MINOR under general semver — it adds a decision family
  to a deployed artefact, inverts an allowlist in a priority-10 handler (with a
  new false-positive class), changes config-preservation semantics and adds a
  second-pass re-exec of the upgrade script. It shipped as PATCH because this
  project's semver table keys on features versus fixes: MINOR is "new
  handlers/features, config options", PATCH is "bug fixes, security patches,
  docs", and the bundle contains no new handler, feature or config option. The
  disagreement is about the table, not about the bundle, so it belongs here.
