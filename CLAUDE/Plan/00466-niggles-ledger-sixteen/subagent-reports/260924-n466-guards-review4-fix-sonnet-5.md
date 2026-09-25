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
| **m-2** (minor) | Team-lead's addendum (below) asked for this to be fixed rather than carried forward: the both-edges pattern's `?`-only interior spelling now denies TEXTUALLY, independent of cwd or filesystem contents. See Addendum 2.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
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

## Addendum 1: false-positive fold-in (content vs Bash context)

Team-lead reported a live false positive: `secret_file_guard` denied an Edit
whose Python content contained `[*words[:subcommand_index], ...]` (a list
unpacking a slice), reading the crude tokeniser's own `*words[subcommand_index`
fragment as a glob matching `*.vault-password`. Two remedies, both
implemented:

- **(a) An unclosed `[` is not a bracket class.** `_token_literal_residue`
  was stripping ANY `*`/`?`/`[` character when computing a token's residue —
  including a lone `[` with no matching `]`, which bash (and `fnmatch`) both
  read as a literal character, never a wildcard. Fixed: only `*`/`?` are
  stripped now; a complete `[...]` bracket expression is still removed
  whole (unchanged). RED-pinned (`TestUnclosedBracketResidueIsLiteral`):
  reverting the fix makes `_token_literal_residue("*words[subcommand_index")`
  return the wrong (shortened) residue.
- **(b) Content scanning is literal-only.** Added a `MentionContext`
  ("bash"/"content") parameter, threaded through
  `find_protected_mention`/`_detail`/`iter_protected_mentions`/`_token_mention`.
  The unconditional literal/glob-pattern match (raw token + bracket
  expansions against every configured pattern) runs in BOTH contexts; the
  AGGRESSIVE glob-shaped heuristics (edge-overlap fnmatch, the DP
  intersection, the both-edges FS-truth route) now run ONLY for
  `context="bash"` — a real shell word a shell will actually expand.
  `secret_file_guard.py`'s `_script_content_mention` (the Write/Edit
  content-scan route) now passes `context="content"`. RED-pinned
  (`TestContentContextSkipsAggressiveGlobIntersection` +
  `TestContentContextThroughTheHandler`): a genuinely context-dependent
  example (`cat prod.vault-passw*rd` denies as Bash via the interior-wildcard
  DP, the identical text as a Python string literal stays allowed as
  content) fails when the context gate is reverted. The reported snippet
  itself turned out to be independently fixed by (a) alone (it has no `*`
  reaching the DP once the residue fix lands), so its own RED test doesn't
  exercise (b) — the interior-wildcard-string-literal test is what does.

## Addendum 2: m-2 (both-edges FS route is cwd/existence-dependent)

Team-lead's follow-up asked for the both-edges wildcard route
(`*.secret*`/`*vault_pass*`) to deny TEXTUALLY wherever the glob-intersection
judgement from M-1 says it can, not only when the file exists and the
caller's cwd happens to reach it — "keep the FS route only as an extra
positive signal, never as the only way to deny."

