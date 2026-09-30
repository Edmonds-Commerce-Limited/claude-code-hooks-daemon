# Plan 00463 sixth review: verification of the review 5 fixes (Opus 5.5)

**Scope.** Branch `worktree-plan-463-full-qa-gate` at `01f9ef51`, base `1569d25f`
(`git merge-base main HEAD`). I checked the fixer's "Review 5 fixes" section against review
5's M1, M2, m1 to m7 and n1 to n9, then attacked the new code. The review was read-only.
Nothing tracked was edited or committed, and `git status` in the worktree was clean before and
after. This report is the only new file, and it is uncommitted.

**How it was probed.** Every probe is under `/workspace/untracked/scratch/probe_463v6_*`. Hand-built
payloads carry `synthetic_source: review-463-v6`.

- `probe_463v6_rerun_*.txt`: review 5's own probes, re-run against HEAD (corpus, `cd` rows,
  timing, scaling, chain timing, setup_worktree, N10 regex timing).
- `probe_463v6_blocker.py` and `_out.txt`: a NEW corpus of 279 rows through the configured
  handler with a sub-agent event. The groups are: 75 realistic targeted commands, 63
  fail-closed shapes, 19 `all`/`tests` word rows, 20 brace rows, 10 wrapper-peel rows, 30
  stdin-Python rows, 31 code-file rows, 15 `env -C` rows and 16 git-listing rows. The
  fixtures are in `probe_463v6_fx/`, and `probe_463v6_extra.py` adds single rows.
- `probe_463v6_filebomb.py` and `_out.txt`: the cost of the code-file reader.
- `probe_463v6_chain_timing.py` and `_out.txt`: whole-chain time at 32 KiB and 94 KiB.
  `probe_463v6_chain_main_heredoc.py` compares the same command on `main`.
- `probe_463v6_peel_diff.py` and `_out.txt`: `peel_command_wrappers` before and after
  `01f9ef51`.
- `probe_463v6_n2.sh`, `probe_463v6_n2b.sh`, `probe_463v6_finish.sh`, `probe_463v6_fences.sh`
  and `probe_463v6_loop.sh`, with `_out.txt` files: N2 end to end in a fresh clone of HEAD
  (`probe_463v6_repo`). Tools are faked by `probe_463v6_n2_fake_run.py`, and `main-moved`,
  `--start`, `--advance` and `--finish` are the clone's real code.
- `probe_463v6_m4b.py` and `_out.txt`: the m4 guard reverted in a second clone
  (`probe_463v6_m4repo`, left clean). `probe_463v6_m7.py` covers the here-string lookbehind.

**Targeted tests (no full suite):** 1045 passed. The files were the blocker test, the
shell-segmentation tests (both), `test_process_probe.py`, `test_self_matching_process_probe.py`,
`test_glob_readers_are_declared.py` and `test_llm_qa_main_moved.py`
(`probe_463v6_targeted_pytest.txt`).

**Counts.**

- Review 5 findings: every one is fixed for the shape review 5 reported. M1, m2, m3, m4 and m6
  each have a residual in the same class (below). Review 5's 266-row corpus gives **0 false
  denies and 0 false allows**, and all 12 `cd` rows match.

- New findings: **0 blocker, 2 major, 8 minor, 7 nit.**

- The new corpus has 279 rows (169 expect deny, 110 expect allow):

  - 8 false denies;
  - 54 false allows;
  - 8 denies the documentation accepts as the price of failing closed;
  - 12 allows the documentation names as limits (a script run by its own name, a file over
    64 KiB, a FIFO).

  On the 75 realistic targeted commands, the false-deny rate is **6 of 75 (8%)**. Two of those
  6 are `JUDGED UNSEEN` denies, and 4 more are documented denies.

---

## Review 5, finding by finding

