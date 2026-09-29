NOT READY

# Plan 00463 ninth review: the review 8 fixes, and the fixer's four open items (Opus 5.5)

**Scope.** Branch `worktree-plan-463-full-qa-gate` at `50741c610`. Review 8 was at `aae6c33b`. I read
review 8, the fixer's round 9 report and `git diff aae6c33b..HEAD` (22 commits), then ran the code.
Nothing tracked was edited or committed, and no daemon was restarted. This report is the only new
file in the worktree, and it is uncommitted.

**The binding principle used throughout:** anything the handler cannot fully judge within budget is
DENIED, and it never narrows or blanks what it reads.

**Probes.** All are under `/workspace/untracked/scratch/probe_463r9_*`.

- `probe_463r9_lib.py` judges a command two ways. In-process, it calls the configured handler's
  `_find()` on a sub-agent event (`synthetic_source: review-463-r9`). Through the daemon, it sends
  the event to the worktree's RUNNING daemon via `.claude/hooks/pre-tool-use --no-relay`, with no
  synthetic marker (session `review-463-r9-session`). In the daemon route only `R-SUBAGENT-FULL-QA`
  counts as this handler's deny. A forwarder budget message counts as TIMEOUT.
- The evasion corpus is `probe_463r9_fn.py`, with its output in `_fn_out.txt` and fixtures in
  `probe_463r9_fx/`.
- The everyday corpus is `probe_463r9_fp.py`, with its output in `_fp_out.txt`.
- The budget probes are `probe_463r9_budget.py` and `_budget2.py`, with their `_out.txt` files.
- The item 4 probe is `probe_463r9_yield.py`, with its output in `_yield_out.txt`.
- The execute-bit probe is `probe_463r9_modes.py`, and the probe of oversized repository scripts is
  `probe_463r9_bigrepo.py`.
- The run_changed_tests selection is in `probe_463r9_rct_select.json`.
- The merge result is `probe_463r9_mergetree.txt`, with its copy in `probe_463r9_merged/` and its
  test run in `probe_463r9_merged_pytest.txt`.
- Review 8's rows re-run at HEAD are in `probe_463r9_r8fn_out.txt`, `_r8fn_daemon_out.txt` and
  `_r8fp_out.txt`.

## Counts

- **2 blockers, 7 majors, 5 minors, 4 nits.**
- **Review 8's corpora are clean at HEAD.**
  - The false-negative corpus is 114 of 114 correct in-process and 114 of 114 through the daemon.
  - The everyday corpus is 203 of 203 allowed both ways.
  - The fixer's corpus claims are TRUE.
- **New evasion corpus: 206 rows, 202 of which must deny. 81 of those 202 are ALLOWED** in-process,
  and all 81 are allowed by this rule through the daemon. Five of the 81 were denied in the daemon
  run by a different handler (`project_containment`), because the fixtures sit outside the worktree.
  Inside the tree, those five are allowed too.
- **New everyday corpus: 64 commands, 63 allowed.** The one deny is `bash -n scripts/qa/run_tests.sh`
  (m1).
- **Targeted tests at HEAD:** 1505 passed. They cover the blocker, the corpus,
  `test_audit_error_hiding`, `test_path_predicates`, `test_setup_worktree_qa_guidance` and
  `test_shell_segmentation`.
- **Full gate:** see "Full gate" at the end.

## Review 8, finding by finding

