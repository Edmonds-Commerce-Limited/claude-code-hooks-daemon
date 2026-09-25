# Plan 00466 — fix report for guard-defects review 4

**Author**: Sonnet 5, on `worktree-n466-guard-defects`.
**Scope**: fix every finding in `260924-n466-guards-review4-opus-5-5.md`
(1 major, 2 minors, 1 nit), per team-lead's instruction: "Fix the class, not
just those two spellings." Base: `61f61e8e` (the review-4 report itself,
committed first per team-lead's instruction).

## M-1 — the structural fix: real shell word normalisation

The review's own M-1 was narrow on its face (`expand_braces` has no brace
SEQUENCE support), but team-lead's remedy scoped it to the whole CLASS: real
bash strips quotes, decodes backslash/ANSI-C escapes, and concatenates
adjacent quoted/unquoted segments into ONE word before anything else
(including glob expansion) sees it — a mention-scanner that tokenises on raw
delimiters (including quote characters and `$`) shatters a legitimately
assembled word into fragments too short or wrong to match.

New in `src/claude_code_hooks_daemon/utils/shell_expansion.py`:

- **Brace SEQUENCE expansion** (`{start..end[..step]}`) — a lazy generator
  (`_sequence_alternatives`/`_numeric_sequence`/`_alpha_sequence`), numeric
  (zero-padded when either endpoint carries a leading zero) or single-letter
  alpha, either direction, optionally stepped, composed into
  `_raw_brace_expansions` alongside the pre-existing comma-alternation split.
  Bounded by the SAME `max_spellings`/`itertools.islice` cap the comma form
  already used — `{1..100000}` raises `TooManyToEnumerateError` without ever
  materialising the range, closing the review's own explicit ask ("I
  verified `{1..3}` is currently treated as one literal alternative, so the
  cap is not even reached today").