| #   | Verdict             | Evidence                                                                                                                                                                                                                                                 |
| --- | ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | FIXED, residual     | All 12 `cd` rows match (`probe_463v6_rerun_blocker_extra.txt`). Residual: an existing `all`/`tests` in the cwd turns the word back into a path (m1 below).                                                                                               |
| M2  | FIXED               | 24 to 200 groups take 0.4 to 3.5 ms, 2000 nested braces 13 ms, and `{1..100000}` 0.4 ms. Review 5's chain probe: 23 groups take 0.00 s. A NEW unbounded path exists in the file reader (Major M1 below).                                                 |
| m1  | FIXED               | `python3 -c "import pytest; print(pytest.__version__)"` is allowed. `python3 - tests/unit/qa <<'PY' … sys.argv …` is allowed, and `- tests` is denied.                                                                                                   |
| m2  | FIXED, residual     | Python heredocs, here-strings, pipes and `python3 < f.py` are judged. Residual: flag clusters and module aliases (m3 below).                                                                                                                             |
| m3  | FIXED, residual     | `script -qc`, `env --`, `nice --`, `timeout --` and `exec -a` are all denied. Residual: Python `-uc`/`-Ic`/`-Im`, env `-iu`/`-iC` (m3 below).                                                                                                            |
| m4  | FIXED, load-bearing | With the guard at HEAD, review 5's reproduction goes RED (1 failed). With `TestEveryPatternOfAReaderIsDeclared` removed it is GREEN (18 passed) (`probe_463v6_m4b_out.txt`). Residual: 4 of 5 other spellings of the same new directory pass (m5 below). |
| m5  | FIXED               | `unmoved` prints the exact certified sha, and `--finish` refuses a descendant and keeps the refs (N2 section below).                                                                                                                                     |
| m6  | FIXED, residual     | After a full run on a head that holds `main`, only `--advance` is printed. The loop ran `llm_qa.py all` once per head. Residual: `main-moved` called between the merge and `--advance` asks for `all` (m8 below).                                        |
| m7  | FIXED               | `cat <<<'X'` / `<<< 'EOF'` / `<<<"E F"` with a destructive next line are now denied by the whole chain. A real `cat > f <<'EOF'` is still allowed (`probe_463v6_m7_out.txt`).                                                                            |
| n1  | FIXED               | Each fence branch exits with the verdict's code and `main` does not move (`probe_463v6_fences_out.txt`: exits 1, 7, 5, 6 and 4).                                                                                                                         |
| n2  | FIXED               | S12 now says `head-moved` with a "1. git merge --no-edit main" step (`probe_463v6_n2b_out.txt`).                                                                                                                                                         |
| n3  | FIXED, new major    | `env -C` pushes and pops. The listing is targeted, but an EMPTY listing runs the whole suite (Major M2 below).                                                                                                                                           |
| n4  | FIXED               | `$'py\x74est'`, octal, `function t { … }` and variables set in the command are all denied.                                                                                                                                                               |
| n5  | FIXED               | 1 MB takes 0.12 s. A command over 32 KiB goes to a name check. This does not bound file content (Major M1).                                                                                                                                              |
| n6  | FIXED               | 1000 nested `setsid`, `uv run` and `xargs` are denied in 0.03 to 0.1 s with no `RecursionError`.                                                                                                                                                         |
| n7  | FIXED               | QA.md:92 records the created-and-deleted case.                                                                                                                                                                                                           |
| n8  | FIXED               | The guidance test's docstring states it. My re-run: 9 caught, 2 targeted missed, and the one conservative row stands.                                                                                                                                    |
| n9  | Outside 463         | The ledger's 00466 N32, N36 and N28 are open.                                                                                                                                                                                                            |

**Shared `peel_command_wrappers` (no regression).** Every difference from before `01f9ef51` is a
`--` that was returned as the command word and now resolves to the real command
(`probe_463v6_peel_diff_out.txt`), for example `timeout -- 60 pgrep` becomes `pgrep`. That is more
coverage for the process-probe guards, never less. Their tests pass (above). One over-detection is
a nit (n4).

---

## Blockers

None.

## Major

### M1. The code-file reader has no work bound: a 67-byte command takes 312 s in the handler

**Where:** `subagent_full_qa_blocker.py`:

