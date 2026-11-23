# Independent security review: PR #232 (N716, secret guard glob, bracket and option gaps)

Branch `fix-n710-secret-guard-glob-later-parts`, diff `origin/main...HEAD` (commits 9f6f70e04, f989093aa). Read-only review. Dummy fixtures only.

Intended destination: `CLAUDE/Plan/00474-niggles-ledger-seventeen/subagent-reports/261123-opus-independent-review-pr232.md` in the main tree. The cross-worktree write guard blocked that write from this sub-agent, so the coordinator should copy this file there.

## Verdict

**Safe to merge as a strict improvement. It does not fully close what it claims.**

- I found **no fail-open regression**. Every probe was run against both this PR's `src` and main's `src`. Every verdict that differed went from allow on main to deny on the PR. None went from deny to allow. The method is described below.
- **Several bypasses remain inside the PR's own claims**:
  - findings 1 and 2: nocaseglob plus a finite bracket, and a POSIX class on the Write and no-index routes;
  - finding 3: the option-switch keyword list;
  - finding 4: an extglob word beside a size cap;
  - finding 5: extglob produced without a literal `(`.
- Every one of them is also present on main, so none blocks the merge. They should be filed as N716 follow-ups. The PR text and the builder report should stop saying these classes are closed.
- Two claims in the builder report are false as worded:
  1. "Every N716 reproducer is denied with the index off". Finding 2 is a POSIX-class reproducer that is allowed with the index off.
  2. "Past [the bound] the scan raises IncompleteScanError, which the guard denies". On the Bash route an earlier size cap fires first, and that path allows (finding 4).

## Method

**Harness.** pytest probe files in this directory (gitignored scratch in the worktree). They reuse the PR's own `project` fixture and `_every_route`, which returns the Bash route, the Write-script route and the Bash route with no index. Each probe runs in two modes: defaults-certain (an all-off shell snapshot) and conservative (no snapshot).

**Bash truth.** Every allowed probe was rerun in real bash 5.2.37 (`env -i`, empty HOME) against a dummy tree with `kit/bin/late` and `kit/.hid/late2` linked to a dummy file. A probe counts as a **bypass only when the guard allows it and bash really prints the dummy content**.

**Main comparison.** The same probes were run with `PYTHONPATH=/workspace/src` (main).

**Production relevance of defaults-certain mode.** The host's real shell snapshots, checked for option lines only, record `shopt -u dotglob`, `shopt -u globstar` and `shopt -u nocaseglob`, plus `shopt -s globasciiranges`. Defaults-certain mode is therefore what production runs, so bypasses in that mode are live.

**Targeted tests.** `test_secret_file_guard_glob_bash_options.py`, `test_secret_file_guard_glob_later_parts.py` and `tests/unit/utils/test_shell_snapshot.py`, run with `nice -n 19` against the worktree's source: 263 passed, 2 skipped.

**Bracket reader differential** (`bracket_diff.py`). 63 bracket patterns × 26 short names, comparing `_component_spells(..., ignore_case=False)` with bash `nullglob` expansion. Patterns included `[]abc]`, `[!]x]`, `[a-]`, `[-a]`, `[z-a]`, `[[:alpha:]-z]`, `[[.a.]]`, `[[=a=]]`, `[\]]`, `[a-[]`, `[]-a]`, `[!]]` and `[^]`.

- **Result: 0 fail-open, 644 over-matches.** All over-matches are fail-closed widenings.
- `_bracket_regex` itself is sound.

**Reproducers below.** `P` is the dummy protected basename the fixture assembles (`"id_" + "rsa"`). Reproducers show it spelled out only where the shape matters; the probes build it at runtime.

## Findings

### 1. HIGH, pre-existing, inside the claim: nocaseglob plus a finite bracket naming a protected file directly is allowed on every route, in both modes

```
shopt -s nocaseglob; cat kit/lib/[I]D_RSA        # "[" + P_UPPER[0] + "]" + P_UPPER[1:]
shopt -s nocaseglob; cat kit/lib/ID_RS[A]
```

**Verdicts.** Guard: allow, allow, allow, in both modes, on the PR and on main. Bash reads the file (checked with a dummy name: `shopt -s nocaseglob; cat kit/lib/[D]UMMYNAME` prints the content).

**Why it is allowed.** `_expand_bracket_expressions` (`secret_file_matching.py:961`) expands the finite bracket into the literal `ID_RSA`. The literal check `first_matching_glob` is case-exact. The stem loop at `:3556-3557` then skips the expansion because it is no longer glob-shaped. The index fallback at `:3651` (`protected_file_index.glob_matches`) is case-exact, which is N719. The glob walk at `:3703` judges only link hops, and the file here is a plain file.

