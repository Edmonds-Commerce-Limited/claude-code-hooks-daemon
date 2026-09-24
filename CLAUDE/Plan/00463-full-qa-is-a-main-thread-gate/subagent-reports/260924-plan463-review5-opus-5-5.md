# Plan 00463 fifth review: verification of the review 4 fixes (Opus 5.5)

**Scope.** Branch `worktree-plan-463-full-qa-gate` at `5ec9abfa`. I checked the implementer's
"Review 4 fixes" section and the two merges of `main` (`403e3284`, `21f5b0f7`) against review 4's
N1 to N12. The review was read-only. Nothing tracked was edited or committed. I started the 463
worktree's daemon once and stopped it again, returning it to its earlier NOT RUNNING state.
`CLAUDE.md` was not regenerated, and `git status` is clean. This report is the only new file,
and it is uncommitted.

**How it was probed.** All probes are under `/workspace/untracked/scratch/probe_463v5_*`:

- `probe_463v5_blocker.py` and `_out.txt`: a new corpus of 266 commands, each judged by the
  configured handler with a sub-agent event. It covers wrappers, launchers, subshells,
  substitutions, chains, `cd`, quoting, variables, functions, `python -c`, `bash -c`, heredocs,
  paths and mentions. `probe_463v5_blocker_extra.py` and `_out.txt` add 12 rows on `llm_qa.py`
  after a `cd`.
- `probe_463v5_regression_bc804523.py` and `_out.txt`: the same `cd` rows through the blocker as it
  stood at `bc804523`.
- `probe_463v5_timing.py`, `probe_463v5_scaling.py`, `probe_463v5_chain_timing.py` and their
  `_out.txt` files: timing through the handler alone and through the whole PreToolUse chain.
- `probe_463v5_n10_chain.py`, `probe_463v5_n10_{new,old}.json` and `probe_463v5_n10_diff.txt`: 832
  heredoc commands through the whole chain, once with main's delimiter regex and once with N10's.
  `probe_463v5_n10_timing.py` times the regex alone.
- `probe_463v5_n2.sh`, `probe_463v5_n2b.sh` and `probe_463v5_errexit.sh`, with `_out.txt` files:
  the certified-head refs, run for real in a scratch clone (`probe_463v5_repo`).
  `probe_463v5_n2_fake_run.py` drives llm_qa's own run, record and certify code with stub tools, so
  nothing ran the real suite.
- `probe_463v5_n1_pattern.sh` and its outputs: the glob-reader guard, tested with a new pattern.
- `probe_463v5_setup_worktree.py` and `_out.txt`: further printed shapes for the N7 guidance test.

The in-process chain probes send main-thread or sub-agent events with no `synthetic_source`
marker. The reason is that `scope: SUB` declines a synthetic event, so the handler under test would
never run. No daemon received these payloads and no verdict log was written. The hand-built
payloads carry `synthetic_source: review-463-v5` in their probe files.

**Targeted tests (no full suite):** in the 463 worktree, 720 passed and 1 was skipped. The files
were:

- `test_llm_qa_live_daemon.py`, `test_llm_qa_provenance.py`, `test_llm_qa_main_moved.py` and
  `test_llm_qa_run_lock.py`;
- `test_main_moved_branching_survives_errexit.py`;
- `test_subagent_full_qa_blocker.py` and `test_shell_segmentation.py`.

`untracked/qa/` and `refs/integration/*` were identical before and after that run
(`probe_463v5_qa_{before,after}.txt`). Review 4's own `probe_463r4_blocker.py` still reports 0
mismatches of 166.

**Counts.**

- Review 4 findings: 9 VERIFIED (N3, N4, N5, N7, N8, N9, N10, N11, N12). 2 VERIFIED with a
  residual (N1, N2). 1 fixed but REGRESSED elsewhere (N6).
- New findings: 0 blocker, 2 major, 7 minor, 9 nit.
- Blocker corpus: 266 rows (181 expect deny, 85 expect allow). It gave 6 false denies and 17 false
  allows. Of the 17 false allows, 1 is deliberate obfuscation and 5 fall under the documented
  limits. The 12 extra rows add 7 more false allows, all from M1.

---

## Review 4, finding by finding