| #      | Verdict            | Evidence                                                                                                                                                                                                                                                                                                   |
| ------ | ------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1     | FIXED              | 200 references to a 32 KiB script that reads `"$1"`, each with a new argv, DENY `too-much-code-to-judge`: 0.22 s in-process and 0.53 s through the daemon. The heredoc-opener variant also denies, but took 6.0 s in-process and **12.2 s** through the daemon, not the 3.90 s the fixer reports (see M7). |
| M1     | FIXED              | All the Python variable, constant, dict and return-value rows deny (review 8 corpus, `py` group, 31 rows).                                                                                                                                                                                                 |
| M2     | FIXED as described | A large file is scanned raw with nothing blanked. The raw scan only NAMES programs, though, so what an oversized file RUNS is never read (B2).                                                                                                                                                             |
| M3     | FIXED              | All 19 environment-setup rows deny, in-process and through the daemon.                                                                                                                                                                                                                                     |
| M4a-d  | FIXED              | The guidance test and the pyright error are gone. No wall-clock assert is left in the blocker tests (checked below).                                                                                                                                                                                       |
| m1     | PARTLY             | `$(cat f)` and backticks as the command word deny. `$(<f)` as the command word is still allowed (M6).                                                                                                                                                                                                      |
| m2, m3 | FIXED              | Corpus rows pass.                                                                                                                                                                                                                                                                                          |
| m4     | FIXED              | The assertion is restored and the limiter is per calling site.                                                                                                                                                                                                                                             |
| m5     | FIXED              | Renumbered.                                                                                                                                                                                                                                                                                                |
| n1-n4  | FIXED as described | n4 closed only `iter(())`. Twelve other shapes still pass (m2).                                                                                                                                                                                                                                            |

---

## Blockers

### B1. A script path built by a substitution is "absent", so it is allowed unread. This is item 1, and it is wider than the script-directory idioms.

**Where.** In `_read_code` (`subagent_full_qa_blocker.py:4462-4468`), a path that starts with `$` or
a backtick gets these verdicts:

- `_LEADING_VARIABLE` does not match `$(` or a backtick, so the path returns `_ABSENT_CODE`.
- A variable the code assigns anywhere also returns `_ABSENT_CODE`.
- `_full_run_in_code_file` (`:4288`) turns ABSENT into `return None`, which allows the command.

**Reproduced** (`probe_463r9_fn_out.txt`, group `sdir`). Each of these is ALLOWED in-process and
through the daemon. The file `full.sh` holds `pytest tests`.

- These top-level commands need no script-directory idiom and no helper file:
  - `bash "$(echo /abs/fx)/full.sh"`
  - `` bash `echo /abs/fx`/full.sh ``
  - `bash "$(realpath /abs/fx)/full.sh"`
  - `bash "$(readlink -f /abs/fx)/full.sh"`
  - `bash "$(cd /abs/fx && pwd)/full.sh"`
- These scripts, each run as `bash <script>` (and one directly as `./sd_dirname.sh`):
  - `sd_dirname.sh`: `bash "$(dirname "${BASH_SOURCE[0]}")/full.sh"`
  - `sd_scriptdir.sh`: `SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"`, then
    `bash "$SCRIPT_DIR/full.sh"`
  - `sd_dollar0.sh`: `bash "$(dirname "$0")/full.sh"`
  - `sd_realpath.sh`: `HERE="$(realpath "$(dirname "$0")")"`, then `"$HERE/full.sh"`

**These shapes DENY at HEAD:**

- `${BASH_SOURCE[0]%/*}/full.sh`, because the variable is not assigned, so the path is UNSEEN;
- `X=/abs/full.sh; bash "$X"`;
- `D=/abs; bash "$D/full.sh"`.

So `${BASH_SOURCE[0]%/*}` already fails closed, while `$(dirname "${BASH_SOURCE[0]}")`, which means
the same thing, fails open.

**Quantified.**

- In this repository, 62 tracked shell files use `dirname` on `${BASH_SOURCE}` or `$0`, 42 assign
  `SCRIPT_DIR=`, and 3 use `BASH_SOURCE[0]%`. There are 109 shell files in all.
- Hiding `pytest tests` takes one `Write` of a two-line script, or no script at all (the five
  commands above).

**Is "absent" a fail-open? Yes.** Absent is correct only for a path that provably names nothing:
missing, or a directory, as `_read_new` decides. A path the handler could not COMPUTE is not a path
it proved empty.

**The plan to adopt Plan 464's resolver.** Sharing one resolver is sound as consolidation. It is not
sound as a reason to ship this gap, for three reasons:

