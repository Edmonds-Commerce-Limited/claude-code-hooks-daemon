# N4, N5, N6: reproduction, cause, fix (Plan 00466)

Worktree: `worktree-n466-guard-defects`. HEAD after this report's commit:
see the coordinator's log, or `git log -1 --format=%H` in this worktree.

## N4 — secret_file_guard leading-wildcard overlap false positive

**Reproduction**: independently reproduced (peer agent's report treated as a
hypothesis, not fact) via `TestBashMentionsProtectedPath` in
`tests/unit/utils/test_secret_file_matching.py`. An Edit adding a Python
unpacking/splat expression over a bracketed slice (space before the colon
splits the slice into its own token) to a `.py` file was denied under
R-SECRET-SCRIPT-AUTHOR, naming the one shipped-default protected glob with a
leading wildcard and no trailing one. The same shape denied a bracket-free
`def f(*wordlist): pass` / `call(*wordlist)`.

**Cause** (`src/claude_code_hooks_daemon/utils/secret_file_matching.py`,
`_glob_token_overlaps_stem` and its call site in `_token_mention`): the
leading-wildcard branch checked whether the stem's suffix overlapped the
token residue's prefix by at least a minimum length, with no regard for
whether the PATTERN itself had a trailing wildcard. For a both-edges pattern
this is correct (the pattern's own trailing wildcard absorbs whatever the
token's residue doesn't cover). Applied to an anchored pattern (no trailing
wildcard), a short boundary coincidence between residue and stem was
wrongly counted as a truncation — the splat token's residue happened to
share its first 4 characters with the stem's tail.

**Fix** (implemented): `_glob_token_overlaps_stem` gained a
`pattern_has_trailing_wildcard` keyword-only parameter; the leading-wildcard
branch now also requires `pattern_has_trailing_wildcard or stem_basename.endswith(residue)`. The call site in `_token_mention` passes
`_has_trailing_wildcard(pattern)` — a function already used elsewhere in the
same module for the token's own edges, reused here for the pattern's. This
is parametrised on the pattern's own shape, not special-cased to one glob,
so any leading-wildcard-only pattern (shipped or project-configured) is
covered the same way.

**RED evidence**: `TestBashMentionsProtectedPath::test_leading_wildcard_python_splat_operator_is_not_matched`
confirmed failing pre-fix, passing after; a paired
`test_leading_wildcard_full_suffix_of_anchored_stem_still_matched` regression
guard proves a genuine truncation of an anchored pattern still denies.

**Sibling audit**: the shipped default patterns were checked for the same
false-positive class — the fix is gated on the PATTERN's own trailing-wildcard
shape (computed per-pattern via the already-existing `_has_trailing_wildcard`),
so any other leading-wildcard-only pattern is covered by construction, not by
enumeration.

**Commit**: `c496de11` — "Plan 00466 N4: fix secret_file_guard leading-wildcard overlap false positive".

## N5 — SECURITY fail-open: an empty path-mention token crashes `secret_file_guard.matches()`

**Reproduction**: the coordinator supplied the exact `tool_input` of the
three live triggering Edits (saved to
`untracked/scratch/n5_triggering_edits.jsonl` in this worktree, not
committed). Replayed through the real daemon's full `process_request`
pipeline (cwd `/workspace`) for a live traceback:
`chain.py handler.matches (block-secret-file-read)` ->
`secret_file_guard.py _matched_pattern_and_route` -> `_script_content_mention`
-> `secret_file_matching.py find_protected_mention_detail` ->
`iter_protected_mentions` -> `_token_mention`: `path_matches_globs(form, ...)`
with `form == ""` -> `path_exclusion.py _candidate_paths`:
`os.path.relpath(raw, root)` with `raw == ""` ->
`ValueError: no path specified`.

**Cause**: `_normalised_token_forms` strips a token EQUAL to one of the
home/pwd expansion prefixes (e.g. a quoted `"~/"` Python string literal,
observed live) down to an empty string (`token[len(prefix):]` on a token
exactly as long as the prefix). That empty spelling then reached
`path_matches_globs`, which had never been asked to answer for an empty
path — `os.path.relpath` rejects an empty PATH argument outright, regardless
of `start`.

**Severity**: the exception is raised inside `matches()`, not `handle()`.
The daemon's per-handler catch (`core/chain.py`) is non-strict by default for
this path: it logs the exception as context and treats the handler as "did
not match", moving on to the next handler. A Write/Edit whose content
contains one of these operand tokens therefore SKIPPED `secret_file_guard`
ENTIRELY for that call — including any genuine protected-path mention
elsewhere in the same content. This is a security fail-open, not noise;
confirmed live by replaying against the real daemon and observing the
`PreToolUse:Edit` context carry the raw exception text with no denial.