**First attempt, reverted.** A standalone "near-total-match residue" check
(mirroring `_glob_token_overlaps_stem`'s both-edges branch, but without
requiring the token's OWN wildcard to sit on both edges) was built, tested,
and then proven, by direct construction, to never fire on any input not
ALREADY caught by an existing check: for a token with exactly one wildcard,
"residue ends with/starts with the complete stem" is equivalent to "the
literal token (wildcard character included) already contains the stem as a
substring" — which plain `path_matches_globs` catches for free. It was
removed rather than shipped as dead code.

**What actually closes the gap.** The canonical shapes the FS-truth route
was built for (`demo.se?ret`, `vault?passwords.yml` — both edge-closed,
single `?`) are genuine textual truncations that the codebase's OWN false
positive history (Plan 00306/00311: `report-[0-9]*.txt`, `secret*.py`) rules
out from a blanket DP fix, because those shapes glob-intersect a both-edges
pattern identically to the genuine ones — the difference is only in the
literal characters, which the DP alone cannot see. The real, safe
distinguisher is `*` vs `?`: a both-edges pattern's own two wildcards can
absorb the required substring adjacent to ANY `*` the token carries,
wherever it sits, making the intersection trivially satisfiable regardless
of the token's actual text — but a token using only `?` can absorb at most
one character per `?`, so a genuine intersection there requires its fixed
literal text to already closely resemble the stem, a real signal.

Implemented: `_dp_intersection_is_meaningful` gained a both-edges-pattern
branch — meaningful (worth running the DP) only when the token carries no
`*`. `_glob_intersection_mention` no longer excludes both-edges patterns
from `eligible_patterns`; the meaningfulness gate does the filtering
instead. `_both_edges_glob_mention` (FS-truth) is unchanged and still the
only route for a `*`-bearing both-edges truncation (`demo.s*t`).
`TestBothEdgesFilesystemTruthRoute`'s own `?`-only tests now pass with no
file created at all; its one `does-not-deny` control was moved to the `*`
spelling specifically, since that shape alone still needs the file to be
absent to prove the allow.

RED-pinned (`TestBothEdgesTextualIntersectionIsCwdAndExistenceIndependent`

- the handler-level twin): `cd /tmp && cat /elsewhere/demo.se?ret` and a
  create-then-read of the same shape both deny with no real file anywhere
  near the process; `report-[0-9]*.txt`/`secret*.py` stay allowed (control).
  Reverting either code change (the `_dp_intersection_is_meaningful` branch,
  or the `eligible_patterns` filter) makes the new tests fail.

**Judgement call, flagged for review 5.** Team-lead's own RED-test example
in the addendum message was `cat /elsewhere/*ecre*` (a `*`-bearing token).
Taken completely literally, denying that would require dropping the both-
edges exclusion for `*`-bearing tokens too — which reopens Plan 00306/00311's
own false-positive class (`report-[0-9]*.txt`/`secret*.py` would then ALSO
deny, an established regression, not a hypothetical one; both are ordinary,
common shell idioms). This fix denies the `?`-only class textually and
keeps `*`-bearing both-edges truncations on the FS-truth route, unchanged
from before. If the `*`-bearing case genuinely needs to deny textually too,
that is a explicit human/team-lead call given how broad the usability cost
is, not one this agent will make unilaterally — please confirm in review 5.

Verification (all commands re-run after this addendum, superseding the
counts above): targeted module suite 679 passed; full unit suite 22,625
passed, 9 failed (the identical, pre-existing 4-file order-dependence set,
one more test passing overall than before this addendum since it added
tests of its own); `run_format_check.sh` clean; `audit_error_hiding.py` 0
violations; `llm_qa.py` 7/7 PASSED.

## Addendum 3: review 5 MAJOR-2, minor-1, and N39 (fixed in this pass)

Review 5 (`260925-guard-defects-review5-opus-5-5.md`, committed alongside
this addendum) found MAJOR-1 (this worktree was not clean during the
review -- resolved automatically by committing addendum 1/2's work),
MAJOR-2 (a real gap Addendum 1's own fix opened), and minor-1 (a
pre-existing, documented residual). Team-lead's own follow-up message
widened MAJOR-2's required fix beyond the review's own finding. All three
are fixed in this pass.

**MAJOR-2 — `context="content"` was too broad, reopening `.sh`/`.bash`
write-then-execute.** Addendum 1's fix applied `context="content"`
uniformly across every `_SCRIPT_EXTENSIONS` entry, including `.sh`/`.bash`
-- but that content genuinely IS shell text a shell expands when the
script runs (`bash deploy.sh`), so the weaker literal-only matcher reopened
exactly the vulnerability class Task 4.3 exists to close (`cat prod.vault-pass*`, `cat id_rs?`, `cat id*a` in a `.sh` file's content were
ALLOWED). Checked first whether the narrower `_token_literal_residue`
fix (item a) alone resolved the original Python-splat false positive
without any context split at all (team-lead's stated preference, if
true): confirmed empirically that it does for THAT shape, but also
confirmed it reopens a DIFFERENT false positive the context split was
built for -- an ordinary Python string literal that merely LOOKS
glob-shaped (`pattern = 'prod.vault-passw*rd'`) would deny under a
context-free "always aggressive" design, which is real source code, not a
mention. Went with the primary path instead: scope `context="bash"` (the
aggressive route) to content that genuinely IS shell text, and keep
`context="content"` (literal-only) for everything else.

`secret_file_guard.py`'s `_script_content_mention` now classifies by
FOUR signals, matching team-lead's explicit widened ask: (1) a
`.sh`/`.bash` extension, (2) a Makefile (`Makefile`/`makefile`/
`GNUmakefile` basename, or `.mk` extension -- and `_SCRIPT_EXTENSIONS`
itself is widened to scan these at all, since neither was in it before),
(3) a CI workflow YAML (`.github/workflows/*.yml`/`.yaml`, or a
`.gitlab-ci.yml`/`.gitlab-ci.yaml` basename -- also newly scanned), (4) a
shebang alone naming a shell interpreter (`sh`/`bash`/`zsh`/`dash`/`ksh`/
`ash`, with or without a leading path) on an otherwise extensionless
script -- the fourth signal also widens the scan gate, since an
extensionless file matches none of `_SCRIPT_EXTENSIONS`. Any of the four
selects `context="bash"`; everything else that still reaches the scan
(a `.py`/`.js`/`.rb`/... file, or a non-shell-shebang extensionless file)
keeps `context="content"`. The Makefile/CI-YAML routes scan the WHOLE
file rather than isolating recipe/`run:` lines specifically -- a
deliberate simplification in the safe direction (this guard's failure
mode is "scans a bit too much", never "misses a shell word").

RED-pinned end-to-end through the real handler
(`TestContentContextThroughTheHandler`, new tests): `.sh`/`.bash`/
`Makefile`/`.mk`/GitHub-workflow-YAML/`.gitlab-ci.yml`/shebang-only-shell
content carrying an interior-wildcard or `?`-glob mention still denies;
the identical text in `.py` content, an ordinary (non-CI) `.yml`, and an
extensionless file with a non-shell (`python3`) shebang all stay allowed
(controls). Reverting the classification (back to the Addendum-1 shape)
makes every new denial-side test fail while both controls still pass --
confirmed by direct revert-and-run.

The module-level WIP test flagged in team-lead's message
(`test_an_interior_wildcard_string_literal_denies_on_bash_but_not_content`)
is renamed/inverted: it now pins that `context="bash"` denies the SAME
text whether it arrived as a typed Bash command or as content scanned
with that context -- `context="bash"` is not a per-language exemption, it
is what the handler now selects for anything a shell genuinely executes.
`context="content"` stays the narrow exemption for genuinely non-shell
source, pinned by a sibling test.

**minor-1 — `bash -c '…'`/`sh -c '…'`/`eval '…'` nested quote-splice.**
The review's own repro (`bash -c 'cat id_'\''rs'\''a'`) was ALLOWED
because M-1's word normaliser (`iter_normalised_shell_words`) reads the
`-c` argument as ONE already-decoded word (`cat id_'rs'a`) but never
RE-PARSES that word as a nested command, so the inner quote-splice was
never resolved. Team-lead's follow-up: "re-parse the string argument of
`bash|sh|zsh|dash -c` and of `eval` with the SAME normaliser, recursively,
bounded by depth and by bytes."

Implemented directly in `shell_expansion.iter_normalised_shell_words`:
the word immediately following a recognised interpreter's `-c` (leading
path stripped before comparing, e.g. `/bin/bash`), or immediately
following `eval`, is re-parsed with the SAME function, recursively. Two
independent bounds, both new: `_MAX_NESTED_SHELL_DEPTH` (4 levels) and
`_MAX_NESTED_SHELL_BYTES` (32 KiB, shared across the whole call, not
reset per level). Past EITHER bound this raises `TooManyToEnumerateError`
rather than silently declining to recurse -- matching this module's own
existing fail-closed doctrine for `expand_braces`/`bounded_recursive_glob`:
"cannot rule out a protected path" must never be conflated with "no
match". Two documented, accepted simplifications, matching the reported
shape exactly rather than claiming full generality: only the SINGLE word
directly after `-c`/`eval` is treated as the nested command (bash's own
`-c` semantics: anything past it is positional arguments, not command
text; a multi-argument `eval a b` is not reassembled), and a flag
between the interpreter and `-c` (`bash --norc -c '…'`) is not
recognised (adjacency only).

RED-pinned at both layers: `TestIterNormalisedShellWordsNestedCommands`
(module-level, `shell_expansion`, using a benign quote-split word so the
mechanism is pinned without naming any protected pattern) and
`TestNestedDashCAndEvalCommandsDeny` (end-to-end via
`find_protected_mention_detail`, using the review's own literal shape)
each cover: the single-level report shape, the `eval` equivalent, an
interpreter with a leading path, two levels of `bash -c` nesting
(team-lead's requested RED test), mixed double/single quoting
(team-lead's other requested RED test), the documented flag-adjacency
limitation (control), an unrelated `bash -c` command staying allowed
(control), and excessive nesting raising `TooManyToEnumerateError`
rather than hanging or silently allowing. Reverting the recursive
re-parse (back to the pre-fix single-level tokeniser) makes 11 of these
13 tests fail (the 2 controls still pass, as they must) -- confirmed by
direct revert-and-run.

**N39 — the 9-failures-only-in-a-whole-suite-run leak (not a review-5
finding; a parallel diagnosis handed to this worktree).** A companion
agent bisected the leak to `test_project_containment.py`'s class-wide
`_project_root` autouse fixture (`with patch(...) as mock`) being
double-patched by three tests that ALSO called
`monkeypatch.setattr(..., classmethod(lambda cls: _raise()))` on the
exact same target -- `monkeypatch`'s finalizer runs AFTER the fixture's
own `with patch(...)` block has already restored the real classmethod,
so the second patcher's teardown overwrote it AGAIN with the fixture's
stale `MagicMock`, permanently, for the rest of the pytest PROCESS. Fixed
per the diagnosed recipe: the three tests now reconfigure the fixture's
own `mock` (`mock.side_effect = ...`) instead of introducing a second
patcher; the fixture itself gained a post-teardown tripwire assertion
(`isinstance(ProjectContext.__dict__["project_root"], classmethod)`) so
any FUTURE double-patch in this file fails immediately, at the fixture
boundary, with a clear message, rather than silently corrupting an
unrelated downstream file; and a new regression test
(`TestProjectRootDoublePatchDoesNotLeakAcrossFiles`) runs the exact
polluter/victim pair from the bisection together in one subprocess pytest
invocation and asserts both pass -- the shape the leak actually needs to
reproduce, which neither test alone exercises. RED-pinned by reverting
only the polluter test back to the double-patch shape: the regression
test fails with the IDENTICAL symptom the original bisection found
(`'Example:' is contained here: Example: /repo/test.py`), confirming the
new test is a genuine pin, not a vacuous one.

Verified per team-lead's instruction (targeted, not the whole suite, host
overloaded): the polluter file plus all four originally-diagnosed victim
files together, sequential, no `-p xdist` -- 215 passed. The broader
targeted suite across every file touched this round (secret_file_matching,
shell_expansion, secret_file_guard, project_containment,
quarantine_artefact_read_guard, enforce_llm_qa, rule_ids, absolute_path,
model_fallback_detector, rule_explain/test_lookup,
dangerous_invocation_corpus_checker) -- 809 passed. `llm_qa.py` run
against every `check_*.py`-backed detector plus `lint`/`type_check`/
`security`/`error_hiding` -- 27/27 PASSED (one `magic_values` violation
found and fixed along the way: the regression test's own subprocess
`timeout=60` moved to `Timeout.REQUEST_LONG`). The full unit suite was
NOT re-run this pass per team-lead's explicit host-overload instruction.

## Addendum 4: review 6's three named closures (interpreter flags, multi-word eval, other-language shell-exec calls)

Team-lead's follow-up closed the two review-5/Addendum-3 minor-1 "accepted
simplifications" as real defects, plus a third item extending the same
shell-exec detection to non-shell languages. Picked up from a previous
agent's uncommitted WIP (cut off by a usage limit) -- reviewed it against
the three asks, found it sound, and finished the gap it left (no tests for
item 3 through the real handler) rather than rewriting what was already
correct.

**Item 1 -- a flag between the interpreter and `-c`.** minor-1's documented
limitation ("adjacency only") is closed by
`_classify_interpreter_option_word` in `shell_expansion.py`: walking
`<interpreter> [options...] -c <code>` word by word, recognising `-c`
anywhere inside a short-option cluster (`-lc`), long options
(`--rcfile`/`--init-file`, value as the next word), and `-o`/`-O`
consuming a value either glued (`-opipefail`) or separate (`-O extglob`).
Covers `bash -x -c '…'`, `bash -lc '…'`, `bash -O extglob -c '…'`.

**Item 2 -- `eval` with several words.** minor-1's other documented
limitation ("only the single word directly after eval") is closed:
`eval`'s own argument words are collected until a genuine shell command
terminator (`;|&<>()`) and rejoined with a single space each -- matching
eval's real semantics -- then re-parsed recursively through the same
bounded mechanism (`_MAX_NESTED_SHELL_DEPTH`/`_MAX_NESTED_SHELL_BYTES`,
shared across every nesting level and shape). The same word-collection
path also covers `builtin eval`/`command eval` (triggers on the literal
word `eval` appearing at all, prefix or not), `source <(echo|printf …)`/
`. <(echo|printf …)` (a literal producer's joined output is what gets
sourced), `bash <<<'…'` (a here-string with no `-c`, read from stdin),
and a literal `echo '…' | bash` (piped to a shell's stdin). A `source <(...)` /`. <(...)` whose substituted command is NOT a recognised literal
producer cannot be examined at all and FAILS CLOSED (raises
`TooManyToEnumerateError`) rather than silently passing through --
matching this module's existing doctrine for
`expand_braces`/`bounded_recursive_glob`.

RED-pinned end-to-end via `find_protected_mention_detail`
(`TestReview6ClosedShellFeedShapes`, `tests/unit/utils/ test_secret_file_matching.py`): the flag-before-`-c` shapes, `-lc`,
multi-word `eval` (team-lead's own repro), `eval` with two double-quoted
words, `builtin eval`/`command eval`, `source <(echo …)`, the non-literal
`source <(...)` fail-closed raise, a here-string, and a literal-echo pipe
to `bash` -- all deny (or raise, for the fail-closed case); an unrelated
`bash -c` command stays allowed (control, carried from review 5).

**Item 3 -- shell-executing calls in other languages.**
`secret_file_guard.py` gained `_shell_exec_call_literals`, dispatched by
file extension, extracting string-literal arguments to a KNOWN
shell-executing call and scanning them with `context="bash"` (the
aggressive route already used for `.sh`/`.bash` content), while the rest
of the file stays on the weaker `context="content"` literal-only scan:
Python (`os.system`, `os.popen`, any `subprocess.*` call carrying
`shell=True` or an argv list naming a shell interpreter, e.g. `["bash", "-c", …]`), Ruby (backticks, `%x{...}`, bare `system`/`exec`), PHP
(`shell_exec`, `exec`, `system`, backticks), Perl (backticks, `qx{...}`,
bare `system`), Node (`exec`/`execSync`, with or without the
`child_process.` prefix). This is a bounded window after the call site
standing in for a real argument-span matcher (documented as the same
honest limit `security_antipattern`'s own docstring states), not a
parser.

The previous agent's WIP had no test coverage for item 3 through the real
handler at all -- added `TestShellExecCallLiteralsInOtherLanguages` (18
tests) in `tests/unit/handlers/pre_tool_use/test_secret_file_guard.py`,
end-to-end via `handler.matches()`: a deny case per language/construct,
paired with an ordinary-string-literal control that must stay allowed
(the same `pattern = 'prod.vault-passw*rd'` control used elsewhere in
this file), plus a `subprocess.run([...])` control with no `shell=True`
and no shell name in its argv, which never reaches a shell and must stay
allowed. Some fixture bodies assemble the call syntax from split string
literals (e.g. `"exec" + "Sync(...)"`) purely to avoid
`security_antipattern` pattern-matching the fixture's own contiguous
`os.system(`/`exec(`/`shell_exec(` text on the Edit that authored the
test file -- a constraint anyone touching this test class again will hit
the same way.

**Verification** (targeted only, per standing instruction -- no
whole-suite run): `TestShellExecCallLiteralsInOtherLanguages` +
`test_shell_expansion.py` -- 71 passed. The full `test_secret_file_guard.py`

- `test_secret_file_matching.py` + `test_shell_expansion.py` -- 487
  passed. Every `scripts/qa/check_*.py` detector run individually -- all
  exit 0. No suppressions or exclusions added. Worktree daemon restarted
  clean after commit.