1. 464's resolution is not on its branch yet. `worktree-plan-464-commit-gate-repo` is at `768d98b54`,
   and its working tree has one uncommitted modified test file. The resolver cannot be judged against
   code, and 463 would ship with the gap in the meantime.
2. The gap is wider than the idioms 464 resolves. `$(echo …)`, `$(realpath …)` and any assigned
   variable are also ABSENT. Resolving the idioms leaves the rest open unless the fallback changes.
3. 464 is a commit gate. What its resolver returns when it cannot resolve must be three-valued
   (resolved, cannot-resolve, provably-nothing). For 463, cannot-resolve must map to UNSEEN, which
   denies.

**Direction.**

- Now, in 463: a path led by a substitution, a backtick, or a variable the code assigns becomes
  UNSEEN, not ABSENT.
- Resolve only the fixed idioms, as "the directory of the file being read" (or of the command's
  cwd at the top level):
  - `$(dirname "${BASH_SOURCE[0]}")`, `$(dirname "$0")` and `$(cd "$(dirname …)" && pwd)`;
  - `${BASH_SOURCE[0]%/*}`;
  - `$(realpath|readlink -f <literal>)`;
  - a `NAME=` assigned exactly once to one of those.
- Put that behind a function with the signature 464 will expose, and swap it for 464's when 464
  lands.
- The fixer's `untracked/scratch/p463r9_script_dir_attempt.patch` already covers most of this. The
  4 everyday commands it still denied (`run_semgrep_check.sh`, `run_canonical_callers_check.sh`,
  `install_version.sh`, `dummy-client-repo.sh`) are cases the principle says to deny. Those are
  QA or installer scripts that a sub-agent reaches through `llm_qa.py <tool>`, not directly.
- Pin every row above as RED.

### B2. Past the caps, the raw scan allows code that RUNS other code, which is then never read. This is item 2.

**Where.**

- **A command over 32 KiB.** `find_full_qa_invocation:4003-4008` returns None unless the command's
  own text names a declared program.
- **A shell file over 32 KiB, or Python over the 96 KiB meter.** `_full_run_in_code_file:4299` goes
  to `_scanned_verdict:4366-4380`, which likewise denies only on a declared name.
- In both cases, a script, a `source`, a `bash -c` or a Python `subprocess.run([...])` inside the
  oversized text is never followed.

**Reproduced** (`probe_463r9_fn_out.txt`, group `cap`; `probe_463r9_budget_out.txt`, row
`cmd-cd`). Each of these is ALLOWED in-process and through the daemon, and each runs `pytest tests`
through `full.sh` or `chain11.sh`:

- `bash big_ref.sh`: 36 KB of comments, then `bash /abs/full.sh`;
- `python3 big_ref.py`: 105 KB, then `subprocess.run(['bash', '/abs/full.sh'])`;
- `bash /abs/full.sh # xxx…` (33,059 bytes);
- `: 'xxx…'; bash /abs/full.sh` (33,062 bytes);
- `echo xxx… && python3 /abs/full_py.py` (33,071 bytes);
- `cd d0 && … && cd d2999 && bash /abs/chain11.sh` (34,950 bytes; daemon 1.10 s, ALLOW).

**Answer to item 2.** Past the cap the handler raw-scans, so it does not allow unread TEXT. But it
does allow unread CODE: every file the oversized text runs. That breaks "never allow unread".

**Cost of failing closed.**

- 4 tracked shell files are over 32 KiB: `init.sh`, `scripts/install/venv.sh`, `scripts/upgrade.sh`
  and `scripts/upgrade_version.sh`. All 4 are allowed today (`probe_463r9_bigrepo_out.txt`), and
  none names a declared program.
- The only Python file over 96 KiB is `llm_qa.py`, which is declared, so its pattern judges it.
- None of those 4 shell files is a sub-agent's everyday command.

**Direction.**

