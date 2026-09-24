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

## QA

- `scripts/qa/run_format_check.sh` — clean (4 files auto-fixed by black,
  re-verified clean).
- `python scripts/qa/audit_error_hiding.py` (whole-project, not
  file-scoped — the CLI args are advisory only) — 0 violations, no new
  exclusion entries added (`git diff` on `error_hiding_exclusions.json` is
  empty).
- `python scripts/qa/llm_qa.py lint / type_check / security / magic_values / error_hiding / fail_open_inventory / declared_invariant_pairs` — all
  PASSED, 0 issues each.
- `pytest tests/unit/utils/ tests/unit/handlers/pre_tool_use/` — 6003
  passed, 2 pre-existing xfails (Plan 00408, unrelated to this fix, both
  present before this branch started).
- Review 3's own probe scripts re-run live against the fixed code:
  `probe_guards_v3_timing.pyprobe` (every shape now denies well under 1s,
  down from 8s–killed-past-90s), `probe_guards_v3_llmqa_timing.pyprobe`
  (every shape 0.001s–0.82s, down from 15s–killed-past-45s),
  `probe_gd_llmqa.py` (`regressions_vs_main=0`, matching review 3's own
  confirmed result).
- Daemon restarted before this commit.

No new QA exclusions or config changes. Release note added:
`CLAUDE/UPGRADES/UNRELEASED/release-notes/37-a-slow-secret-file-guard-or-enforce-llm-qa-scan-is-no-longer-a-fail-open.md`.
