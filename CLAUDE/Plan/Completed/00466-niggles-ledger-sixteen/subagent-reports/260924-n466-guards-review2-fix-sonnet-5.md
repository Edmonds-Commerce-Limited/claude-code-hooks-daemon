# Phase 3: guard-defects security review 2 — fixes

**Agent**: Sonnet 5, `worktree-n466-guard-defects`
**Source review**: `260924-n466-guards-review2-opus-5-5.md`
**HEAD**: `3e3164bd`

## Summary

Every finding in the review is fixed or dispositioned, TDD throughout (RED
confirmed before every fix). Targeted QA is clean (9/9). Full targeted test
suite: 645 passed across `test_secret_file_matching.py`,
`test_secret_file_guard.py`, `test_project_containment.py`,
`test_path_exclusion.py`, `test_flaggable_content_channel_guard.py`,
`test_quarantine_artefact_read_guard.py`, `test_payload_capture.py` and
`.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py`. Full
project-handler suite: 216 passed.

## Blocker

**B1** (timing fail-open) — fixed. `secret_file_matching._globs_can_intersect`
collapses consecutive `*` runs and caps its own DP work at 20,000 cells,
treating an over-cap pair as intersecting (fail closed) rather than paying
for the grid. `iter_protected_mentions`/`find_protected_mention_detail`
gained an optional `deadline` keyword, wired into both
`secret_file_guard.py` call sites via a shared `SCAN_DEADLINE_SECONDS`
(5.0s); exceeding it raises `TimeoutError`, which routes through the
existing N11 fail-closed wrapper rather than silently truncating the scan.
5 new timing tests pin the review's own measured shapes (the 60 KB
bracket-and-star bypass, 200 bracket-and-star tokens, a 1 MB ordinary
`a*b`-token Write, a lone 60,000-character `*` run, and the deadline route
itself) — all comfortably under budget where the pre-fix branch measured
15-35s.

## Major

**M1** (`enforce_llm_qa` 19 regressions) — fixed. String-executor arguments
(`*sh -c/-lc`, `eval`, `ssh <host>`, `watch`, `su -c`, `timeout … <shell> -c`, `python* -c`) are re-parsed recursively as their own shell text;
`_PUNCTUATION_CHARS` gained `<`/`>` so a glued redirection splits into its
own token; a word is checked against the script after resolving any brace
alternation or trailing-glob shape it carries — the brace-expansion route
matches raw command TEXT rather than shlex tokens, since `{`/`}` are
themselves punctuation chars needed for `{ cmd; }` group syntax and would
otherwise tear a real brace group apart before it could be recognised. 8 new
test methods cover all 19 regressions; 53/53 in that file pass, no
regressions in the other 45 pre-existing tests.

**M2** (N10 gaps: both-edges patterns, edge+interior tokens, unenumerable
brackets, brace expansion) — fixed, all four sub-parts:

- (a) The DP-intersection check now runs for edge-open tokens too, against
  every pattern that is not both-edges — gated by a new
  `_dp_intersection_is_meaningful` check, an OWN finding not in the review:
  a leading-wildcard token compared against a trailing-wildcard pattern (or
  vice versa) intersects UNCONDITIONALLY for any literal on either side (a
  simple concatenation always satisfies both), which would have denied an
  ordinary token like a bare glob ending in `.py` against the shipped
  leading-anchor vault-password-prefix pattern. Caught by this branch's own
  RED test before it shipped, not by the review.
- (b) An unenumerable bracket expression (`[!x]`, `[^x]`, `[[:alpha:]]`, an
  over-cap range) is substituted with `?` in the DP — a safe superset. A
  companion regex fix was needed for the POSIX named-class form: the
  general bracket regex's `[^\]]*\]` stops at the class's OWN closing `]`,
  one character short of the real outer close.