- Past a cap, DENY with reason "too large to judge" unless the raw text holds no construct that runs
  code. That means no shell/interpreter/`source`/`.`/`eval`/`exec` word, no path-run word
  (`./`, `/…`), and no `subprocess`/`os.`/`pty`/`runpy` in Python.
- Raising the shell cap after Plan 00466 N38/N41 lands then only reduces false denies.
- Pin all six rows above.

## Majors

### M1. `run_changed_tests.py` is an exemption, not a declaration. This is item 3.

**Where.** The dogfood YAML declares `run-changed-tests` with `full_words: []`. A declared program is
judged only by its pattern, never read (`_full_run_in_code_file:4285-4286`), so no invocation of it
is ever full.

**Reproduced.**

- `python3 scripts/qa/run_changed_tests.py --range 4b825dc642cb6eb9a060e54bf8d69288fbee4904..HEAD --select-only`
  (the empty tree to HEAD) selects **1,062 of the repository's 1,124 test files**, with 457 unmapped
  (`probe_463r9_rct_select.json`).
- `_verdict` runs `run_pytest(selection.selected, …)` whatever the unmapped count is; unmapped files
  only change the pass/fail verdict afterwards (`run_changed_tests.py`, `_verdict`).
- So these three commands are ALLOWED in-process and through the daemon, and run 94% of the suite:
  - `python3 scripts/qa/run_changed_tests.py --range 4b825dc6…..HEAD`
  - `./scripts/qa/run_changed_tests.py --base 4b825dc6…`
  - `./scripts/qa/llm_qa.py changed --range 4b825dc6…..HEAD`
- `MAX_IMPORT_SELECTION = 40` caps one file's reach, not the total.

**Direction.**

- Make the script refuse, and run nothing, when the TOTAL selection passes a declared bound. A
  measured fraction such as 25% of the test files is one option. It should report that as "the full
  suite by another name", as it already does per file.
- Pin the empty-tree range as RED.
- The handler's declaration can then stay as it is, because the script enforces the bound.

### M2. A file rewritten or re-moded in the same command by anything but `>`, `>>` or `tee` is judged from its old contents on disk

**Where.**

- `_written_paths` (`:1515-1522`) knows only redirects and `tee`.
- `_MODE_CHANGERS` (`:736-738`) lists `cp`, `mv`, `install`, `ln`, `rsync`, `tar` and `unzip` as
  things that change an execute BIT, but not as things that change CONTENT.
- The no-execute-bit shortcut (`:4292-4295`) trusts that bit whenever no listed program came first.

**Reproduced** (`probe_463r9_fn_out.txt`, group `write`; `probe_463r9_modes_out.txt`). In the
rewrite rows the target file holds `pytest tests/unit/qa` on disk, and the command replaces it with
`pytest tests` before running it. Every row is ALLOWED in-process:

- `cp full.sh w.sh; bash w.sh`
- `install full.sh w.sh; …` and `dd if=full.sh of=w.sh; …`
- `rsync full.sh w.sh; …` and `mv full_src.sh w.sh; …`
- `ln -sf full.sh w.sh; bash w.sh`
- `patch -d fx -p0 < full.patch; bash fx/w.sh`
- `python3 -c "open('w.sh','w').write('pytest tests')"; bash w.sh`
- A 0644 file holding `pytest tests`, made executable by
  `python3 -c "import os; os.chmod(f, 0o755)"; ./f` or `perl -e 'chmod 0755, "f"'; ./f`. The same
  with `chmod +x` or `bash -c 'chmod +x f'` DENIES.

**Direction.**

- A path is unseen when any earlier segment of the command could have written it. That covers any
  word naming it (or its directory, for `patch -d`/`tar -C`) in a segment that is not provably
  read-only.
- Apply the same test to the execute bit: honour "no execute bit" only when every earlier segment is
  a known read-only program.

### M3. Code for an interpreter the handler does not read is allowed unread

**Where.**

- `_code_kind` (`:4383-4402`) returns None for a `#!` naming any other interpreter, and for a
  binary. `_full_run_in_code_file:4297-4298` turns None into an allow.