- **`normalise_word`/`iter_normalised_shell_words`** — a from-scratch,
  bounded, non-backtracking word scanner (`_decode_span`), built new rather
  than imported across branches per team-lead's explicit instruction. Single
  quotes strip to literal text; double quotes strip with `\\`, `\"`, `\$`,
  `` \` ``, and escaped-newline handling; a bare backslash decodes one
  escape; `$'...'` decodes ANSI-C (`\xHH`, octal, `\uHHHH`/`\UHHHHHHHH`, the
  simple-escape table); adjacent quoted/unquoted spans concatenate into one
  word exactly as a shell reads them. Any span the scanner cannot resolve
  without actually running a shell — `$VAR`, `${...}`, `$(...)`, a backtick,
  `$((...))` — collapses to a single `*`, turning the WHOLE containing word
  into a glob. This needed no new matching logic: `_glob_intersection_mention`
  (built by the N10 remedy, review round 2) already handles a glob-shaped
  token against a both-edges or non-both-edges pattern; the fix only needed
  to produce a correctly-normalised glob STRING and feed it through the
  pre-existing pipeline.

`secret_file_matching.py`: `_brace_expansion_tokens` now runs
`shell_expansion.normalise_word` over each expanded spelling (team-lead's
own example needed it: a brace ALTERNATIVE can itself carry a quote —
`id_rs{'a',x}` — so the quote strips only once a concrete alternative is
chosen, not from the group template beforehand — composition order:
brace-expand first, normalise each resulting spelling second). A new third
stream, `_normalised_word_tokens`, is chained onto `iter_protected_mentions`'s
existing `itertools.chain(_tokenise(...), _brace_expansion_tokens(...))` —
additive, matching this module's established philosophy: every new
detection surface runs ALONGSIDE the existing ones, never replaces them.

## Two regressions found and fixed during this same session (not in the review report)

Adding the third stream, on raw `command` text, broke two pre-existing
invariants the first two streams already respected — both are OWN findings,
caught by re-running the full related suite before committing, not by the
reviewer:

- **The import-module-path exemption was bypassed.** `_without_import_module_paths(command)`
  is applied before `_tokenise`, so an `import <name>` line naming a
  protected stem in its own dotted module path is not a mention — but the
  brace and normalised-word streams read raw `command`, re-discovering the
  same span the exemption had just deleted. Fixed by applying the exemption
  ONCE, up front, and feeding the same stripped text to all three streams.
- **Ordinary mentions were reported twice.** A plain word with nothing to
  decode normalises back to the exact string `_tokenise` already produced
  for it, so the new stream re-yielded it as a second mention — regressing
  `test_one_mention_per_token` and `test_yields_every_mentioned_token_in_order`.
  Fixed by extending the existing per-scan `mention_cache` (keyed on token
  text, already present for the 1 MB timing follow-up) to also gate
  YIELDING, not just recomputation: a token text is yielded at most once per
  scan. Safe for the one consumer that iterates every yielded mention
  (`_mention_is_encrypted`, the encrypted-target exemption) because it is a
  pure function of token text — collapsing repeats, whether from stream
  overlap or the command genuinely repeating a word, changes no verdict it
  computes.

## Findings, disposition

| Finding         | Fix                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **M-1** (major) | Brace sequence expansion + full quote/escape/ANSI-C/substitution-to-glob normalisation, chained as a third additive stream. RED tests through `find_protected_mention_detail` (`TestBraceSequenceExpansion`, `TestShellWordNormalisation` in `test_secret_file_matching.py`) AND through the real `SecretFileGuardHandler` (`TestShellWordNormalisationThroughTheHandler` in `test_secret_file_guard.py`), covering every spelling team-lead listed — brace sequence, double/single-quote adjacency concatenation, a brace alternative carrying a quote, backslash escape, ANSI-C hex escape, `$VAR`/`$(...)`/`"$HOME"` substitution-to-glob, an ordinary `$VAR` path staying allowed — against both shipped defaults (`id_rsa`) and a project-configured exact `.env` pattern. |
| **m-1** (minor) | Two new RED pins in `TestBoundedRecursiveGlob` (`test_shell_expansion.py`): a multi-wildcard-no-`**` pattern rooted at `/` still raises `TooManyToEnumerateError` with no `**` anywhere in it (the review's own cited live finding, previously untested); a `**`-carrying root pattern with `max_entries_visited` raised to 10,000,000 still refuses immediately (< 1s), proving the refusal fires from the root check itself and is not merely masked by a small entries cap.                                                                                                                                                                                                                                                                                                  |
| **m-2** (minor) | No code change — re-confirmed, honest ledger sentence carried forward unchanged from review 3's own m-2 (the both-edges FS-truth route is cwd/existence-dependent by construction).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **n-1** (nit)   | Fixed. `_strip_timeout_prefix` (`enforce_llm_qa.py`) now skips the separate value token of `-s`/`--signal` and `-k`/`--kill-after` (the two GNU `timeout` flags that take one); every other flag (`-v`/`--verbose`, `--preserve-status`, `--foreground`) still takes none. The `--flag=VALUE` spelling needed no change (value travels in the same token). RED tests added (`test_still_matches_timeout_with_a_signal_flag_value`, `test_still_matches_timeout_with_an_equals_form_flag_value`); manually reverted the fix and confirmed the new signal/kill-after test fails (1 failed, 1 passed — the equals-form case needed no fix and stayed green), restored, all 64 pass.                                                                                                |

## Verification

- Targeted module tests: 660 passed (`test_secret_file_matching.py`,
  `test_shell_expansion.py`, `test_secret_file_guard.py`,
  `test_quarantine_artefact_read_guard.py`, `test_project_containment.py`,
  `test_enforce_llm_qa.py`, `test_rule_ids.py`).
- Full unit suite: 22,606 passed, 9 failed, 3 skipped, 3 xfailed. The 9
  failures (`test_model_fallback_detector.py`, `test_absolute_path.py`,
  `test_lookup.py`, `test_dangerous_invocation_corpus_checker.py`) are
  pre-existing test-isolation/order-dependence artifacts, not regressions
  from this fix: re-running exactly those 4 files in isolation gives 105
  passed, 0 failed.
- Targeted QA: `run_format_check.sh` (black auto-fixed the new test file's
  line lengths, re-ran clean), `audit_error_hiding.py` (0 violations),
  `llm_qa.py lint type_check security magic_values error_hiding fail_open_inventory declared_invariant_pairs` — 7/7 PASSED.
- RED-pin verified for the n-1 nit by reverting the fix in place and
  confirming the new test fails, then restoring (see disposition table
  above). The M-1/m-1 tests are RED by construction — each asserts a
  concrete allow-turned-deny (or refusal) that requires the specific fix to
  hold; the module- and handler-level tests were themselves added and run
  green only after the fix landed, mirroring review 3's own RED-pin
  methodology for this same class of change.
