# Plan 00466 — fix report for guard-defects review 3

**Author**: Sonnet 5, on `worktree-n466-guard-defects`.
**Scope**: fix every finding in `260924-n466-guards-review3-opus-5-5.md`
(1 blocker, 3 majors, 3 minors, 2 nits) structurally, per team-lead's
explicit instruction: "the per-shape timing fixes keep reintroducing B1, so
fix it structurally."

## The structural fix

Review 2's own B1 fix, and both of its own new M2 sub-fixes, each
independently reintroduced B1's defect class: a slow SAFETY-guard scan is a
fail-open, because a client socket timeout on the 30s PreToolUse budget is
an ALLOW for the whole chain. Three per-shape caps (a bounded regex, a DP
cell cap, a results-count cap) each missed some OTHER unbounded path the
same general shape could still take.

New module `src/claude_code_hooks_daemon/utils/shell_expansion.py`:

- `TooManyToEnumerateError` — the one shared failure mode. Every bounded
  primitive below raises this past its cap instead of silently falling back
  to a smaller-but-still-eager computation. Every caller (`secret_file_guard`
  and `enforce_llm_qa`) treats it as fail CLOSED — "cannot rule out a
  match" — the same way they already treat `TimeoutError`.
- `expand_braces(word, *, max_spellings=256, max_depth=64)` — a LAZY
  recursive generator (`_raw_brace_expansions`) consumed via
  `itertools.islice(..., max_spellings + 1)`, so at most `max_spellings + 1`
  leaves of the expansion tree are ever visited regardless of how many the
  word's full expansion would produce. A recursion-DEPTH cap runs
  independently of the spelling cap (own live finding, own RED test): a
  DEEPLY nested `{a,{a,{a,...}}}` costs one recursive frame per level
  regardless of how few alternatives are at each level, and a width cap
  alone never catches it.
- `iter_brace_words(text, *, max_words=500)` — the bounded, non-backtracking
  brace-word finder (anchored on the SAME bounded `{...}` regex both modules
  already used, plus a manual boundary scan), replacing BOTH modules' own
  `\S*\{[^{}]*\}\S*` catastrophic-backtracking word-finder regex. Skips a
  match already covered by the previous yielded span (a word carrying
  several groups was previously re-yielded, and re-expanded, once per
  group).
- `bounded_recursive_glob(base, pattern, *, max_entries_visited=2000, deadline=None)` — a manual `os.scandir`-based walk (not `Path.glob`,
  which only ever counts YIELDED matches) for a `**`-carrying pattern.
  Counts every entry VISITED against the cap, regardless of whether it
  matches, so a wide tree with nothing matching the final component still
  trips the cap instead of running to completion. Refuses outright (no walk
  attempted) a pattern rooted at the bare filesystem anchor that carries
  `**` OR two or more wildcarded path segments (own live finding beyond
  the review's own two `**`-marked reproducers: `/*/*/*/*/*/*/*.se?ret-zq9x`
  carries no literal `**` at all, yet forces `Path.glob` to expand a full
  directory listing at every one of seven root-relative levels — measured
  at 1.1s on this small container). Prunes a small fixed set of
  huge/ignored directory names (`.git`, `node_modules`, `__pycache__`,
  build/cache dirs). `deadline` is checked once per entry visited, inside
  the walk itself.

`secret_file_matching.py`'s `iter_protected_mentions` now chains the
ordinary tokens with a LAZY brace-token generator
(`itertools.chain`/`_brace_expansion_tokens`), replacing the eager
`tokens = [*a, *b]` list build B1-R3 found: pulling the next brace-expanded
token (where an over-cap word raises) now happens only after the PREVIOUS
token has already cleared the per-token deadline check, so construction is
bounded by the same gate that bounds consumption — not just the per-token
loop, the token-list build itself. `_expand_glob_token` routes any pattern
containing `**`, or rooted at the bare filesystem anchor, through
`bounded_recursive_glob`, threading `deadline` all the way from
`iter_protected_mentions` through `_token_mention` → `_both_edges_glob_mention`.