- `env` in a `#!` line drops flags but not `VAR=value` words.
- `perl`, `node`, `ruby`, `awk`, `busybox` and `fish` code on the command line is not read at all.

**Reproduced** (group `interp`). All 16 rows are ALLOWED in-process and through the daemon:

- Scripts run by path (0755):
  - `#!/usr/bin/perl` with `system('pytest tests')`;
  - `#!/usr/bin/env node` with `execSync`;
  - `#!/usr/bin/ruby`;
  - `#!/usr/bin/awk -f` with `BEGIN{system(…)}`;
  - **`#!/usr/bin/env -S VAR=1 bash` with `pytest tests`**. This is a shell script, misread as
    interpreter `VAR=1`.
  - **`#!/usr/bin/env -S uv run --script`**, a Python script;
  - a NUL-bearing binary holding `pytest\0tests`.
- `perl f.pl` and `node f.js`.
- Inline code: `perl -e 'system("pytest tests")'`, `node -e '…execSync("pytest tests")'`,
  `ruby -e …`, `awk 'BEGIN{system("pytest tests")}'` and `gawk …`.
- Other shells: `busybox sh -c 'pytest tests'` and `fish -c 'pytest tests'`.

**Direction.**

- For code the handler does not parse, apply the fail-closed raw scan it already uses for oversized
  files: DENY when the text names a declared program. That covers other interpreters' files,
  binaries, and `-e`/`-c`/awk program text.
- Parse a `#!/usr/bin/env -S` line the way `env` does: skip `NAME=value` words and flags.
- Treat `uv run --script` (and `uv run python`) as Python.
- Add `busybox sh`/`ash` and `fish` as shells, or scan them.

### M4. Python reaches code the handler does not read

**Reproduced** (group `pyc`). All ALLOWED in-process and through the daemon; each target runs
`subprocess.run(['pytest', 'tests'])`:

- `PYTHONPATH=fx python3 -m fullmod` and `cd fx && python3 -m fullmod`. `-m` of a LOCAL module is
  not resolved against the cwd or `PYTHONPATH`.
- `python3 fx/pkgdir`. Python runs `pkgdir/__main__.py`, but `_read_new:4501-4502` calls a
  directory ABSENT.
- `python3 -c "exec(open('fx/full_py.py').read())"` and
  `python3 -c "import runpy; runpy.run_path('fx/full_py.py')"`.

**Direction.**

- Resolve `-m NAME` against the cwd, then each `PYTHONPATH` entry, and read the module or the
  package's `__main__.py`.
- For a directory or zip given to `python`, read `__main__.py`. A zip it cannot read is UNSEEN.
- In Python code, a string literal passed to `open`, `runpy.run_path`, `compile`, `exec`,
  `importlib` or `SourceFileLoader` names code: read it, or deny it as UNSEEN.

### M5. pytest's own argument sources are not read

pytest is the declared full program, so these are one-line full runs. `-o addopts=` and `-c <ini>`
were checked against pytest 9.0.3 in this venv: each added a test file to a `--co` run
(`probe_463r9_pt/o2.txt`, `o3.txt`).

**Reproduced** (group `ptcfg`). All ALLOWED in-process and through the daemon:

- `pytest -o addopts=tests tests/unit/qa` and `pytest -o 'addopts=tests' -q tests/unit/qa`;
- `pytest -c fx/p.ini --rootdir=. tests/unit/qa`, where the ini's `addopts` names `tests`;
- `read PYTEST_ADDOPTS <<< tests; export PYTEST_ADDOPTS; pytest -q tests/unit/qa`;
- `printf -v PYTEST_ADDOPTS tests; …`;
- `export $(cat fx/addopts.env); pytest -q tests/unit/qa`. The same file through `env $(cat …)` and
  through `. file` DENIES.
- `pytest tests/unit/block_report tests/unit/config … tests/unit/utils`, which lists all 24
  `tests/unit` subdirectories. The config calls `tests/unit` full, and this is `tests/unit` spelled
  out.