| #   | Verdict                 | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| N1  | VERIFIED + residual     | The declared `path_glob` rules match `DOCUMENT_GLOBS` and the other readers' globs. **Residual:** the guard checks reader FILES, not their PATTERNS (m4).                                                                                                                                                                                                                                                                                                                                        |
| N2  | VERIFIED + residual     | Run for real in the clone. A failing run, a dirty tree, an untracked file, a tree edited mid-run and HEAD moved mid-run all certify nothing. A second `--start` refuses, and `--restart` clears the certified head. A late commit gives `head-moved` (7). `--advance` refuses a non-merge commit, a `--no-ff` side branch and an evil merge. `--finish` refuses before landing. **Residuals:** m5 and m6, plus nits n2 and n7.                                                                   |
| N3  | VERIFIED                | Both AgentTeam.md blocks were run as written under `set -euo pipefail` against the real `main-moved`. Exits 1, 7, 0, 5, 6 and 4 each reached the end, and only 0 moved `main` (`probe_463v5_errexit_out.txt`). See n1 for the Phase 5 fence.                                                                                                                                                                                                                                                     |
| N4  | VERIFIED                | Every double-quoted and nested substitution row is denied, for example `x="$(pytest)"` and `echo "$(echo "$(pytest)")"`.                                                                                                                                                                                                                                                                                                                                                                         |
| N5  | VERIFIED + gaps         | Globs, braces, `eval`, `<<<`, `echo \| bash`, `source` and `time -p` are all handled. Gaps: `script -qc`, `--` after a wrapper, and ANSI-C `\x`/octal (m3, n4); a Python heredoc (m2).                                                                                                                                                                                                                                                                                                           |
| N6  | FIXED, REGRESSED        | Paths outside the repository are right: `pytest <wt>/tests` from `/workspace`, and `pytest <wt>` itself, are both DENIED. But judging every operand as a path broke `llm_qa.py all` after a `cd` (M1).                                                                                                                                                                                                                                                                                           |
| N7  | VERIFIED                | Review 4's nine rows are all caught. So are nine more of mine: `printf %s`, `echo -e`, double spaces, `cd tests && pytest`, `uv run pytest`, backticks, an unquoted `cat <<EOF`, `$SUITE` and an escaped quote.                                                                                                                                                                                                                                                                                  |
| N8  | VERIFIED                | `cd tests/unit/qa && pytest .` and `cd tests/unit/qa && pytest` are allowed. QA.md:275-279 states the rule as policy.                                                                                                                                                                                                                                                                                                                                                                            |
| N9  | VERIFIED                | `xargs` is peeled. Arguments from stdin fail closed (n3).                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| N10 | VERIFIED, no regression | 832 commands went through the whole chain with each regex. There were 132 differences, and every one is a lost deny. 88 are the intended fix: `cat > f` and `git commit -F -` with a blank or punctuated delimiter. The other 44 are one class that already exists on main (m7). Nothing changed for a receiver that executes: `bash`, `cat \| bash`, `$(cat …)`, an opener inside `echo "…"`, or an opener in a comment. The regex is no slower than main's (`probe_463v5_n10_timing_out.txt`). |
| N11 | VERIFIED                | AgentTeam.md:1336 and :1830 use `git branch -d`. QA.md:193-201 names the new parent branch.                                                                                                                                                                                                                                                                                                                                                                                                      |
| N12 | VERIFIED                | The refs are kind-first (`refs/integration/base/integ`). `--finish` deleted both refs in S9c. The range check compares resolved commits (unit tests).                                                                                                                                                                                                                                                                                                                                            |

**The two merges of main.** Both are sound.

- The `llm_qa.py` keep-both in `403e3284` is right (`git show --remerge-diff`).
  `ensure_live_daemon` runs before `run_tool(name, extra)`, and the digest is still taken straight
  after `run_tool`.
- The `test_llm_qa_live_daemon.py` fixture points `QA_OUTPUT_DIR` at `tmp_path`. Its tools are not
  the full set, so `_certify_gate` never runs against the real checkout. The snapshot above
  confirms that nothing under `untracked/qa/` or `refs/integration/` changed.
- `21f5b0f7` merged cleanly.

---

## Major

### M1. N6 regression: `llm_qa.py all` is ALLOWED after any `cd` into a subdirectory

**Where:** `subagent_full_qa_blocker.py` `_operand_is_full` (:1467-1492). `49b4e3dc` introduced it.

`full_args` holds two kinds of entry. `tests`, `tests/unit` and `.` are paths. `all` and `tests`
for `llm_qa.py` are SUBCOMMAND WORDS. Since N6, every operand is resolved from the current
directory and judged against its repository root, and `operand in full_args` is only reached when
no repository is found. So once the command has `cd`'d below the root, `all` resolves to
`<root>/scripts/qa/all`, which is not a full entry. The run is then judged not full.