**Contrast with the PR's own test.** `ID_RS*` is denied because the `*` keeps it in the stem loop. The PR's test covers only that shape.

**This makes N719 reachable**, despite the builder's "not reproduced as a leak". The fix needs two parts:

- when nocaseglob is not certainly off, compare the bracket expansions case-blind with the stems;
- route the index matcher through `_component_regex`.

### 2. HIGH, pre-existing, inside the claim (POSIX class not first): Write-script and no-index routes allow a class bracket naming a protected file directly

```
cat kit/lib/[x[:lower:]]d_rsa                   # "[x[:lower:]]" + P[1:]
cat kit/lib/id_rs[x[:lower:]]                   # P[:-1] + "[x[:lower:]]"
```

**Verdicts.** Guard: Bash deny, Write allow, no-index allow, in both modes, on the PR and on main. Bash reads the file. `[x[=i=]]` is denied on every route.

**Why.** The stem heuristic's residue comes from a second, bracket-naive reader. `_BRACKET_EXPRESSION_RE = r"\[!?\]?[^\]]*\]"` (`:885`, used by `_token_literal_residue`, `:1095`) closes the bracket at the first `]`. The residue of `[x[:lower:]]d_rsa` is therefore `]d_rsa` (measured), which is not a substring of the stem, so the residue gate at `:3608-3609` fails. Only the index, on the Bash route, catches it.

**Route parity is broken.** The Write route is how a script is authored, and running the script afterwards is not re-judged: `bash plan2.bash` and `. ./plan2.bash` holding that line are both allowed. The no-index route runs whenever the index is cold or unavailable.

**This contradicts the PR's "one bracket-aware translator".** Shell-pattern readers that still bypass `_bracket_regex` and `_component_regex`:

- `_BRACKET_EXPRESSION_RE` (`:885`) and its users `_is_glob_shaped` and `_token_literal_residue` (`:1026`, `:1095`);
- `_expand_bracket_expressions` (`:961`), which is case-exact (finding 1);
- `protected_file_index._component_pattern` and `_bracket_expression` (`protected_file_index.py:595`, `:638`), which are N719.

**Fix.** Make the residue reader class-aware: skip a whole `[...]` as `_bracket_regex` scans it. Or, when a bracket holds a class, use `_component_spells` against the stem without the residue gate.

### 3. HIGH, pre-existing, inside the claim (dotglob or nocaseglob switched on without `shopt`): the keyword list in `_SWITCHES_OPTIONS` is bypassed

`shell_snapshot.py:51-55` keeps defaults-certain mode unless the raw text contains a listed word. Each command below is allowed on every route in defaults-certain mode (production), and bash reads `kit/.hid/late2` (`kit/bin/late` for the last row):

| Reproducer                                                        | Gap                                                                |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| `X=sho; ${X}pt -s dotglob; cat kit/*/late2`                       | command name built by expansion                                    |
| `X=shopt; $X -s dotglob; cat kit/*/late2`                         | same                                                               |
| `sh''opt -s dotglob; cat kit/*/late2`                             | quote splits the keyword                                           |
| `sh\opt -s dotglob; cat kit/*/late2`                              | escape splits the keyword                                          |
| `$(printf '\163hopt') -s dotglob; cat kit/*/late2`                | command substitution as the command                                |
| `trap "$(printf 'sh%sopt -s dotglob' '')" DEBUG; cat kit/*/late2` | trap body                                                          |
| `export GLOB''IGNORE=zz; cat kit/*/late2`                         | quoted name passed to `export` (plain `export GLOBIGNORE=` denies) |
| `N=GLOB; declare ${N}IGNORE=zz; cat kit/*/late2`                  | name built by expansion                                            |
| `printf -v GLOB''IGNORE zz; cat kit/*/late2`                      | `printf -v`                                                        |
| `bash -xO dotglob -c 'cat kit/*/late2'`                           | `-O` inside a flag cluster                                         |
| `bash --rcfile r.md -ic 'cat kit/*/late2'`                        | rc file not read (r.md holds `shopt -s dotglob`)                   |
| `builtin . ./r.md; cat kit/*/late2`, `command . ./r.md; …`        | `.` after `builtin`/`command`                                      |
| `! . ./r.md; …`, `time . ./r.md; …`                               | `.` after `!`/`time`                                               |
| `if . ./r.md; then cat kit/*/late2; fi`, `while . ./r.md; do …`   | `.` after `if`/`while`/`elif`/`until` (only `then/do/else` listed) |
| `X=sho; ${X}pt -s nocaseglob; cat kit/B?N/late`                   | same as row 1, for nocaseglob                                      |