`enforce_llm_qa.py` now imports the shared module: `_word_could_name_the_script`
catches `TooManyToEnumerateError` from `expand_braces` and returns `True`
(fail closed — this guard's whole M1 redesign is already deny-by-default,
over-blocking being the accepted safe direction per review 2's own m-3).
`_brace_words_in_segment` now delegates to `shell_expansion.iter_brace_words`,
deleting the SECOND independent copy of the catastrophic regex. A recursion-
depth cap (`_MAX_INVOCATION_RECURSION_DEPTH = 20`) was added to the mutually
recursive `_segment_executes_script`/`_has_real_invocation` pair (each
`eval`/substitution level re-joins and re-parses the whole remaining
command); past the cap the segment is treated as a candidate invocation
(fail closed). Measured cause of the `eval` x100 case's own 71s: NOT the
recursion itself, but the catastrophic regex being re-run against the same
~20 KB padded text at every one of the 100 levels — fixed by the regex
replacement above; the depth cap is an additional, independent bound.

## Findings, disposition

| Finding             | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **B1-R3** (blocker) | `_brace_expansion_tokens` is lazy, chained not concatenated; `expand_braces` is capped+lazy. `{a,b}`x22 now denies in ~0.3s (was killed past 90s alongside a real `.vault-password` mention).                                                                                                                                                                                                                                                                                                                                                                         |
| **M-1** (major)     | `bounded_recursive_glob` bounds entries VISITED; refuses a broad root-rooted pattern outright, `**`-spelled or not. `/**/` denies in 0.002s (was 9.5s); the un-`**`-spelled `/*/*/.../` shape (own live finding) denies in 0.002s (was 1.1s).                                                                                                                                                                                                                                                                                                                         |
| **M-2** (major)     | `_dispatch_key` wrapped inside `_compute_and_cache_matched`/`_take_cached_matched` (secret_file_guard.py) and `_compute_and_cache`/`_take_cached` (project_containment.py) — both files, for consistency, though project_containment's own key was already tolerant. RED tests added for `tool_input` `None`/`[]`/a bare string on both handlers.                                                                                                                                                                                                                     |
| **M-3** (major)     | Catastrophic regex deleted, replaced with the shared `iter_brace_words`. `_expand_braces` replaced with the capped `expand_braces` (fail closed past cap). Eval-recursion depth capped. `echo <94/200 KB>` now 0.05–0.75s eval (was 14.5s/killed); `eval`x100/250/400 now ~0.58–0.60s (was >71s / untested further).                                                                                                                                                                                                                                                  |
| **m-1** (minor)     | New `TestBraceAndFsWalkAreBounded` in `test_secret_file_matching.py` pins the reviewer's exact shapes (brace x20/22/40 with and without a real mention, `/**/` single and x10, the 94/200 KB regex-shaped input) — each under budget. New timing tests in `test_shell_expansion.py` and `test_enforce_llm_qa.py` for the shared primitive and the enforce_llm_qa surface respectively.                                                                                                                                                                                |
| **m-2** (minor)     | Documented here rather than as a code change per the review's own framing ("worth one honest sentence in the ledger"): the both-edges FS-truth route (`*.secret*`/`*vault_pass*`) only denies an interior/edge spelling when the protected file actually EXISTS and is reachable — on a checkout where `.claude/block-words.secret` is absent, every interior/edge spelling of it ALLOWs. Safe by construction (nothing to read), but the "interior globs of every shipped pattern are denied" claim holds conditionally for these two patterns, not unconditionally. |
| **m-3** (minor)     | No code change — already the deliberate, accepted safe-direction cost of the M1 (review 2) deny-by-default redesign; re-confirmed unchanged by the review-2 100-case verdict-diff probe (`regressions_vs_main=0`, same 20 `branch_wrong` over-blocks as review 3 itself measured: `ls`/`cp`/`awk`/`vim`/`chmod`/bare `echo run_all.sh`).                                                                                                                                                                                                                              |
| **n-1** (nit)       | No code change — `_strip_timeout_prefix`'s flag-value skip gap is pre-existing, acknowledged in its own docstring, and fails toward the safe (usability) direction for THIS guard; the reviewer itself rated it low value.                                                                                                                                                                                                                                                                                                                                            |
| **n-2** (nit)       | Added `test_dispatch_key_falls_back_to_repr_for_an_unsortable_key` to `test_project_containment.py`, pinning the `repr()` fallback path with a dict carrying mixed int/str keys (`json.dumps(..., sort_keys=True)` raises `TypeError` comparing them).                                                                                                                                                                                                                                                                                                                |

## Own findings this session (not in the review report)

- `iter_brace_words`'s original draft re-yielded (and re-expanded) a word
  carrying several brace groups once per group found inside it, tripling
  the effective work for the reviewer's own `x{a,b}{c,d}{e,f}y` shape (0.78s
  eval at 200 KB — over budget). Fixed by skipping a match already covered
  by the previous yielded span; now 0.55s.
