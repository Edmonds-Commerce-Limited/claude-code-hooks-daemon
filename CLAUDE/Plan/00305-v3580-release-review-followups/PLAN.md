# Plan 00305: v3580 release review followups

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Non-blocking findings ledger from the v3.58.0 release Code Review Gate
(RELEASING.md Step 10), per the "Never drop a finding" rule (Plan 00157).
The blocking finding (blockage marker never cleared) and two cheap
non-blocking findings (duplicate project-name generation in the two
migration/advisory generators; goal_injection latch ordering) were fixed
before the release shipped. The three findings below were deferred to this
tracked MUST-FIX ledger and are to be fixed immediately after the release.

## Goals

- Every deferred v3.58.0 review finding is fixed with TDD, or explicitly
  ruled out by the owner with the ruling recorded here.

## Non-Goals

- Re-reviewing the v3.58.0 diff; the findings list below is the full
  deferred set.

## Tasks

### Phase 1: Deferred MUST-FIX findings

- [ ] ⬜ **Task 1.1** (review finding 3, MEDIUM):
  `src/claude_code_hooks_daemon/daemon/cli.py:148,178` — `unittest.mock.patch`
  imported and used in shipped CLI code (`_collect_enforcement_status_lines`
  wraps three handler constructions in
  `patch.object(ProjectContext, "project_root", ...)`, mutating the class
  process-wide). Remediation: let those handlers construct without a live
  `ProjectContext` (optional root argument or lazy resolution at first use),
  then delete the patch and the import.
- [ ] ⬜ **Task 1.2** (review finding 4, MEDIUM):
  `src/claude_code_hooks_daemon/utils/repo_relative_path.py:135` —
  `expand_repo_root_token` raises `ValueError` for a misplaced `{REPO_ROOT}`
  token at four unguarded call sites (`daemon/controller.py:474`,
  `daemon/cli.py:114,224,235`), surfacing as a startup exception or CLI
  traceback instead of a named config error. Remediation: add a
  `field_validator` on the two token-accepting exempt fields
  (`PluginConfig.path`, `ProjectHandlersConfig.path`) checking token
  PLACEMENT only (not repo-relativity).
- [ ] ⬜ **Task 1.3** (review finding 5, MEDIUM, security-relevant):
  `src/claude_code_hooks_daemon/utils/secret_redaction.py:222` — an absolute
  configured `secret_word_list_path` is silently replaced by the default
  `.claude/block-words.secret`, which likely does not exist on such a repo,
  and a missing secret file is inert by design — so secret-term blocking
  stops enforcing with only a `logger.warning` as evidence. Remediation:
  keep the zero-absolute-paths ruling but surface the degrade where a human
  sees it — a `check` advisory line or a startup degraded entry.

### Phase 2: v3.58.0 acceptance-run playbook drift

- [ ] ⬜ **Task 2.1**: Playbook expected-message drift — many generated
  expected patterns still cite long-form literals (`SECURITY ANTIPATTERN BLOCKED`, `TDD REQUIRED`, `dangerous permissions`, `Error-hiding pattern detected`) that the live short-form `BLOCKED [R-*]` deny messages no
  longer contain (denials themselves correct throughout). Regenerate the
  playbook generator's expected patterns from the current message forms.

- [ ] ⬜ **Task 2.2**: Playbook Test 124 `valid.py` fixture lacks a
  trailing newline, so the "valid" case is denied on ruff W292 as written.

- [ ] ⬜ **Task 2.3**: Playbook Tests 39/40 (artifact_publish_blocker) are
  marked `Requires Main Thread: no` but the Artifact tool is not exposed
  to sub-agents (and is source-disabled in never_want sessions) — routing
  field should be `yes`, or the tests should document the source-disable
  skip.

- [ ] ⬜ **Task 2.4**: Playbook Test 110 (ESLint deny path) is
  unexecutable in this repo — needs `llm:` scripts in a tracked
  package.json; document the precondition or synthesise a fixture.

- [ ] ⬜ **Task 2.5**: secret_file_guard false positive (reported by the
  clippy-shim-fix agent): an Edit whose new content contained the literal
  Python list `[pass_result, fail_result]` was blocked as matching the
  `*vault_pass*`-family protected glob, despite no vault/password content.
  Reproduce, pin with a test, and tighten the substring/glob matching.

- [ ] ⬜ **Task 2.6**: pipe_blocker producer attribution for a plain
  quoted-argument pipe under a `[[` head (playbook Test 87,
  `[[ "python -m pytest tests/ | tail -5" == 0 ]]`): the deny is correct and
  the expected patterns match, but the headline names the producer as
  `[[ unrecognized` (with a fabricated `^[[\b` extra_whitelist suggestion)
  instead of pytest, and the printed echd-capture remediation line is
  malformed (`[[ "python -m pytest tests/ 2>&1 | ...`). Attribute the
  producer inside the quoted argument (as the `$( )` path already does,
  Test 86) and emit a runnable remediation.

## Success Criteria

- [ ] All three findings fixed with TDD (or owner-ruled-out with the ruling
  recorded), QA green, daemon restarted and verified.

## Delivery & Milestones

- (none yet)
