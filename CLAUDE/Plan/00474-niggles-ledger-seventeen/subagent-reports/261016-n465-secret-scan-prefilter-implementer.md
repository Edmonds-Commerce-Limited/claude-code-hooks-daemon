# N465: secret-file guard prefilter (implementer, Opus 5.5)

Branch `worktree-n465-secret-scan-prefilter`, based on `31cb64ee8`. The work was started before the host reboot and finished after it.

## Assumptions (for the coordinator to rule on)

1. **The prefilter gates the `cd`/`pushd` tracking, not the protected-name match.** Profiling the 00495 shape showed that the per-line `_shell_words` calls come from `effective_cwds`. It tokenises every `;`/`&&`/`|`/newline segment of the content to find directory changes. The protected-name match does not tokenise per line. So the cheap gate sits in front of that tokenisation: a segment is tokenised only if, after deleting the characters POSIX shlex removes (`'`, `"`, `\`), it contains `cd` or `pushd`. That gate is sound by construction. shlex only deletes those three characters, so a first word equal to `cd`/`pushd` always leaves that substring in the stripped segment.
2. **A `"content"` scan (non-shell files such as `.py`) no longer computes the cd directories at all.** `_token_mention` reads `effective_cwds` only in `"bash"` context. Both the anchored spellings and the index glob match sit behind `if context != "bash": continue`. The directories were computed and then thrown away.
3. **No name-based prefilter in front of the main mention scan.** It cannot be made sound. The scan catches spellings that share no substring with the protected name: quote splitting (`id_"rs"a`), escapes (`id_r\sa`), ANSI-C escapes (`$'id_\x72sa'`), percent-encoding (`.vault-pa%73s`), brace expansion (`.vault-pas{s,x}`), globs that truncate a name (`dummy.vault-p*`, `id_rs?`), Python string concatenation, and a `cd` into a protected directory followed by a bare relative name. The corpus pins all of these. Those cases therefore stay on the full path, as the brief allows.

## What changed

- `src/claude_code_hooks_daemon/utils/secret_file_matching.py`:
  - New `_may_change_directory` gates `effective_cwds`.
  - `iter_protected_mentions` derives the cd directories only for a `"bash"` scan.
- Release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/071-secret-guard-judges-large-scripts-faster.md`.

## Tests

- `tests/unit/handlers/pre_tool_use/test_secret_file_guard.py`:
  - `TestDirectoryChangePrefilterChangesNoVerdict` is the equivalence test. It runs 72 corpus lines × 3 routes (Write `.sh`, Write `.py`, Bash), plus the whole corpus as one file. The corpus covers every shipped protected pattern and a configured directory pattern. Spellings include quoting, escapes, `$HOME`/`${HOME}`/`~`/`$PWD`, relative, absolute and `..` paths, globs, braces, option-attached values, `@file`, Python `open()` and cd/pushd in all their quoted forms, with negatives. It pins the exact `(pattern, token, route)` of every finding.
  - `TestLargeBenignWriteCost` counts tokenisations and sets a CPU-time bound. A 100 KB benign `.sh` Write must take under 2.5 s of CPU, fastest of 3 runs. That is half `Timeout.HOOK_DISPATCH`, and about 15 times the 0.17 s measured here. The bound catches a gross regression without flaking under load (N462). The call-count tests pin N465 itself.
- `tests/unit/utils/test_secret_file_matching.py`, `TestEffectiveCwdsPrefilterIsExact`:
  - It compares the gated `effective_cwds` against an ungated reference on 67 hand-written cd-adjacent shapes × 3 cwd kinds, and on all of them joined into one script.
  - It also runs a seeded fuzz of 4000 random strings over the characters that build, quote, escape or split a `cd`/`pushd`.

**The pins hold on the old code as well as the new.** `untracked/scratch/n465_check_pins.py` replays the 219 pinned (route, input) pairs against a `git archive` copy of `31cb64ee8`'s `src/`, and then against the branch. Both runs gave `checked=219 mismatches=0`.

RED, quoted from the run before the source change:

```
FAILED tests/unit/utils/test_secret_file_matching.py::TestEffectiveCwdsPrefilterIsExact::test_a_script_with_no_directory_change_is_never_tokenised - AssertionError: assert 1001 == 0
FAILED tests/unit/utils/test_secret_file_matching.py::TestEffectiveCwdsPrefilterIsExact::test_only_the_segments_that_could_change_directory_are_tokenised - AssertionError: assert 31 == 10
FAILED TestLargeBenignWriteCost::test_no_line_is_shell_tokenised[/proj/deploy.sh-...] - AssertionError: assert 3013 == 0
FAILED TestLargeBenignWriteCost::test_no_line_is_shell_tokenised[/proj/tool.py-...] - AssertionError: assert 1653 == 0
FAILED TestLargeBenignWriteCost::test_a_content_scan_never_computes_the_directories - AssertionError: assert 1 == 0
```

GREEN: both touched files, `1372 passed`.

## Timing

Run with `untracked/scratch/n465_measure.py` on the same host, before (a copy of `31cb64ee8`'s `src/`) and after. It calls `_matched_pattern_and_route` with the shipped protected patterns, best of 3 runs (1 run at 1.2 MB). Shapes:

- `sh` is the 00495 Task 3.2 line, repeated.
- `sh-real` is a shell line with `${}` and `$( )`.
- `py` is a Python line.

| shape   |   size | before (ms) | after (ms) |
| ------- | -----: | ----------: | ---------: |
| sh      |  12 KB |          38 |         18 |
| sh      | 120 KB |         376 |        205 |
| sh      | 1.2 MB |        4569 |       2524 |
| sh-real |  12 KB |          60 |         52 |
| sh-real | 120 KB |         612 |        475 |
| sh-real | 1.2 MB |        5307 |       3885 |
| py      |  12 KB |          80 |         53 |
| py      | 120 KB |         944 |        740 |
| py      | 1.2 MB |        8062 |       7524 |

This host is faster than the 00495 one: 3.1 ms/KB before here, against the 8.5 ms/KB 00495 reported. The ratio is the comparable figure. The 00495 shape is roughly 1.8 to 2.1 times faster. Verdicts are unchanged in every row. The 1.2 MB `advisory` rows are the same before and after.

## Still open

A large Write still exceeds the 100 ms Rule 0 target, at about 1.7 ms/KB for the 00495 shape. The remaining cost is whole-file analysis that a per-line name prefilter cannot soundly skip (assumption 3):

- `_brace_expansion_tokens` / `shell_expansion._shell_brace_words`
- the normalised word stream
- for `.py`, `python_string_literals` (an AST walk) and `_python_shell_exec_literals_ast`

Closing that gap needs its own ledger entry. Candidates are making the brace scan skip text with no `{`, and a single AST walk shared by the two Python scans. Each needs its own equivalence proof.

## QA

The final targeted `llm_qa.py changed` verdict is recorded in the commit that follows this report.