- `_expand_glob_token`'s routing initially checked only for a literal `**`
  substring before delegating to the bounded walker, leaving the
  un-`**`-spelled `/*/*/*/*/*/*/*.se?ret-zq9x` shape (present in the
  reviewer's own probe script, though not written up as a separate finding)
  on the old unbounded `Path.glob` path — measured independently at 1.1s.
  Broadened `bounded_recursive_glob`'s root-refusal check (and
  `_expand_glob_token`'s routing) to cover ANY pattern rooted at the bare
  filesystem anchor with two or more wildcarded path segments, not just a
  literal `**`.
- `bounded_recursive_glob`'s non-recursive fallback initially caught
  `OSError`/`ValueError` from `base.glob(pattern)` locally, which the
  project's `audit_error_hiding.py` correctly flagged (`log-and-continue`).
  Rather than add a new exclusion entry (which review 3 explicitly checked
  for and this fix must not introduce), removed the local catch: every
  caller of this branch reaches it through `_expand_glob_token`'s own
  `try/except (OSError, ValueError): continue` around consuming the same
  iterator — an EXISTING, already-registered exclusion (Plan 00272/00357)
  — so the exception now propagates to that pre-existing handler instead of
  being caught twice.

## Cross-cutting note for the ledger

Plan 00463's `subagent_full_qa_blocker` has "the same brace blow-up" per the
coordinator queue (fixed independently on its own branch). The eventual
shell-parsing consolidation (the queue names it alongside 464's
`shell_lexer`, `n422-guards`' command_evasion primitives, `pipe_blocker`'s
`_command_inside`, and enforce_llm_qa's own shlex handling) should move that
handler onto this branch's `utils/shell_expansion` primitive too, rather
than leaving a third independent brace expander in the codebase.

## Addendum: n466-n24's 1 MB timing follow-up

n466-n24 separately measured `secret_file_guard` at 12.3s for a 1 MB payload
and 49s for 4 MB (linear, ~12 µs/byte) — a 4 MB input exceeds the 30s client
timeout, a fail-open. Team-lead asked for the constant factor cut while this
same file was already being rewritten, target under 1s for 1 MB, pinned by a
timing test. Separately, the coordinator queue asked for
`_expand_glob_token`'s silent `except (OSError, ValueError): continue` to be
made genuinely fail-closed and its `error_hiding_exclusions.json` entry
removed.

Profiled a 1 MB Bash command and a 1 MB Write-to-`.py` payload with cProfile
(scratch: `untracked/scratch/profile_sfg_1mb.py`,
`profile_sfg_1mb_unique.py`, `profile_sfg_1mb_realistic.py`). Four changes to
`secret_file_matching.py`, no change to the public API or the security
surface:

- **Per-scan memoization** (`iter_protected_mentions`) — every input to
  `_token_mention` other than the token TEXT is fixed for the whole call
  (`patterns`, `stem_pairs`, `project_root`, `cwd`,
  `both_edges_patterns`/`_stems`), so the verdict for a given token can never
  differ between two occurrences of it in the same command. A local
  `dict[str, str | None]` cache keyed by token text turns a scan that redid
  the full DP/bracket/filesystem work per occurrence into one that pays for
  each DISTINCT token once — realistic content (source, logs, minified code)
  is dominated by a small reused vocabulary, so this is the single largest
  win for realistic payloads.
- **Realpath-skip for glob-shaped tokens** (`_token_mention`) — the trailing
  `_realpath_if_resolvable(token)` call (a real `os.stat`) exists only for
  the `worktree_create` symlink-alias case, which needs the token to
  plausibly BE a literal filename. Gated it on `not _is_glob_shaped(token)`:
  a real on-disk symlink literally named with an unescaped `*`/`?`/bracket
  expression is not a shape any genuine alias uses, and this syscall was the
  single biggest per-token cost at volume for glob-shaped content.
- **Cheap regex-skip guards + rolling-array DP** (`_globs_can_intersect`) —
  the three `.sub()` calls per operand (POSIX class, bracket expression,
  star-run) ran unconditionally even when the operand had none of the
  trigger characters; guarded each behind a cheap `in` substring check
  first. Replaced the full `len_a+1 × len_b+1` grid with a two-row rolling
  array (`prev`/`curr`) — the recurrence only ever reads the immediately
  previous row plus the current row's own previous cell — avoiding
  `O(len_a)` list allocations per call at high call volume.
- **`_expand_glob_token` fail-closed** — removed the
  `try/except (OSError, ValueError): continue` around the match-consumption
  loop. It used to catch a failure on one expansion base and silently try
  the next, degrading to "no mention" if every base failed — exactly the
  silent-degrade class the rest of this review round has been closing
  everywhere else. The exception now propagates to the caller's own
  fail-closed wrapper. Removed the now-obsolete
  `error_hiding_exclusions.json` entry for it (a pre-existing Plan
  00272/00357 entry, not one added by this branch).

**Measured** (raw wall-clock, not cProfile — cProfile's own per-call
instrumentation overhead measurably inflates `tottime` at these call
volumes, confirmed by cross-checking a profiled run against a raw
`time.perf_counter()` run of the same workload):

- Realistic 1 MB content (400-word local vocabulary, moderate repetition,
  the way real source/log content behaves): ~0.08–0.09 µs/byte for both the
  Bash-command route and the Write-to-`.py` script-content route (down from
  the ~12 µs/byte baseline — roughly 130–150x). A genuine mention appended
  after 1 MB of ordinary content is still found, at the same speed —
  detection is not weakened.
- The pre-existing fully-repeated `"a*b " * 250_000` test shape (previously
  deadline-truncated at 5s+) now completes unconditionally under 1s with no
  deadline needed at all.
- The fully-adversarial worst case (≈90K MOSTLY-UNIQUE tokens, no
  repetition to memoize) is essentially unchanged at ~11.4 µs/byte — a raw
  microbenchmark of `_globs_can_intersect` alone
  (`untracked/scratch/microbench_dp.py`) puts ~14 µs/call at roughly the
  Python-interpreter floor for this DP at current problem sizes. This
  residual case is explicitly left to n24's own separate whole-chain
  deadline + input-size-cap backstop, not claimed fixed here.

**Considered and rejected**: a literal-substring overlap pre-filter before
invoking the DP in `_glob_intersection_mention`, to skip the DP entirely for
token/pattern pairs sharing no literal text. Found a genuine correctness
counterexample for glob-language intersection with interleaved segments —
`A="ab*"` and `B="*ba*"` can intersect via a longer string like `"abba"`
that satisfies both, even though neither's literal segment is a substring of
the other — so this class of shortcut is unsound in general. Not
implemented; the adversarial residual case relies on n24's backstop instead.

Pinned with a new `TestOrdinaryVolumeContentCompletesFast` class (4 tests)
in `test_secret_file_matching.py`: the 1 MB Bash-command and Write-content
routes each under 1s with no deadline, the repeated-`"a*b "` shape under 1s
unconditionally, and a genuine mention still found in 1 MB of realistic
volume content, under 1s.

**Disclosed trade-off**: `_expand_glob_token` is also called (via
`find_protected_mention_strict`) by `quarantine_artefact_read_guard.py`,
which has no local fail-closed wrapper of its own around `matches()`/
`handle()`. Making `_expand_glob_token` propagate on a non-ENOENT error
(see the review-4 refinement below) instead of swallowing changes that
handler's behaviour on such a failure from "silently returns None" to "may
raise, caught by the chain's default non-strict dispatch — still
effectively ALLOW, but now a surfaced/logged exception rather than a silent
pass". Left as-is rather than expanding scope to add a wrapper there:
team-lead's instruction was specific to `_expand_glob_token`; that handler
ships disabled by default; and giving it its own fail-closed posture is
already n24's separate "24 SAFETY+BLOCKING handlers fail closed" workstream.
Verified no regression: `test_quarantine_artefact_read_guard.py`,
`test_project_containment.py` and `test_enforce_llm_qa.py` all still pass
(223 tests) with the change in place.

## Addendum 2: review 4 — narrow the fail-close to ENOENT only

Review 4 flagged that my initial fix (propagate ANY `OSError`/`ValueError`
from `_expand_glob_token`'s consumption loop) was too blunt in the other
direction: a genuinely proven negative — a literal directory prefix that
simply does not exist (`ENOENT`) — does not need to deny, it can safely
prove "no match" and let the scan continue to the next base. Only an error
that means the expansion could not be COMPLETED (permission denied, an I/O
error, …) must deny, because THAT case cannot rule out a match hiding behind
whatever raised.

`_expand_glob_token`'s consumption loop now catches `OSError` narrowly:
`exc.errno == errno.ENOENT` logs at DEBUG and continues to the next base
(filesystem truth, not a masked failure); any other `errno` re-raises
unchanged, propagating to the caller's fail-closed wrapper as before.
`ValueError` (a malformed pattern) is never a proof of absence either way,
so it still always propagates uncaught.

The same conflation existed one level down, inside
`shell_expansion.bounded_recursive_glob`'s own `os.scandir` catch (used for
`**`-carrying patterns): it treated "the directory disappeared" and "the
directory could not be read" identically ("contributes nothing, skip it"),
which silently fails open on a permission-denied directory ENCOUNTERED MID-
WALK — a case `_expand_glob_token`'s own try/except cannot see, because this
generator never propagated it out. Applied the identical ENOENT-narrow
split there too: `ENOENT` continues (logged DEBUG), anything else re-raises
out of the generator to whichever caller is consuming it (currently always
`_expand_glob_token`, itself uncaught there, reaching the SAFETY guard's own
fail-closed wrapper).

New tests (TDD, RED before the fix): `TestExpandGlobTokenErrorHandling` in
`test_secret_file_matching.py` (a missing directory prefix returns `None`,
both naturally and via a forced `ENOENT`; a forced `PermissionError`
propagates; a forced `ValueError` propagates) and two additions to
`TestBoundedRecursiveGlob` in `test_shell_expansion.py` (a subdirectory that
vanishes mid-walk is skipped and a real match elsewhere is still found; a
permission-denied subdirectory propagates). All via `monkeypatch` on
`Path.glob`/`os.scandir` — real filesystem permission enforcement is
unreliable to test against as root, which this container runs as.

## QA

- `scripts/qa/run_format_check.sh` — clean (0 files needing formatting).
- `python scripts/qa/audit_error_hiding.py` (whole-project) — 0 violations;
  the `_expand_glob_token` exclusion entry removed, no new entries added.
- `python scripts/qa/llm_qa.py lint / type_check / security / magic_values / error_hiding / fail_open_inventory / declared_invariant_pairs` — all
  PASSED, 0 issues each.
- `pytest tests/unit/utils/test_secret_file_matching.py tests/unit/utils/test_shell_expansion.py tests/unit/handlers/pre_tool_use/test_secret_file_guard.py tests/unit/handlers/pre_tool_use/test_quarantine_artefact_read_guard.py tests/unit/handlers/pre_tool_use/test_project_containment.py .claude/project-handlers/pre_tool_use/test_enforce_llm_qa.py` —
  590 passed.
- Review 3's `probe_guards_v3_timing.pyprobe` re-run live against this
  round's code: every shape still denies well under 1s (max eval 0.608s),
  confirming no regression from the timing-cut changes.
- Daemon restarted before this commit.

No new QA exclusions or config changes (one pre-existing exclusion entry
removed). Release note added:
`CLAUDE/UPGRADES/UNRELEASED/release-notes/37-a-slow-secret-file-guard-or-enforce-llm-qa-scan-is-no-longer-a-fail-open.md`.

## Addendum 3: review 4 — quarantine_artefact_read_guard fail-closed wrapper

Review 4's remaining item: this repo has `quarantine_artefact_read_guard`
ENABLED (`R-QUARANTINE-ARTEFACT-READ` is live), and it is itself a SAFETY+
BLOCKING guard. The "disclosed trade-off" in Addendum 1/2 -- a non-ENOENT
error reaching it via `find_protected_mention_strict` now raises instead of
returning `None` -- is only harmless if the exception is caught somewhere
and denied. Before this addendum it was NOT: `core/chain.py`'s per-handler
catch treats a propagated exception as "did not match" under the daemon's
default non-strict `strict_mode`, so a raise here was an ALLOW, exactly the
fail-open class the rest of this review round has been closing. Fixed
directly rather than depending on N24's separate handler-wide fail-closed
sweep, which lives on another branch.

`quarantine_artefact_read_guard.py` now carries the identical wrapper
posture as `secret_file_guard`'s own N11 fix (Plan 00466 N11):
`_matched_pattern` (the single dispatch point `matches()`/`handle()` share)
wraps the real evaluation (renamed `_evaluate_matched_pattern`) in a
try/except that NEVER re-raises -- an exception is logged and returns
`(_INTERNAL_ERROR_PATTERN, type(exc).__name__)`, denied by `handle()` via a
new `_ERROR_RULE` (`R-QUARANTINE-ARTEFACT-READ-EVALUATION-ERROR`) whose
message names the exception TYPE (never its full text, which could itself
carry flaggable content discovered by a directory walk) -- the same
restraint `secret_file_guard` N11 takes. `get_rules()` now returns both
Rules.

New tests (TDD, RED before the fix), `TestFailClosedOnEvaluationError` in
`test_quarantine_artefact_read_guard.py`: `matches()` is `True` when
evaluation raises; `handle()` denies with the exception type name and the
new rule ID in the reason, for a simulated failing-glob-base error
(`PermissionError`, the exact shape a non-ENOENT `_expand_glob_token`
failure now takes); a raise is never indistinguishable from a genuine
"no match" ALLOW. `get_rules()`'s existing single-rule test updated to
expect 2. Verified via `pytest tests/unit/handlers/pre_tool_use/test_quarantine_artefact_read_guard.py tests/unit/constants/test_rule_ids.py`
(81 passed) and the full related suite (619 passed, listed above plus
`test_rule_ids.py`).

## QA (review 4, quarantine wrapper)

- `scripts/qa/run_format_check.sh` — clean (2 files auto-fixed by black,
  re-verified clean).
- `python scripts/qa/audit_error_hiding.py` (whole-project) — 0 violations.
- `python scripts/qa/llm_qa.py lint / type_check / security / magic_values / error_hiding / fail_open_inventory / declared_invariant_pairs` — all
  PASSED, 0 issues each.
- `pytest tests/unit/handlers/pre_tool_use/test_quarantine_artefact_read_guard.py tests/unit/constants/test_rule_ids.py` —
  81 passed.
- `pytest` across every related suite touched this round (secret_file_matching,
  shell_expansion, secret_file_guard, quarantine_artefact_read_guard,
  project_containment, enforce_llm_qa, rule_ids) — 619 passed.
- Daemon restarted before this commit.