`pytest @args.txt` (an argument file) DENIES; that one is fine.

**Direction.**

- Read a `-o`/`--override-ini` value of `addopts=…` as more arguments.
- Treat `-c`/`--config-file`/`--inifile` as a file to read for `addopts` (UNSEEN if unreadable).
- Any `PYTEST_ADDOPTS` mention that is not the literal `NAME=value` form (`read`, `printf -v`,
  `export $(…)`, `declare`) makes the addopts UNSEEN.
- Judge a set of operands that covers every child directory of a full argument as full.

### M6. Launchers and positions still not followed

**Reproduced** (groups `envS`, `runner`, `xargs`, `psub`, `func`, `eval`, `misc`). All ALLOWED
in-process and through the daemon:

- `env -S 'pytest tests'`, `env -S'pytest tests'`, `env --split-string='pytest tests'` and
  `/usr/bin/env -S 'bash -c "pytest tests"'`;
- `git -c alias.t='!pytest tests' t`, `git rebase --exec 'pytest tests' HEAD~1` and
  `git bisect run pytest tests`;
- `su -c 'pytest tests'`, `at now <<< 'pytest tests'`, `systemd-run --user --wait pytest tests`,
  `unbuffer pytest tests` and `hyperfine 'pytest tests'`;
- `printf 'tests\n' | xargs -I{} pytest {}` and `echo 'pytest tests' | xargs -I% sh -c %`. Plain
  `echo tests | xargs pytest` DENIES, so the `-I` placeholder is what is missed.
- `tee >(bash) <<< 'pytest tests'` and `echo pytest tests > >(bash)`, where the output process
  substitution runs a shell;
- `f() { "$@"; }; f pytest tests` and `set -- pytest tests; "$@"`, with `"$@"` as the command word;
- `$(<fx/full.sh)` as the command word. `$(cat fx/full.sh)` DENIES.
- `make -f fx/Makefile t`, `make -C fx t`, `tox -c fx/tox.ini`, `nox -f fx/noxfile.py`,
  `npm test --prefix fx`, `npm run test --prefix fx` and `cd fx && npm test`, where each config runs
  `pytest tests`.

**Direction.**

- Follow `env -S`/`--split-string` by splitting the value as `env` does.
- Add launchers for `su -c`, `at`/`batch` (stdin), `systemd-run`, `unbuffer` and `hyperfine`
  (each argument is a command).
- Follow `git -c alias.*=!…`, `git rebase --exec|-x` and `git bisect run`.
- Substitute the `xargs -I`/`-i` replacement string.
- Treat `>(…)` like `<(…)` as a consumer.
- Treat `"$@"`, `"$1"` and `${@}` in command position as an unset-variable command word.
- Treat `$(<f)` as `$(cat f)`.
- For `make`/`tox`/`nox`/`npm`, raw-scan the config file they read (`-f`/`-C`/`-c`/`--prefix`, or
  the cwd default) for declared names. This is the M3 rule.

### M7. The daemon's 30 s budget: a 32 KiB heredoc-opener command takes 24-27 s through the chain

**Reproduced** (`probe_463r9_budget_out.txt`, `probe_463r9_budget2_out.txt`; load average
2.4-3.6 on 8 cores, no gate running):

| Command (ends `pytest tests` unless noted)            | Length | This handler in-process | Whole daemon chain |
| ----------------------------------------------------- | ------ | ----------------------- | ------------------ |
| `cat <<'E'\nE\n` × 2,700                              | 32,412 | 3.08 s DENY             | **26.92 s** DENY   |
| the same, × 2,725                                     | 32,712 | 3.14 s                  | 24.77 s            |
| the same, ending `bash /abs/chain11.sh`               | 32,460 | 3.32 s                  | 23.81 s            |
| `: <<'E'\nE\n` × 3,600 (over the cap, name scan only) | 36,012 | 0.00 s                  | 21.69 s            |
| 200 × `bash hd32k.sh a<i>` (B1 heredoc variant)       | 12,888 | 6.01 s                  | 12.22 s            |