These are ALLOWED at `5ec9abfa` and DENIED at `bc804523` (`probe_463v5_blocker_extra_out.txt`,
`probe_463v5_regression_bc804523_out.txt`):

- `cd scripts/qa && ./llm_qa.py all`
- `cd CLAUDE && ../scripts/qa/llm_qa.py all`
- `cd tests && ../scripts/qa/llm_qa.py tests`
- `cd docs && python3 ../scripts/qa/llm_qa.py all`
- `./llm_qa.py all` with the event `cwd` in `<wt>/scripts/qa`

`llm_qa.py` finds its `PROJECT_ROOT` from `__file__`, so each of these runs the whole suite.

The verdicts are also inconsistent. `cd /tmp && <wt>/scripts/qa/llm_qa.py all` is still denied,
because no repository contains `/tmp/all`. No test covers `llm_qa.py` below a real repository root:
the `cd` rows in the test file use `/srv/wt`, which has no marker.

**Fix direction.** Match a `full_args` entry literally as a WORD before resolving. Do this when the
operand has no `/`, is not `.`, and names nothing that exists in `here`. Then `.` after a `cd`
(review 4 N8) keeps its resolution. A cleaner option is to split the schema into subcommand words
(`full_words: [all, tests]`, always literal) and path operands. Add the five rows above as RED
tests with a real temporary repository.

### M2. Brace expansion is exponential: a 139-character command takes 18 s, and the hook fails open at 30 s

**Where:** `_expand_braces` (:1506-1532). It builds the full expansion of every alternative
recursively and only then truncates to `_MAX_BRACE_ALTERNATIVES`. The cap bounds the result, not
the work, so the work is 2^n for n groups.

These are the numbers for `pytest {a,b}{a,b}… --co; git status`. The whole chain is run in-process
(`probe_463v5_chain_timing_out.txt`):

| Groups | Main thread | Sub-agent |
| ------ | ----------- | --------- |
| 20     | 0.01 s      | 3.6 s     |
| 22     | 0.00 s      | 10.4 s    |
| 23     | 0.00 s      | 18.4 s    |

The handler alone takes 13.5 s at 22 groups (`probe_463v5_timing_out.txt`). 24 groups is about
37 s, which is past the client's 30 s socket budget.

The budget is the client's. The forwarder's `socket_timeout` path returns a fail-open allow for
PreToolUse (`.claude/init.sh`:1580-1660, and ledger 00466 N25), so the verdict of the WHOLE chain
is lost. Every handler after priority 32 never decides, including the commit gates
(`staged_lint_gate`, `plan_qa_commit_gate`, `docs_qa_commit_gate`, `guard_config_commit_gate`) and
`verification_result_gate`. The executor thread keeps going after the client has given up. At 30
groups that is roughly 40 minutes of GIL-bound CPU in the daemon every other session shares. Only
sub-agent events reach this handler. Nobody types 24 brace groups by accident, but the damage
reaches every guard behind this one.

**Fix direction.** Make `_expand_braces` a generator and take `islice(…, _MAX_BRACE_ALTERNATIVES)`,
so the work is bounded by the cap. An alternative is to count the product of the group sizes first
and, above the cap, judge the operand by its literal prefix, the way `_glob_reach` does. Pin it with
a test that judges 40 groups within a small time budget.

---

## Minor

### m1. The newest change (`5ec9abfa`) denies a `python -c` that only IMPORTS pytest

These are DENIED as full runs (`probe_463v5_blocker_out.txt`, `[pyc]` rows). They are ordinary
environment checks an agent makes:

- `python -c "import pytest; print(pytest.__version__)"`
- `python3 -c 'import pytest' && echo importable`
- `python3 -c "import pytest, sys; print(pytest.__file__, sys.version)"`

`_pytest_in_code` treats any word-bounded `pytest` as a run. With no string literals, the run is
bare, and a bare run from the root is full.

The same logic ignores the arguments after the code. So
`python -c 'import sys, pytest; sys.exit(pytest.main(sys.argv[1:]))' tests/unit/qa` is denied as
bare.

**Fix direction:** judge the code as a run only when it CALLS the runner. That means
`pytest.main(`, `pytest.console_main(`, or a `"pytest"` literal in a process call or after `"-m"`.
Treat the words after the code string as the run's operands when the code passes `sys.argv`
through.

### m2. A Python heredoc runs pytest unseen, which contradicts the rule m1's change adds

These are ALLOWED:

- `python3 - <<'PY'` with `pytest.main(['tests'])` in the body
- `python3 <<'PY'` with `raise SystemExit(pytest.main([]))` in the body