**What does not bypass.** `export`, `declare -x` and env-prefix `GLOBIGNORE=` (deny). `N=BASH; export ${N}OPTS=dotglob; bash -c …` (bash ignores it). `SHELLOPTS=…` (readonly in bash, harmless). `bash -ic` with no rc file.

**Fail-closed fix.** Keep certain mode only when every command-position word is a plain literal: no `$`, backtick, quote or backslash. Also drop it for `trap`, `printf -v`, `-O` inside a cluster, `--rcfile`/`--init-file`/`-i`, and any `.` in command position.

### 4. HIGH, pre-existing, partly improved: an extglob word beside a size cap is allowed with an advisory

```
bash -O extglob -c 'echo $(echo $(echo … 20 levels … $(cat kit/@(bin)/late)))'
bash -O extglob -c 'cat kit/@(bin)/late' {1..9}{1..9}{1..9}{1..9}{1..9}{1..9}{1..9}
```

**Verdicts.** The nesting form is allowed on the Bash and no-index routes at depth 20, 40, 60, 100 and 200. The Write route now denies it, which is new in this PR. The brace form is allowed on every route. Both hold in both modes. Bash reads the link in both.

**Controls.** The same commands with `b?n` or `bin` in place of `@(bin)` are denied on every route.

**Why.** The handler logs `scan hit a size limit` (`secret_file_guard.py:1449-1451`). `_gave_up_finding_or_advisory` (`:1485-1500`) escalates to deny only when `_holds_search_or_glob` sees a search or a glob, and an extglob group holds none of `*?[`. The new `IncompleteScanError` bound (`secret_file_matching.py:3072-3074`) is never reached on this route. It would deny if reached (it is a `ResolutionFailedError`, which `:1440-1442` denies). The unit test checks only `_extglob_words`, not the handler.

**Depth cap.** Just under the cap, the word is found and denied.

**Fix.** Have `_holds_search_or_glob` treat `_EXTGLOB_OPENER` as a glob, and add an end-to-end test.

### 5. MEDIUM, pre-existing, inside the extglob claim: an extglob or glob with no literal `(` or pattern character in the text

| Reproducer                                                 | Guard (all routes, both modes) | Bash reads |
| ---------------------------------------------------------- | ------------------------------ | ---------- |
| `bash -O extglob -c $'cat kit/@\x28bin\x29/late'`          | allow                          | yes        |
| `shopt -s extglob` (newline) `P='@(bin)'; cat kit/$P/late` | allow                          | yes        |
| `P='b?n'; cat kit/$P/late`                                 | allow                          | yes        |

- **The `$'…'` body.** Its escapes are not decoded before scanning (`_word_piece`, `secret_file_matching.py:3131-3135`).
- **The variable forms.** An unquoted `$P` holding a pattern is globbed after expansion, and the guard does not track assignments. The `b?n` row is a general glob gap that is older than this PR.

### 6. LOW, new and accepted by the builder: quoted `!(…)` text can deny when the cwd holds a protected link

See the table below. From the root with no root-level link, all 28 sampled commands are unchanged.

### 7. LOW: a reversed range logs a full traceback

`_component_regex` (`:4772-4778`) logs a full traceback per `re.error` (`[b-a]`, `[a-[]`). It fails closed and is cached per component, but it lets a command fill the log. Log one line instead.

### 8. LOW: `globasciiranges` is not required by the snapshot check

Real snapshots record it. With it off in a UTF-8 locale, `[a-c]` can match `B` while certain mode reads ranges case-exact. N719 mentions this.

### 9. INFO: sound

- **`_bracket_regex`.** The differential found no fail-open case.
- **Case union.** `(?:X)|(?i:X)` is correct for negated brackets.
- **Route parity.** Identical on all three routes for every linked-file probe outside findings 2 and 4.
- **Performance.** No regression.
  - `_extglob_words`: 2000 quoted words took 0.008 s, 2000 substitutions 0.019 s, 3000 `'('` openers 0.004 s, and deep nesting under 1 ms.
  - Whole route: 2000 bracket globs took 1.77 s on the PR against 2.72 s on main (3 routes). 500 extglob words took 0.39 s against 0.42 s.