- `_full_run_in_code_file` (:2405-2436) and `_read_code_file` (:2439-2455);
- `_MAX_CODE_FILE_BYTES` (:620);
- the depth-only guard `files_deep >= _MAX_NESTING` (:2422).

The 32 KiB cap (:2327) bounds the COMMAND. A file fed to a shell is read up to 64 KiB and parsed
by `_invocations` with no cap. `files_deep` bounds only the DEPTH of feeds, not their number.
Every feed in the command, and every feed in each file, is read and parsed again. Handler-alone
times (`probe_463v6_filebomb_out.txt`):

| Command                                                        | Length | Handler |
| -------------------------------------------------------------- | ------ | ------- |
| `cat plain64k.sh \| bash` (64 KiB of `#`)                      | 66     | 0.44 s  |
| `cat heredocs64k.sh \| bash` (64 KiB of `cat <<'E'` lines)     | 69     | 3.61 s  |
| `cat plain64k.sh \| bash; ` × 40                               | 2,720  | 14.75 s |
| `cat plain64k.sh \| bash; ` × 80                               | 5,440  | 24.45 s |
| `cat fanout64k.sh \| bash` (a 64 KiB file of 1,300 such feeds) | 67     | 311.7 s |

This is review 5 M2's class. It runs past the client's 30 s budget, whose timeout ALLOWs the
whole PreToolUse chain (ledger 00466 N25), so every guard after priority 32 loses its verdict.
Meanwhile the daemon burns five minutes of CPU. The files take one `Write` to create. The fix for
review 5's "every shape under 1 s" holds for commands, but not for what they feed.

**Reproducer:** `python3 probe_463v6_filebomb.py`, which builds the fixtures in `probe_463v6_fx/`.

**Direction:**

- Give one event a TOTAL byte budget across every file read, so each path is read at most once per
  event. Past the budget, fail closed if the unread bytes name a declared program; a linear
  `_names_program` scan is cheap.
- Apply the 32 KiB parse cap to file content as it applies to the command.
- Pin it with a test: the fanout file judged within 1 s.

### M2. An empty changed-files listing runs the whole suite, and the handler reference calls it targeted

**Where:** `_is_a_listing`/`_consumers_of_a_listing` (:1300-1344) and `_is_full_run`
(:2277-2281). HANDLER_REFERENCE.md:1425 documents both forms as targeted.

These are ALLOWED:

- `git diff --name-only | xargs pytest`
- `git diff --name-only main -- tests | xargs pytest`
- `pytest $(git diff --name-only -- tests)`

GNU `xargs` runs its command once on empty input. I checked this: `printf '' | xargs echo RAN`
prints `RAN`. An empty substitution leaves a bare `pytest`. Both are the whole suite from the
root. The realistic trigger is ordinary:

- a sub-agent commits its work and then runs `git diff --name-only | xargs pytest`, which lists
  nothing; or
- its branch changed no test file, so `main -- tests` is empty.

This is the accident the handler exists to stop, reached through a form its own reference
recommends. `xargs -r`/`--no-run-if-empty` is also allowed, and there it is safe.

The listing can also be steered to name the suite. These are deliberate, and the handler is "not a
security boundary", so they belong to the same fix rather than to a separate finding. Each of these
is ALLOWED and runs `tests` or every file:

- `git log --name-only --format=tformat:tests -1 | xargs -r pytest`
- `git diff --name-only --line-prefix='tests ' HEAD~1 | xargs -r pytest`
- `git diff --name-only 4b825dc6… -- tests | xargs -r pytest` (the empty tree)
- `git log --name-only --format= | sort -u | xargs -r pytest`

**Direction:**

- Count an `xargs` consumer as targeted only with `-r`/`--no-run-if-empty`.
- Count `$(listing)` as targeted only beside at least one literal target. Otherwise it is judged
  as possibly empty, which is bare.
- Refuse a listing whose git words carry `--format`/`--pretty`/`--line-prefix`/`--output`.
- Correct HANDLER_REFERENCE.md:1425 to show `xargs -r`.
- Add RED rows for the three empty forms.

---

## Minor