The body is not blanked, because `python3` is not a data sink. It is scanned as shell lines, and
`pytest.main([tests])` is not the program `pytest`. `python -c` with the same code is denied, so the
spelling alone decides.

**Fix direction:** hand a heredoc body fed to a Python interpreter to `_pytest_in_code`, exactly as
a `-c` string is.

### m3. Gaps in the launchers and wrappers the handler claims to follow

All of these are ALLOWED, and bash runs pytest for each (checked):

- `script -qc 'pytest tests' /dev/null`. `-qc` is the usual spelling, and `_resolve_launcher` only
  matches `-c` as a whole word.
- `env -- pytest tests`, `nice -- pytest tests` and `timeout -- 600 pytest tests`. The shared
  `peel_command_wrappers` stops at `--` and returns it as the command word. The table moved from
  `process_probe.py`, and main behaves the same, so this is not a regression.
- `exec -a qa pytest tests`. The `-a` value is taken for the command.

**Fix direction:**

- Find a code flag's letter inside a short cluster in `_resolve_launcher`.
- In `peel_command_wrappers`, skip `--` and continue to the wrapper's positionals.
- Give `exec` a `-a` value flag.

### m4. N1 residual: a NEW pattern in an already-declared glob reader passes the guard

Reproduced in the clone (`probe_463v5_n1_pattern.sh`, `_out.txt`, `probe_463v5_n1_*`):

1. Add `"CLAUDE/Architecture/*.md"` to `DOCUMENT_GLOBS` in
   `test_documented_commands_are_not_self_denied.py`.
2. `test_glob_readers_are_declared.py` still passes (12 passed). The reader FILE is already named
   by a rule.
3. Add a page there with a fenced `curl … -o /tmp/install.sh`. The mapper selects no test
   (`tests: []`, tools `docs_qa`, `plan_qa`), so `main-moved` reads it as docs-only.
4. The reader test FAILS on that tree, naming `CLAUDE/Architecture/StatusLine.md:535`.

QA.md:172-177 then overstates the case: "a `docs-only` or `targeted` landing relies on nothing CI
does". The scanner also sees only `.glob`/`.rglob`/`os.walk`. It does not see `iterdir`,
`os.listdir`, `glob.glob` or a `git ls-files` enumeration. I found no undeclared reader of these
kinds today.

**Fix direction:** for a reader whose globs are a literal constant, have the guard compare that
constant with the reader's declared `path_glob`s. A stronger option is to derive the rules from the
constant. Widen the scanner to the other enumeration idioms.

### m5. N2 residual: `unmoved` names the BRANCH, and `--finish` accepts any descendant of the certified head

`_print_verdict` prints `git merge --ff-only <integration-branch>`, and AgentTeam.md:1287 and :1800
run the same. `finish_batch` only asks whether the certified head is an ancestor of `main`.

S9c (`probe_463v5_n2b_out.txt`):

1. The gate certifies C, and `main-moved` says `unmoved`.
2. A late commit lands on the integration branch. The window is realistic when a teammate merges a
   late child.
3. The documented fast-forward lands that uncertified child on `main`.
4. `--finish` prints "landed on main; the batch refs are removed", which erases the evidence.

**Fix direction:**

- Print, and document, `git merge --ff-only <certified sha>`, so the exact head that passed is what
  lands.
- `--finish` refuses unless the integration HEAD is the certified head, or unless `main` holds no
  commit of the branch beyond it.

### m6. The documented loop runs `llm_qa.py all` twice on the same head

S13 (`probe_463v5_n2b_out.txt`):

1. `main` gains code, and the coordinator merges `main` first. This is what re-running AgentTeam
   STEP 1 after a red batch does.
2. `main-moved` says `head-moved` and prints `llm_qa.py all`.
3. That run passes and certifies the merged head.
4. `main-moved` then says `full-gate` and prints `llm_qa.py all` AGAIN before `--advance`.

`--advance` accepts at once without the second run (S10), because the provenance already covers
the tree. On this repository the second run costs 15-20 minutes, and cutting that kind of repeat
is this plan's purpose. QA.md:163-165 says the loop "never re-runs anything the advanced base
already covers". That is true of the base, but not of this path.

**Fix direction:** when HEAD is the certified head, already contains `main`, and the provenance
satisfies `required_tools(verdict)`, print only `--advance`. Alternatively, let `_certify_gate`
advance the base to `merge-base HEAD main` itself.

### m7. N10 widens an existing false allow: a here-string whose line is read as a heredoc opener