- **Under the cap.** Nested `bash -c`/`$(…)`/backtick/here-string/eval bodies are denied. So are brace groups around extglob, nested `!(@(…))`, extglob combined with nocaseglob, and heredoc bodies.
- **Explicit options.** `GLOBIGNORE`, `BASHOPTS` and `BASH_ENV` in plain, export, declare and env-prefix forms switch to the conservative reading.
- **`set -f`.** The guard still over-denies globs that bash would not expand. That is unchanged and acceptable.
- **Unterminated and odd groups.** `kit/@(bin|zz/late` and `kit/@(b;in)/late` are allowed, but bash cannot read them.
- **New over-denies.** `kit/!(lib|bin)/late2`, `kit/@(bin/late|zz)` and `kit/!(x)*/late2` are now denied, although bash 5.2 reads none of them. These are harmless.

## False-positive table

The 28 realistic commands below were run against main and the PR from the project root, where the fixture has `kit/bin/late` linked. 10 of them were run again from `kit/bin` (which holds the link) and from a root holding a top-level protected link. Verdicts are Bash/Write/no-index.

| Command                                                            | Root, main | Root, PR | Link in cwd or root, PR |
| ------------------------------------------------------------------ | ---------- | -------- | ----------------------- |
| `awk '!(NR%2)' notes.txt`                                          | allow      | allow    | **deny (new)**          |
| `python3 -c 'print(*(1, 2))'`                                      | allow      | allow    | deny (also on main)     |
| `find . -name '*.txt' -exec wc -l {} +`                            | –          | D/A/A    | D/A/A (not this PR)     |
| `rg '\w+(\.\w+)*' notes.txt`                                       | –          | allow    | allow                   |
| `grep -E 'colou?(r)' notes.txt`                                    | –          | allow    | allow                   |
| `git log --grep='feat!(x)'`                                        | –          | allow    | allow                   |
| `pytest -k 'not (slow or flaky)' -q`                               | allow      | allow    | allow                   |
| `jq '.[] \| select(.a == 1)' notes.txt`                            | –          | allow    | allow                   |
| `git log --format='%h %s (%an)' -n 3`                              | allow      | allow    | allow                   |
| `echo "$(git rev-parse HEAD)"`                                     | allow      | allow    | allow                   |
| `awk 'NR>=1 && NR<=20' …`, `git log --oneline -n 5`, `git diff …`  | allow      | allow    | –                       |
| `grep -rE '(foo\|bar)+' kit/lib`, `find kit \( -name … \)`         | allow      | allow    | –                       |
| `pytest -k '(glob and bracket) or extglob' -q`                     | allow      | allow    | –                       |
| `jq '.items[] \| select(.name \| test("^a(b\|c)"))' data.json`     | allow      | allow    | –                       |
| `jq -r '.[] \| (.a // "x")'`, `python3 -c 'print((1+2)*3)'`        | allow      | allow    | –                       |
| `gh pr view 232 --json body,comments`, `gh issue list --search …`  | allow      | allow    | –                       |
| `bash -c 'echo ok; ls kit/lib'`, `for f in kit/lib/*.txt; …`       | allow      | allow    | –                       |
| `source .venv/bin/activate && pytest …`, `. .venv/bin/activate; …` | allow      | allow    | –                       |
| `eval "$(direnv export bash)"; ls kit/lib`                         | allow      | allow    | –                       |
| `ls kit/lib/*.txt`, `cat kit/*/notes.txt`, `ls kit/*`              | allow      | allow    | –                       |
| `rg -n '@\(' src`, `sed -n '1,5p' …`                               | allow      | allow    | –                       |

**Summary.** No newly denied command in normal repository work. There is one new denial (`awk '!(NR%2)'`), and only when a protected link sits in the cwd or root.

## Recommendation

**Merge.** File follow-ups, test-first, each with an end-to-end three-route test:

| Priority | Findings | Follow-up                                                                                                      |
| -------- | -------- | -------------------------------------------------------------------------------------------------------------- |
| a        | 1 and 2  | Case-blind or class-aware direct-name reading: residue reader, finite-bracket expansions, index matcher (N719) |
| b        | 4        | `_holds_search_or_glob` counts extglob groups                                                                  |
| c        | 3        | Certain mode only when every command word is a plain literal                                                   |
| d        | 5        | Decode `$'…'` bodies; deny a pattern-holding variable that reaches a path word                                 |
| e        | 7, 8     | Single-line log for a refused regex; require `globasciiranges`                                                 |