### m1. M1 residual: `llm_qa.py all`/`tests` is ALLOWED when the cwd holds something of that name

**Where:** `_is_subcommand_word` (:2144-2154). This is the heuristic review 5 itself suggested.
For `llm_qa.py` the words are never paths, so an existing name makes the check read the word as
one. `.claude/hooks/handlers/pre_tool_use/tests` exists in this repository, so no setup is needed.
Each of these is ALLOWED, and each runs the whole suite:

- `cd .claude/hooks/handlers/pre_tool_use && ../../../../scripts/qa/llm_qa.py tests`
- the same with `python3`, or with the event `cwd` there;
- in the clone, once `scripts/qa/all` or `CLAUDE/all/` exists: `cd scripts/qa && ./llm_qa.py all`
  and `cd CLAUDE && ../scripts/qa/llm_qa.py all`.

The `.claude/.../pre_tool_use && pytest tests` rows are correctly targeted.

**Direction:** review 5's cleaner option. A per-pattern `full_words` list (`llm_qa.py: [all, tests]`) is always literal. The `full_args` paths (pytest's `tests`) keep the existence check.

### m2. Code a shell reads that the handler cannot see is ALLOWED, not failed closed

**Where:** `_producer_output` (:1375-1387), `_code_on_stdin` (:1390-1419) and `_fed`
(:1422-1437). HANDLER_REFERENCE.md:1418 says "What cannot be seen fails closed". Only
`echo`/`printf` and a single-operand `cat` are understood. Each of these is ALLOWED, and bash runs
`pytest tests` (the fixture is `probe_463v6_fx/small.sh`):

- `cat f g | bash`, `cat < f | bash`, `< f cat | bash`, `cat f | tee /dev/null | bash`;
- `awk 1 f | bash`, `grep . f | bash`, `tac f | bash`;
- `bash -c "$(cat f)"`, `eval "$(cat f)"`;
- `echo 'pytest tests' | bash /dev/stdin`, `bash /dev/stdin <<< 'pytest tests'`,
  `source /dev/stdin <<< …`;
- `bash <(echo pytest tests)` and `. <(echo pytest tests)`. The handled `bash < <(echo …)` is the
  same thing.

A file changed by the same command is read in its OLD state.
`echo 'pytest tests' > small_tgt.sh; bash < small_tgt.sh` is allowed, because the check read the
targeted content. A file over 64 KiB, or a FIFO, is judged by name. That is documented at :1411,
but it contradicts :1418.

**Direction:**

- A shell or Python reading code from stdin whose producer is not understood is unseen. Deny it
  with `JUDGED UNSEEN`.
- Treat `/dev/stdin`, `/dev/fd/N` and a `<(...)` operand as stdin.
- Treat a path the same command writes (`>`, `>>`, `tee`) as unseen.
- For an unread file, fail closed on a bounded `_names_program` scan instead of trusting the name.

### m3. Flag clusters and aliases still hide pytest

These are ALLOWED:

- `python3 -uc 'import pytest; pytest.main(["tests"])'` and
  `python3 -Ic 'import pytest; pytest.main()'`. In `_resolve_python` (:1919-1928) only a LEADING
  `-c`/`-m` is recognised. `-Im pytest` is denied by accident: `pytest` is taken as a script, whose
  name matches. `python3 -Im coverage run -m pytest tests` is allowed.
- `python3 -c 'import pytest as p; p.main()'`, `from pytest import main as m; m()` and
  `import _pytest.config as c; c.main()`. `_PYTEST_CALLS` (:670) matches only the literal
  `pytest.main(`.
- `env -iu HOME pytest tests`, `env -iC tests pytest` and `env - pytest tests`. In the shared
  peel (`shell_segmentation.py`:433-449), a short cluster ending in a value flag does not take its
  value, and a lone `-` is `-i` for env. `-iu` is older than this branch. `-iC` is the branch's
  new `env -C` support meeting the same gap.

**Direction:**

- Parse short clusters letter by letter: for Python, `c`, `m`, `W` and `X` take the rest or the
  next word; do the same for a wrapper's value flags.