- The chain time is mostly OTHER handlers running `strip_quoted_heredoc_bodies` (Plan 00466
  N38/N41). The 36 KB row shows this: this handler spends 0 s on it, and the chain still takes
  21.7 s.
- A forwarder timeout returns no decision, so the command is ALLOWED. The margin is 3-8 s at low
  load. The gate's own full run pushes load well past this, so under load this is a timeout, which
  is an allow.
- This handler's own share is 3-6 s.

**Direction.**

- Do not merge 463 before N38/N41 lands, or make the chain turn a budget overrun into a deny for a
  SUB-scoped guard.
- In 463, count heredoc openers (linear) before calling the shared scanner, and deny past a
  threshold, so this handler's own share is bounded.
- Correct the fixer's 3.90 s figure: it is 12.2 s through the daemon here.

## Minors

- **m1. `bash -n scripts/qa/run_tests.sh` is denied.** This is the one false deny in the 64 new
  everyday commands. `-n` (`--noexec`) reads and parses the script without running anything. Treat
  `bash|sh -n` and `--noexec` as running nothing.

- **m2. `_names_the_failure` (item 4) is a denylist, and 12 trivial shapes pass** (`probe_463r9_yield_out.txt`).

  - `yield ()`, `yield []`, `yield {}`, `yield -1`, `yield f""` and `yield str()` pass;
  - so does `yield path`, a normal item yielded on error;
  - so do `yield from range(0)`, `yield from (x for x in ())`, `yield from map(str, ())`,
    `yield from itertools.chain()` and `yield from ([] if True else [])`.

  `yield from helper()` is undecidable, and it is presumed to name the failure. **That presumption is
  a fail-open.** Direction: turn it into an allowlist. A yield names the failure only when the
  expression references the bound exception name (`except … as exc`), or is a non-empty string, or
  an f-string with literal text. A call counts only if the exception is among its arguments. Pin
  the 12 shapes as RED.

- **m3. `pytest ~+/tests` is allowed.** Bash expands `~+` to `$PWD`; add it to
  `_CWD_VARIABLE_PREFIXES`.

- **m4. `t() { pytest "$@"; }; t tests/unit/qa` is denied.** Function arguments are not bound to the
  body's `$@`, so a targeted call is judged unseen. It fails closed, but it is a false deny on an
  ordinary helper shape.

- **m5. A symlink to a declared runner is judged by its content, not its target's name.**
  `fx/q.py lint`, which links to `llm_qa.py`, is denied by the raw scan (101 KB over the meter).
  Resolving the link (`os.path.realpath`) before the declared-name check would judge it by its
  pattern.

## Nits

- **n1.** `_reset_unreadable_warning_burst` (`path_predicates.py`) is documented "Test-only:
  production never needs this". It is a test helper in shipped `src/`. The rule is "No test
  constants in shipped src/". Move the reset to a fixture that clears `_warning_bursts`.
- **n2.** `_FRAMES_ABOVE_CALLER = 3` hard-codes the call depth. Any new wrapper between a public
  predicate and `_answer_or_fallback` silently changes which site a burst is charged to. Pass the
  caller down explicitly, or use `stacklevel`-style counting from the public entry point.
- **n3.** `test_a_self_feeding_file_of_a_hundred_lines…` was deleted rather than converted. The
  60-line twin was converted to a parse count. Converting the 100-line one too costs nothing.
- **n4.** The fixer's B1 table figures (1.16 s and 3.90 s) differ from mine (0.53 s and 12.22 s)
  under similar load. Report counts, not seconds.

---

## Test integrity (`git diff 1569d25f8..HEAD`)

- **Skips.** No `skipif`, `pytest.skip`, `xfail`, `importorskip`, `geteuid` or `getuid` is added to
  tests. The `_is_root_source` match is a Python-AST helper name.