`_QUOTED_HEREDOC_BODY_PATTERN` also matches the tail of `<<<'X'`. Take
`cat <<<'X'`, then a newline, then `git reset --hard HEAD~1`, then a line `X`. The regex blanks the
middle line as a `cat` heredoc body, but bash RUNS it.

On main this already happens for word delimiters (`cat <<<'EOF'` is allowed by both regexes).
N10's charset extends it to every spelling. There are 44 such rows in `probe_463v5_n10_diff.txt`,
across `destructive_git`, `pipe_blocker` and `curl_pipe_shell`. The class is old, and the shape is
not an accident, so this is minor.

**Fix direction:** a `(?<!<)` lookbehind on the opener, in the shared regex N10 already touches.

---

## Nit

- **n1.** The Phase 5 fence (AgentTeam.md:1796-1818) falls through for a non-zero verdict. It goes
  on to the restart, `git push` (of an unchanged `main`) and `--finish`, which refuses and ends the
  script under `set -e`. It is harmless, but add `exit "$rc"` in the non-zero branches, or guard
  the rest of the fence.
- **n2.** S12 (`probe_463v5_n2b_out.txt`): the base advanced, then the branch backed out the merge
  of `main`. After a new gate, `main-moved` says `unmoved` (main == base), but HEAD does not
  contain `main`. `--ff-only` refuses, and the documented response ("run this command again")
  loops. **Fix direction:** `unmoved` should also require `merge-base --is-ancestor main HEAD`.
- **n3.** Some false denies are not documented. A substitution operand (`pytest $(git diff --name-only …)`) reads as a bare `$`, and `env -C tests/unit/qa pytest` ignores the `-C`. The
  `xargs` stdin case is documented. **Fix direction:** list the substitution operand as a limit,
  and treat `env -C` as a `cd`.
- **n4.** HANDLER_REFERENCE:1414 says `$'…'` "is decoded as bash decodes it". `\x74` and octal
  `\164` are not decoded, so `$'py\x74est' tests` is allowed. `function t { pytest; }; t` is
  allowed, while `t() { …; }` is denied. `P=pytest; $P tests` is allowed. The documented limit
  names only substitutions, not variables.
- **n5.** Timing on long commands: `shlex` builds each token character by character, and the
  handler shlex-splits the whole text twice. So a single 400 KB word takes 6.3 s, and 1 MB takes
  36 s, which is past the budget (`probe_463v5_scaling_out.txt`). Realistic commands under 50 KB
  take under 0.3 s. **Fix direction:** add a size cap, above which the handler denies only if a
  declared program is named. Or skip `_code_fed_to_a_shell` when no shell word appears.
- **n6.** About 1000 nested `setsid`, `uv run`, `xargs` or `python -m` raise `RecursionError`.
  `strict_mode` turns that into a SYSTEM ERROR deny, which fails closed. **Fix direction:** a
  depth counter on the runner and launcher recursion.
- **n7.** S4c: a file created and deleted during the run still lets the run certify, because the
  tree before equals the tree after. Record this as a limit.
- **n8.** The N7 guidance test flags
  `echo "  Never run ./scripts/qa/llm_qa.py all in a sub-agent"` as a full run. That is a
  conservative false positive in a test, and acceptable.
- **n9. Outside 463, for the open ledger.** The live chain in `/workspace` denied three commands
  during this review:
  - `grep -n -E "exit (code )?[0-9]|head-moved" f` was denied as R-PIPE-TO-HEAD. It is an
    unescaped `|` inside double quotes, which widens 00466 N32 beyond `\|`.
  - `grep` for the literal text of a force branch-delete was denied as R-GIT-BRANCH-FORCE-DELETE.
  - `cd <clone> && … > ../x.txt` was denied as outside the project. That is 00466 N28.

---

## Verdict

**NOT READY TO MERGE. Fix M1 and M2 first.** Both fixes are small and local to
`subagent_full_qa_blocker.py`, and each needs a RED test.

- **M1** re-opens the plan's own headline command (`llm_qa.py all`) to any sub-agent that `cd`s
  first. It was introduced by the review 4 fix.
- **M2** lets a 140-character sub-agent command run out the client budget, which fails open the
  whole PreToolUse chain.

The rest can follow as ledger items: m1-m7 and n1-n9. m1 and m5 are worth doing with the majors,
because each is a line or two.

The certified-head machinery (N2) held against every attempt:

- certifying a head that did not pass;
- advancing past a non-merge commit, a side-branch merge or an evil merge;
- finishing before landing;
- two racing integrations.

Its gaps are in what it prints (m5, m6), not in what it certifies. N10 changes no verdict for a
receiver that executes its body.