**Fix (both layers, per instruction)**:
(a) `_normalised_token_forms` (`secret_file_matching.py`) never emits an
empty form — the home/pwd-prefix-stripping branch now requires
`len(token) > len(prefix)`, the same guard shape the adjacent
`./`-stripping branch already used.
(b) `_candidate_paths` (`path_exclusion.py`) is now TOTAL on an empty
`file_path` — it returns a single empty-string candidate immediately rather
than calling `os.path.relpath` at all, so no OTHER caller of
`path_matches_globs`/`is_path_excluded` can hit the same crash by a
different route (defence in depth).

**Fail-safe pin**: a dedicated RED test asserts that content carrying BOTH a
crashing home-prefix token AND a genuine protected mention (`id_rsa`)
elsewhere in the same blob still denies — confirmed crashing before the fix,
passing after. A corpus test iterates every operand shape observed in the
live payloads (alone, inside a quoted string, inside a call) asserting the
mention scan never raises.

**RED evidence**: `tests/unit/utils/test_path_exclusion.py::TestEmptyAndNoMatch::test_empty_file_path_with_a_project_root_does_not_raise`
and `tests/unit/utils/test_secret_file_matching.py::TestBareHomePrefixTokenDoesNotCrash`
(6 tests) — all confirmed failing pre-fix, passing after.