- **Wall clock.** No `perf_counter`, `time.time`, `monotonic` or `elapsed` in added test lines.
  Every wall-clock assert removed since `aae6c33b` was replaced by a parse-count or byte-count assert
  (`_ParseLedger`, `_ReadLedger`).
- **Suppressions and exclusions.** None added. The three `nosec` in `run_changed_tests.py` date
  from `a1fff052d`, and `main` carries `nosec` in 33 files. No exclusion or allowlist file is
  touched (`changed_tests_map.yaml` +89 is the test map, not an exclusion).
- **Removed asserts since `aae6c33b`.** There are five. Each was replaced by a stricter one (a
  `_TOO_DEEP_REASON` equality, a `_SCANNED_FILE_REASON` equality, parse counts), except the deleted
  self100 test (n3).
- **Test constants in `src/`.** None beyond n1.

## Merge risk with `worktree-plan-464-commit-gate-repo` (`768d98b54`)

`git merge-tree --write-tree 50741c610 768d98b54` (`probe_463r9_mergetree.txt`) gives 3 conflicts:

- `CLAUDE.md` (the auto-generated section) and `CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md`.
  463 has the same two conflicts against `main` alone.
- `src/claude_code_hooks_daemon/utils/shell_segmentation.py`, in the import block only. 463 adds
  `dataclass` and `Final`; 464 adds `lru_cache`. Keep all three.

**The semantic overlap is larger than the text conflict.**

- 463 adds `peel_command_wrappers`/`_takes_next_word` and edits `_QUOTED_HEREDOC_PATTERN`.
- 464 rewrites `strip_quoted_heredoc_bodies`, `strip_inert_spans`, `split_unquoted` and
  `_receiver_is_data_sink`, and removes `_inside_command_substitution`.
- 463's handler calls `strip_inert_spans` and `split_unquoted`.

I resolved the import conflict in a `git archive` copy of the merge tree (`probe_463r9_merged/`) and
ran 463's blocker, corpus, setup-worktree guidance, `test_shell_segmentation` and two pipe_blocker
suites there: **1638 passed, 0 failed** (`probe_463r9_merged_pytest.txt`).

M7's timings depend on which `strip_quoted_heredoc_bodies` wins. 464's rewrite and 00466 N38/N41
both touch it, so re-measure M7 on the combined head.

## Verdict

**NOT READY.**

- B1 and B2 break the binding principle directly, in one-line commands:
  - a path built by a substitution is treated as nothing;
  - past a cap, the code an oversized text runs is never read.
- Items 1 to 4 were each a finding; none is safe as it stands:
  - item 1 is B1, and wider than the idioms;
  - item 2 is B2;
  - item 3 is M1, where 94% of the suite runs through the declared script;
  - item 4 is m2, where 12 trivial shapes pass.
- The majors are all one-line full runs (81 of 202 new evasion rows are allowed):
  - interpreters and binaries (M3);
  - Python `-m`, a directory, `exec`/`runpy` of a file (M4);
  - pytest's `-o addopts`/`-c ini` (M5);
  - `env -S`, `xargs -I` and git hooks (M6);
  - in-command rewrites by `cp`/`mv`/`ln`/`patch`/Python (M2).
- M7 leaves only 3-8 s of daemon budget on a 32 KiB heredoc command.

**What is good:**

- Every review 8 finding is fixed as described.
- The 114-row and 203-row corpora are fully correct in-process and through the daemon, and 63 of 64
  new everyday commands are allowed.
- The meter denies B1's shapes quickly.
- The tests count work instead of seconds, with no skips and no suppressions.
- The merge with 464 is a trivial import conflict, and the combined tests pass.

## Full gate

`bash /workspace/untracked/scratch/gate.sh worktree-plan-463-full-qa-gate` was started in the
background at the start of this review. At the time of writing it was queued behind another
worktree's full run (`worktree-n466-n24`). The gate line is appended below once
`gate-worktree-plan-463-full-qa-gate.out` ends with `exit=N head=50741c610`.