- Track `import pytest as NAME` and `from pytest import main as NAME`.
- Treat `-` as `-i` for env.

### m4. pytest's own argument channels are not read

These are ALLOWED:

- `PYTEST_ADDOPTS=tests pytest tests/unit/qa` and `export PYTEST_ADDOPTS=tests; pytest …`;
- `pytest tests/unit/qa @args.txt` (pytest 8.2 argument files).

With the venv's pytest 9.0.3, both collected `tests/other` beside the target
(`probe_463v6_pyt`, 2 passed). **Direction:** judge a `PYTEST_ADDOPTS` value's words as operands,
and treat an `@file` operand as built at run time, which is full.

### m5. m4 residual: four other spellings of the same new directory pass the guard

`undeclared_patterns` sees only literal root-relative constants that contain `/`. In the
already-declared documented-commands reader, review 5's literal `"CLAUDE/Architecture/*.md"` is
CAUGHT. These four are MISSED (`probe_463v6_m4b_out.txt`, part 2b):

- `(PROJECT_ROOT / 'CLAUDE' / 'Architecture').glob('*.md')`
- a `PROBE_DIR = 'CLAUDE/Architecture'` constant, then `.glob('*.md')`
- an f-string pattern
- a concatenated pattern

The scanner (part 2a) also misses these readers:

- the argv of `git ls-files` held in a variable or split from a string;
- a suffix built by concatenation;
- a glob method through an alias;
- `Path.walk`;
- a root from `os.getcwd()` or `pytestconfig.rootpath`;
- `sorted(Path(__file__).parents[2].rglob('*.md'))`.

The first of the four missed spellings above is the natural one.

**Direction:** resolve a glob call's receiver path, whether joined or held in a constant, to a
root-relative directory. Compare `directory/pattern` with the rules, not only whole literal
patterns.

### m6. Realistic false denies, two of them one-line fixes

These are 6 of the 75 realistic rows:

- `./scripts/qa/llm_qa.py changed --range "$(git merge-base main HEAD)..HEAD"` and
  `changed --range $BASE..HEAD` are DENIED as full runs, with no `JUDGED UNSEEN` line.
  `llm-qa-whole-suite` (`.claude/hooks-daemon.yaml`:463) has no grammar, so the range value is
  read as a run-time operand. **Fix:** `value_flags: [--range]`.
- `"$PY" -c "print(1)" && pytest tests/unit/qa/x.py` is DENIED `JUDGED UNSEEN`, and
  `$EDITOR notes.txt; pytest tests/unit/qa` likewise. The unset `"$PY"` is judged as pytest
  because the command names pytest, and pytest's `-c` consumes `print(1)`, leaving a bare run
  (:2388-2398). **Direction:** judge an opaque word as a declared program only when its REST
  would also be that program's arguments. At the least, skip it when the rest starts with
  `-c`/`-m` code, which is an interpreter.
- `pytest 'tests/unit/test_config_loader.py::test_x[case-1]'` is DENIED. The `[` of a
  parametrised node id is read as a glob reaching `tests/unit` (:2216-2232). Brackets after `::`
  are not a path glob.
- `pushd tests/unit/qa && pytest -q; popd` is DENIED, because `pushd`/`popd` are not followed as
  `cd`.

### m7. Brace sequences and default expansions pass unexpanded

- `pytest tests/unit/qa {t..t}ests` and `./scripts/qa/llm_qa.py a{l..l}l` are ALLOWED. Bash makes
  `tests` and `all` of them. `_brace_alternatives` (:2181-2204) expands only comma groups, so a
  sequence stays literal and is ignored as a non-path. **Direction:** treat an operand holding
  `{x..y}` as unseen, which is full, or expand small single-character or numeric sequences.
- `RUNNER=${RUNNER:-pytest}; $RUNNER` is ALLOWED. The command word `${RUNNER:-pytest}` is opaque,
  and `_names_program`'s lookbehind (:2460) excludes the `-` before `pytest`. It is a common script
  idiom. **Direction:** read `${NAME:-word}`/`${NAME:=word}` as `word`.