- (c) Both-edges patterns get a filesystem-truth route
  (`_both_edges_glob_mention`): the token's glob is expanded against the
  HOOK's cwd (not the daemon's own), capped, and denies only when a real
  on-disk file matches. Gated by a cheap literal-overlap pre-filter
  (`_shares_min_literal_substring`) — an OWN finding: calling this
  unconditionally for every glob-shaped token measurably broke this
  module's own pre-existing B1 timing budgets (a 60,000-`*` token went
  from well under 0.1s to 8.45s; twenty short wide-bracket tokens from
  under 0.05s to 0.082s), because real disk I/O has a floor cost a pure DP
  calculation does not.
- (d) Brace groups are expanded against the raw command text before
  tokenising, mirroring M1's fix. The first attempt used a
  `\S*\{[^{}]*\}\S*` regex, which turned out to be CATASTROPHICALLY slow on
  adversarial input with no braces at all — the same 60,000-`*` fixture
  from (c) went to 5.7s just from `_brace_expanded_tokens`'s own
  `findall()`. Fixed with a bounded manual boundary scan anchored on the
  (non-backtracking) brace-group regex instead, capped at 500 matches.

16 new tests across 4 classes in `test_secret_file_matching.py`. Full
`test_secret_file_matching.py` + `test_secret_file_guard.py` +
`test_path_exclusion.py` + `test_project_containment.py`: 463 passed.

**M3** (`daemon.strict_mode` inert) — deliberately NOT touched, per
team-lead's instruction. Filed on main as N24, a separate agent
(`n466-n24`) is fixing it there.

## Minor

**m1** (`handle()` outside the fail-closed wrapper) — fixed for both
`secret_file_guard.py` and `project_containment.py`. `handle()`'s real body
now runs inside a try/except (`_build_deny_result`), denying with the
exception's TYPE if anything downstream of a real match raises (the
disclosure tracker, `RuleFormatter`, string building). 6 new tests (3 per
guard: a `get_data_layer`/`project_root` failure, a `RuleFormatter.verbose`
failure, and the review's own unhashable-`transcript_path` case).

**m2** (`matches()`/`handle()` independent re-evaluation) — fixed for both
guards. Each now caches one evaluation per dispatch behind a
`_DispatchKey`-keyed one-shot bridge (the same shape `sensitive_content`
already uses): `matches()` computes and caches, `handle()` consumes the
cache when the dispatch key matches, else recomputes defensively. 2 new
tests, each confirmed to reproduce the review's exact bug (a transient raise
silently overwritten by a clean re-evaluation) against the pre-fix code path
before the fix was restored.

**m3** (sibling audit gaps: `destructive_git` timing, `sensitive_content`
NUL-byte raise) — **not fixed here, dispositioned as follows** (per
team-lead's correction, superseding this branch's own now-reverted N32
entry):

- `destructive_git`'s super-linear `strip_inert_spans` (99s on a 200 KB
  `git commit`) is already filed on main as **N25**, which a separate agent
  (`n466-n24`) is fixing there with a linear rewrite plus a 200 KB timing
  test, alongside the chain-level deadline. Confirmed against
  `git show main:.../NIGGLES.md` that N25 already covers both timing
  measurements the review's m3 names (destructive_git's 99s/98s, and this
  branch's own B1 DP fix) — nothing to add there.
- `sensitive_content`'s NUL-byte raise (`ValueError: embedded null byte`
  from `realpath`, 485 of 12000 fuzzed payloads in the review's own probe)
  is **not covered by N25** — N25 is scoped to timing, not raise paths. Not
  independently exploitable (a NUL path cannot be written), but under M3
  (once fixed) a raise there is a fail-open the same as everywhere else.
  Worth a one-line addition to N25 or a new entry, at the ledger owner's
  discretion.

**m4** (ledger/release-note overstatement) — fixed. Corrected in
`NIGGLES.md`:

- **N5** and **N11**: both originally claimed this repository's own
  `strict_mode: true` made a guard's crash deny rather than fail open. Per
  team-lead's explicit instruction, both are corrected in place — each now
  states the claim is false, corrected by N24, with the live-verified
  reason (`daemon.strict_mode` never reaches the real startup path).
- **N6**: a correction paragraph appended, noting the "restoring
  deny-by-default"/"Only the WORD SPLITTING changed" claims were overstated
  (19 further regressions), with a pointer to this branch's M1 fix.