**Post-fix verification**: replayed all three original triggering payloads
through a real `DaemonController.process_request` pipeline end to end — no
crash (denied for an unrelated, correct reason: the synthetic repro root
differs from the payload's literal absolute path).

**Live confirmation the bug is still active on main**: committing this very
fix, my commit message itself quoted `"~/"` (documenting the exact
crash-triggering token) — the MAIN checkout's still-unpatched daemon
(routing hooks for this session regardless of worktree cwd, see "routing"
note below) hit the exact N5 crash live on my own `git commit`, and
correctly failed OPEN (allowed the commit) rather than blocking, which is
the fail-open this fix closes.

**Commit**: `d3bdbd56` — "Plan 00466 N5: fix security fail-open on an empty path-mention token".

## N6 — `enforce_llm_qa` denies a prose mention of `run_all.sh` in an unrelated argument

**Reproduction**: live, hit while writing this very ledger's journal entry —
a `CLAUDE/Plan/mkplan.bash --journal ... --title "... run_all.sh ..."`
command was denied even though the runner's name appeared only inside the
quoted `--title` prose. Also reproduced the design's other named shapes in
unit tests before touching the source: a `gh issue comment --body "... run_all.sh ..."`
prose mention, and a compound command naming a DIFFERENT script's wrapper
plus separate unrelated prose in a later segment.

**Cause** (`.claude/project-handlers/pre_tool_use/enforce_llm_qa.py`,
`_is_inspection_only` pre-fix): for any top-level segment CONTAINING the
substring `run_all.sh` anywhere, the check looked only at that segment's OWN
leading word against an inspection/VCS allowlist. A word appearing inside a
quoted argument to an unrelated command (not the segment's leading word) was
invisible to that check, so `mkplan.bash`'s leading word (on no allowlist)
caused the whole segment — including the prose buried in `--title` — to be
treated as a potential invocation.

**Fix (implemented)**: replaced the substring-plus-allowlist check with a
`shlex`-based real-invocation detector (`_has_real_invocation` /
`_segment_executes_script` / `_word_names_the_script`), reusing this
project's already-established `shlex.split()` + `try/except ValueError`
tokenisation pattern (`project_containment.py`'s `_tokenise` static method)
rather than a third hand-rolled parser — `subagent_full_qa_blocker.py`'s
`find_full_qa_invocation` (mentioned as a possible reuse candidate) does not
exist on `main`; confirmed via `find src -iname "*full_qa*"`. A segment now
matches only when the script is named at the command's own HEAD, or as an
argument to a wrapper (`bash`/`sh`/`env`/`timeout`/`nice`/`exec`) —
recursing into a wrapper's `-c` subshell argument and into any
`$(...)`/backtick substitution's inner text (both run before the rest of the
line, per the existing UNQUOTED-heredoc regression test). A whole shlex
token that merely CONTAINS the script's name inside longer prose (an entire
quoted `--title "..."` phrase is ONE token) no longer counts as naming it. A
segment that can't be tokenised safely falls back to the prior conservative
substring check (still denies) — no bypass opened.

This let the old `_INSPECTION_COMMANDS`/`_VCS_COMMANDS` allowlists be
deleted outright (YAGNI): with no wrapper match and no script-name match at
the head, nothing can execute regardless of what the head verb is, so no
enumerated list of "known-safe" verbs is needed.

**A second instance of the same false-positive class**, found while manually
tracing every pre-existing test against the new design: the handler's own
`get_acceptance_tests()` "Block run_all.sh" fixture used
`echo "./scripts/qa/run_all.sh"` as a "safe to execute" DENY case — it only
denied under the old code because `echo` happened to be absent from the
allowlist, not because it invoked anything. Replaced with
`bash -n scripts/qa/run_all.sh` (a genuine wrapper-invocation shape; `-n`
keeps it parse-only and harmless if the block were ever to regress).

**RED evidence**: `test_does_not_match_a_prose_mention_in_a_quoted_title_flag`
(the exact live shape) and `test_does_not_match_an_unrelated_wrapper_invocation`
confirmed failing pre-fix, passing after. Four companion "must still deny"
regression guards were added alongside and were already passing pre-fix
(kept as pins): a `gh --body` prose mention, `cd ... && ./run_all.sh`,
`sh -c './scripts/qa/run_all.sh'`, and a bare `$(./scripts/qa/run_all.sh)`
substitution.

**Targeted QA for this defect**: all 41 tests in
`.claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py` pass. All 198
tests under `bin/hooks-daemon test-project-handlers --verbose` pass (the
project-handler QA tool named in the assignment).

**Commit**: `455a2672` — "Plan 00466 N6: fix enforce_llm_qa denying a prose mention of run_all.sh".

## A cross-cutting note: hook routing during this session

Throughout this task, Bash commands issued from inside this worktree were
intercepted not by this worktree's own daemon (restarted repeatedly with
each fix applied) but by the MAIN checkout's daemon at `/workspace` — the
relay hot path in `.claude/hooks/pre-tool-use` activates on the literal
`BASH_SOURCE[0]` of the session's REGISTERED hook script
(`/workspace/.claude/hooks/pre-tool-use`), not on the Bash tool's `cwd`.
This meant my own fixes (uncommitted to `main`) never actually protected my
own subsequent commands in this session — visible directly as: (a) my first
attempt at N6's journal entry was denied by the pre-fix code even after
restarting my OWN worktree's daemon; (b) my N5 commit message, quoting the
exact crash-triggering token, hit the live N5 crash on the main checkout's
daemon and correctly failed open. Neither blocked real progress (worked
around by rephrasing the one command that hit N6's still-open bug on main,
and N5's fail-open is by design non-blocking), but it's worth the
coordinator knowing this is a standing artifact of multi-worktree sessions,
not specific to this task.

## Ledger and journal

`CLAUDE/Plan/00466-niggles-ledger-sixteen/NIGGLES.md` — full write-ups for
N4, N5, N6 (newest first, above N3). `PLAN.md` — table rows for N4, N5, N6,
all `✅ Remedied`. `JOURNAL/00466-Journal-26-09-24.md` — three `finding`
entries, one per defect, appended via `mkplan.bash --journal`. Committed
together as `ae5c7f38` — "Plan 00466: ledger N4, N5, N6 as remedied".

## Release notes

- `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-secret-file-guard-no-longer-flags-a-python-unpacking-splat-as-a-vault-password-reference.md` (N4, audience: client projects)
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/14-secret-file-guard-no-longer-fails-open-on-an-empty-path-mention-token.md` (N5, audience: everyone, security fix)
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/15-enforce-llm-qa-no-longer-blocks-a-prose-mention-of-the-denied-runner.md` (N6, audience: handler authors — `enforce_llm_qa` is a project-local handler, not shipped to client projects by the installer)

## Targeted QA (full diff, all three defects)

`./scripts/qa/llm_qa.py format lint type_check pyright magic_values error_hiding security docs_qa plan_qa`:
9/9 PASSED (one `format` run auto-fixed two files via Black on its first
pass — `run_format_check.sh` auto-formats rather than merely checking — a
re-run confirmed 0 files needing reformatting; re-ran the touched-test suite
afterward to confirm the reformat changed no behaviour).

Touched-test suite (`tests/unit/utils/test_secret_file_matching.py tests/unit/utils/test_path_exclusion.py tests/unit/handlers/pre_tool_use/test_secret_file_guard.py .claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py`): 368 passed.

Project-handler QA (`bin/hooks-daemon test-project-handlers --verbose`):
198 passed.

## Daemon restart

This worktree's daemon was restarted three times over the course of the
task (after N6's fix, before committing, and once more after the final
Black auto-format) — most recently immediately before the final QA/test
re-run above, so the restart-then-verify order holds for the committed
state.

## HEAD SHA

`ae5c7f38` (this report's own commit, once made, will move HEAD one further —
see the coordinator's log or `git log -1 --format=%H` for the exact final
value).