### m8. m6 residual: `main-moved` between the merge of main and `--advance` asks for a full run

`probe_463v6_loop_out.txt` L3: `main` moves a doc and the verdict is `docs-only`. The coordinator
merges `main` and passes the docs recheck, then re-runs `main-moved` before `--advance`, after a
compaction or to check. It gets `head-moved` and `1. ./scripts/qa/llm_qa.py all`, which is 15-20
minutes that the recheck already covered. `_head_uncertified` (`llm_qa.py`:1712-1726) sees only
that HEAD is not the certified head. **Direction:** when every commit past the certified head is
a merge of `main` that `_only_main_merged` would accept, return the main-moved verdict with its
recheck, not `head-moved`.

---

## Nit

- **n1.** `_repository_root` (:2092-2098) raises `OSError` (ENAMETOOLONG) for an operand with a
  component over 255 bytes, for example `pytest tests/unit/qa/xxx…(300).py`. Strict mode makes
  that a SYSTEM ERROR deny, not a verdict. `_is_subcommand_word` already catches `OSError`, and
  this should too.

- **n2.** The brace-cap denies (over 64 alternatives or 32 groups) and the run-time-operand denies
  carry no `JUDGED UNSEEN` line. The brace cap is not in HANDLER_REFERENCE.md.

- **n3.** `_merges_exactly` (`llm_qa.py`:2064-2075) accepts any commit with the certified head
  among its parents and the certified tree. That includes a same-tree NON-merge child, an octopus
  and a merge with an unrelated branch (`probe_463v6_finish_out.txt`). The content is identical,
  so this is harmless, but the docstring and the refusal say "a merge of it".

- **n4.** The peel now resolves `timeout 60 -- pgrep` to `pgrep`. GNU `timeout` stops option
  parsing at its first operand, so there `--` is the command. The error is in the harmless
  direction.

- **n5.** Deliberate obfuscations that are still allowed, consistent with "not a security
  boundary":

  - `alias` under `expand_aliases`, `hash -p` and `coproc pytest tests`;
  - `P=$(printf 'py%s' test); $P tests`;
  - `subprocess.call(["py" + "test"])`;
  - a nested `env -C a env -C ../.. pytest`, where the first `-C` wins in `_env_directory`
    (:1504-1520).

  List them among the documented limits.

- **n6.** Outside 463, for the ledger (00466 N25/N34 already track it): the whole chain takes 52 s
  on the MAIN thread for 94 KiB of `cat <<'E'` openers. It is the same on `main` (51.7 s) and on
  this branch (52.0 s) (`probe_463v6_chain_main_heredoc_out.txt`).

- **n7.** The documentation offers `pytest tests/unit/**/…` only as a full deny. It is fine by
  design, but it is 1 of the 4 documented denies in the realistic corpus. A one-line note of the
  narrower spelling would save a retry.

---

## N2 end to end (fresh clone of `01f9ef51`)

All of this is from `probe_463v6_{n2,n2b,finish,fences,loop}_out.txt`.

- **`unmoved` prints the certified sha.** S5, S10 and B1: `git merge --ff-only <40-char sha> (the certified head of integ)`, equal to `refs/integration/certified/<branch>`.

- **`--finish` accepts only that head, or a same-tree merge.**

  | What landed on `main`                                                | `--finish`      |
  | -------------------------------------------------------------------- | --------------- |
  | The certified head                                                   | accepted        |
  | A merge with the certified head as first or second parent, same tree | accepted        |
  | An uncertified child                                                 | refused, exit 1 |
  | An evil merge                                                        | refused         |
  | A same-tree grandchild                                               | refused         |
  | A late commit plus its revert                                        | refused         |
  | Nothing landed                                                       | refused         |

  The refusal names the sha to land. A same-tree non-merge child, an octopus and a same-tree
  unrelated merge are accepted (n3).