- **N10**: a correction paragraph appended, noting the "interior … globs of
  each shipped protected pattern" acceptance criterion was not met for 2 of
  6 patterns, with a pointer to this branch's M2 fix.
- Release notes **13** and **15** (N4's and N6's own callouts): both
  corrected with a short addendum pointing at the new release notes (32 and
  31 respectively) that closed the residual gap.

## Nit

**n1** (error route echoes `str(exc)` unfiltered) — fixed for both guards.
The deny reason now names only the exception TYPE; the full message is
logged (`logger.exception`/`logger.warning`) but never echoed back. 5
new/updated tests, including one existing test whose assertion was flipped
from "message present" to "message absent".

**n2** (pre-existing false positive) — already fixed on this branch before
this phase (Phase 2); unaffected here.

**n3** (`enforce_llm_qa` data-consumer heads matched by basename, include
executing verbs) — fixed. The exemption now requires the head to be spelled
EXACTLY as the bare trusted word (`head == head_name`, no path prefix at
all — closes the path-qualified/shadowed-binary loophole), and is VOIDED
for `git bisect run`, `git rebase -x`/`--exec`, `git -c alias.NAME=!…`
(both the glued and shlex-punctuation-split spellings of the bang), and `rg --pre`. 6 new tests, including a negative case pinning that ordinary
`git`/`rg` usage stays exempt.

**n4** (no chain-level test caught m1) — fixed. Added
`HandlerChain.execute(hook_input, strict_mode=False)` tests for both
guards, confirming the fail-closed behaviour holds at the layer the
guard's own claim is actually about (2 tests per guard).

## Own findings (not in the review)

Two defects were introduced and caught by this branch's own TDD before
shipping — both are documented in code comments at their fix site and in
the commit message:

1. A degenerate DP-orientation case in M2(a): comparing a leading-wildcard
   token against a trailing-wildcard pattern (or vice versa) via the DP is
   satisfiable by simple concatenation for ANY literal on either side, so
   running it unconditionally would have denied ordinary tokens with no
   relation to any protected name. Fixed with
   `_dp_intersection_is_meaningful`, gating the DP call to same-orientation
   pairs or a fully literal side.
2. A catastrophic-backtracking regex in M2(d)'s first cut
   (`\S*\{[^{}]*\}\S*`), reintroducing a B1-class timing bypass on
   adversarial input with no braces at all. Fixed with a bounded manual
   boundary scan.

## Not in scope on this branch

- **M3 / N24** (`daemon.strict_mode` inert): per team-lead's explicit
  instruction, left untouched. On main as N24, a separate agent is fixing
  it.
- **m3's `destructive_git` half**: already on main as N25, a separate agent
  is fixing it there (see the m3 section above for the disposition).

## QA and process

- Targeted QA only, no new exclusions: `format lint type_check pyright magic_values error_hiding security docs_qa plan_qa` — 9/9 passed.
- Daemon restarted twice (once before the initial QA pass, once more after
  the error_hiding fixes that followed the first QA run) before committing.
- Journal entries filed via `mkplan.bash --journal` (two: the phase-3
  summary, and a correction noting the N32 → N25 disposition change).
- Commit: `3e3164bd` — "Plan 00466: fix guard-defects security review 2
  (B1, M1, M2, m1-m4, n1, n3, n4)".

## Files touched

- `.claude/project-handlers/pre_tool_use/enforce_llm_qa.py` +
  `test_enforce_llm_qa.py`
- `src/claude_code_hooks_daemon/utils/secret_file_matching.py` +
  `tests/unit/utils/test_secret_file_matching.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/secret_file_guard.py`
  - `tests/unit/handlers/pre_tool_use/test_secret_file_guard.py`
- `src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py`
  - `tests/unit/handlers/pre_tool_use/test_project_containment.py`
- `CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md`,
  `PLAN.md`, `JOURNAL/00466-Journal-26-09-24.md`
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-…md`,
  `15-…md` (corrected), `30-…md` through `36-…md` (new)
