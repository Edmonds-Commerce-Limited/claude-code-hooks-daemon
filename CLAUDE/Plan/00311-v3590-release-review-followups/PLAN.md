# Plan 00311: v3590 release review followups

**Status**: Not Started
**Created**: 2026-09-01
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Agent

## Overview

The v3.59.0 release code review (`untracked/agent-reports/260901-code-reviewer-release-v3590.md`)
raised two BLOCKING findings (fixed before release: a `secret_file_guard`
both-edges-wildcard regression, and the `/optimise` skill not being deployed
to clients) and seven NON-BLOCKING findings. Four of the seven were fixed
directly during the same pass (N3 option coercion, N4 `git -C` support, N6
verified-not-dead, N7 docstring). This plan is the never-drop-a-finding
ledger (RELEASING.md, Plan 00157 rule 2) for the three that were explicitly
deferred: N1, N2, N5.

## Goals

- Each of N1/N2/N5 below is either fixed (with TDD where it touches
  behaviour) or explicitly rejected with a recorded reason.

## Non-Goals

- No new features; no re-litigating the fixed BLOCKING findings (B1, B2) or
  the four NON-BLOCKING findings already fixed in the same release pass
  (N3, N4, N6, N7).

## Tasks

### Phase 1: Deferred non-blocking findings from the v3.59.0 release review

- [ ] ⬜ **Task 1.1 (N1)**: `dispatch_declaration` hardcodes `CLAUDE/Plan/`
  while its comment claims configurability
  (`src/claude_code_hooks_daemon/handlers/pre_tool_use/dispatch_declaration.py:44-48`
  — `_PLAN_PATH_PATTERN = re.compile(r"CLAUDE/Plan/\d{5}-", ...)`). A project
  with a non-default `plans_directory` can never satisfy declaration option 1
  (naming its plan folder), so the advisory fires on every compliant
  dispatch, and in opt-in strict mode DENIES it. Fix: read the configured
  plan directory (same source `plan_workflow`/`plan_number_helper` use) and
  build the pattern from it, or correct the comment if a fixed pattern is
  intentional.

- [ ] ⬜ **Task 1.2 (N2)**: the glob heuristics in
  `src/claude_code_hooks_daemon/utils/secret_file_matching.py::find_protected_mention`
  are now heavily special-cased (~40+ lines of comment across four gates —
  residue length, substring, both-edges-wildcard near-total-match, and the
  leading-wildcard-only overlap check — each added by a different plan after
  a different live false positive/false negative). This is a heuristic
  patched per incident rather than re-derived, and is the highest-risk
  maintenance surface in the file (B1 in the v3.59.0 review was exactly this
  kind of hole). Consider a from-scratch re-derivation with a single
  documented model (e.g. "does the token's residue, positioned per its
  wildcard edges, plausibly reconstruct the stem's literal text") backed by
  the full existing adversarial test corpus in
  `tests/unit/utils/test_secret_file_matching.py`, rather than another
  incremental gate. Judgement call — may be rejected if the current
  incremental structure, despite the maintenance cost, is judged safer to
  touch than a rewrite.

  **A fifth gate has since been added, which is evidence FOR the
  re-derivation rather than against it.** The shipped default glob matches by
  substring, and a dotted Python module path incidentally produces the
  substring it keys on — so the guard denied any file that imported the
  guard's own module, and the only way to reference the handler was an
  indirect module-object import. Fixed at `c8ce2d7a` by exempting a token
  that appears as the target of an `import` statement, since an import cannot
  read a file's contents.

  Two things about that incident belong in this task's evidence:

  - It is the same failure this task predicts — a live false positive
    answered with one more special case, making the sixth incident likelier
    rather than less likely.
  - The fix is incomplete by construction, and deliberately so. It covers the
    Write/Edit content surface only; the SAME false positive still fires on
    the Bash surface, where a `git commit` message mentioning the module in
    dotted form is denied as a protected-path mention. That was worked around
    at the time by naming the file rather than the module, which is a better
    commit message anyway — but it means the underlying heuristic is still
    wrong, in a second place, and no gate added to `find_protected_mention`
    will reach it.

- [ ] ⬜ **Task 1.4 (R5, incremental re-review)**:
  `src/claude_code_hooks_daemon/utils/secret_file_matching.py::_is_git_rm_cached`
  special-cases `words[1] == "-C"` (jumping the subcommand index to 3)
  instead of skipping leading global git flags generically. Verified
  fail-closed and no widening — `git -C /repo rm --cached <p>` and
  `git -C /repo rm -r --cached <p>` are correctly exempt; `git -C /repo rm --cached=x <p>`, `git -c core.pager=cat rm --cached <p>`, `git -C /repo --no-pager rm --cached <p>` are correctly NOT exempt (same usability gap
  N4 described, one layer out — a real hygiene-recommended invocation with
  an unrelated global flag still gets no exemption). Fix: replace the single
  `-C` special case with a small loop that skips leading global flags
  (`-C <path>`, `-c <key>=<value>`, and other value-taking globals),
  consuming a value where the flag needs one, before locating the
  subcommand.

- [ ] ⬜ **Task 1.5 (R6, incremental re-review)**: three independent
  hand-rolled coercions of a blind-`setattr` YAML handler option exist with
  no shared helper — `_is_strict()` and `_threshold()` in this same module,
  plus a third instance cited by both of their docstrings in
  `bash_safe_mode._min_statements`. The behaviours diverge in a way that is
  not obviously intended: `_threshold()` parses a numeric STRING (`"4000"`
  -> `4000`), while `_is_strict()` accepts only the literal strings
  `"true"`/`"false"` and silently returns `False` for `strict: 1` or
  `strict: yes` — both plausible YAML spellings of "on". Both directions are
  fail-safe (no defect today), so this is a maintenance-cost finding, not a
  correctness one. Fix: extract one shared `coerce_bool_option` /
  `coerce_int_option` pair (or a single typed-coercion helper) and migrate
  all three call sites, or explicitly reject if the three sites are judged
  too heterogeneous (different option semantics) to share a helper safely.

- [ ] ⬜ **Task 1.3 (N5)**: the `git rm --cached` exemption in
  `src/claude_code_hooks_daemon/utils/secret_file_matching.py::_is_git_rm_cached`
  matches `--cached` ANYWHERE after the `rm` subcommand, so
  `git rm --dry-run --cached x` and `git rm -r --cached x` are exempt.
  Verified this is CORRECT rather than incorrect (neither reads content, and
  a compound command like `git rm --cached a && cat b` correctly stays
  non-exempt) — recorded here for completeness per the review's request, not
  because a fix is expected. Likely disposition: close as "verified correct,
  no action" after a second look confirms no reachable content-disclosure
  shape through this looseness.

## Success Criteria

- [ ] N1, N2, N5 each have a disposition (fixed-with-tests, or explicitly
  rejected with a recorded reason) linked from this plan's closing journal
  entry.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00311-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed during the v3.59.0 release fix pass (see
  `untracked/agent-reports/260901-code-reviewer-release-v3590.md` for full
  finding text).