- **An uncertified late commit cannot land.** S9b/S9c: fast-forwarding by the branch NAME lands
  it, and `--finish` then REFUSES and keeps both refs. The AgentTeam.md fences run as written
  under `set -euo pipefail`:

  - with a late commit before the fence, `main-moved` exits 7 and `main` does not move;
  - with the late commit racing in between `main-moved` and the fast-forward, the fence lands
    the certified sha (`c575f3a9`), not the branch head (`2f2529cb`).

- **The batch refs are not erased early.** Both refs survived every refused `--finish`, and were
  removed only by an accepted one.

- **One `llm_qa.py all` per head.** L1, L2, L2b and S13 each reached `unmoved` in 2 rounds, and the
  run log has every head exactly once. S13 now prints only `--advance` after the full run. S10's
  race is correct: after A lands, B is refused a fast-forward, merges, runs once and advances.
  The one extra run is m8's off-script call.

## QA exclusions and gate dodges

`git diff 1569d25f..HEAD -- '*exclusions*' '*.yaml'` touches:

- no exclusions file;
- `.claude/hooks-daemon.yaml` (the handler's config);
- the release config-changes manifest;
- `changed_tests_map.yaml` (new mapper rules);
- `declared-invariant-pairs.yaml`, re-pointed from `process_probe._WRAPPERS` to
  `COMMAND_WRAPPERS` after the table moved.

The review 5 fix diff (`5ec9abfa..HEAD`) adds no `noqa`, `type: ignore`, `nosec` or `pragma`. The
branch's three `nosec` comments in `run_changed_tests.py` date from `a1fff052` and follow the
repository's justified-`nosec` convention. The test constants `"os." + "system"` and
`"__imp" + "ort__"` (`test_subagent_full_qa_blocker.py`:95-96) are split test data. That has
precedent in `test_security_antipattern.py`:685-974, and I do not count it as dodging a QA gate. I
found no code restructured to satisfy a gate.

## Timing

**Handler alone.**

- Review 5's timing probe: slowest row 0.136 s. Its brace rows take 0.001 s.
- The new corpus: slowest 0.39 s (a 64 KiB file read). Brace rows take at most 13 ms.
- The file reader is not bounded: 3.6 s for one file and 312 s for a fanout (Major M1).

**Whole chain, in-process** (`probe_463v6_chain_timing_out.txt`). Each cell is main thread /
sub-agent. The sub-agent chain adds the blocker, whose share is at most about 0.6 s.

| Shape                       | 32 KiB − 1    | 32 KiB + 1    | 94 KiB        |
| --------------------------- | ------------- | ------------- | ------------- |
| pytest path operands        | 0.92 / 1.31 s | 0.64 / 0.39 s | 1.89 / 0.90 s |
| echo words chained          | 0.84 / 1.32 s | 0.77 / 0.98 s | 3.52 / 3.46 s |
| brace operands              | 0.63 / 1.30 s | 0.75 / 0.38 s | 1.72 / 1.11 s |
| double-quoted substitutions | 0.74 / 1.23 s | 0.94 / 0.82 s | 2.00 / 2.26 s |
| subshell parens             | 0.72 / 0.95 s | 0.85 / 0.80 s | 2.13 / 2.04 s |
| quoted heredoc openers      | 10.4 / 11.9 s | 8.3 / 8.3 s   | 64 / 55 s     |

The heredoc row is the chain's other handlers, and it is the same on `main` (n6).

---

## Verdict

**NOT READY.** Fix the two majors first. Both are local to `subagent_full_qa_blocker.py` and its
reference page, and each needs a RED test.

- **M1** re-opens review 5 M2's failure mode, a sub-agent command that runs out the client budget
  and fails open the whole chain. It does so through the new code-file reader, from a 67-byte
  command.
- **M2** lets the handler's own documented targeted form (`git diff --name-only | xargs pytest`)
  run the whole suite whenever the listing is empty. That is the ordinary state just after a
  commit.

The certified-head machinery (N2) held against every attempt, and every review 5 finding is fixed
for the shape it reported. m1 (`full_words`) and m6's `--range` value flag are each a line or
two, and worth doing with the majors. The other minors and the nits can go to the ledger.
