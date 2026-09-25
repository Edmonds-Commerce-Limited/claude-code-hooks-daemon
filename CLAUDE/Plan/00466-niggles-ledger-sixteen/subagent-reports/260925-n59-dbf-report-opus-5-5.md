# Defence Before Fix report: N59, unproven signal target

Branch `worktree-n466-n59`, cut from main `9f83b9ff9`. Practitioner: the N59
fix agent (Opus 5.5), under the team lead's instruction. The independent search
was run by a separate agent (`n59-searcher`), dispatched by the lead before the
rule existed. Its report is kept beside this one as
[260925-n59-independent-search.md](260925-n59-independent-search.md).

## Specification followed

- Method specification **1.0.1**, published 2026-09-08.
- Detector specification 1.0.0 and tooling specification 0.2.0.
- Every copy read was **vendored**, from the `defence-before-fix` plugin 0.1.1
  cache. The refresh script (`scripts/refresh-spec.bash`) ran with `--offline`
  and reported the vendored copy; nothing was fetched.
- Also read before any narrowing: `project-prompt.md` and SPEC section 4.

## Toolchain

- **No conforming toolchain was found.** The project manifest declares no DBF
  toolchain. The tools register lists `php-qa-ci` and `ts-qa-ci`, and neither
  reads Python or shell.
- **Detector chosen:** a bespoke detector in the project's own QA framework,
  `scripts/qa/check_signal_targets.py`. It uses Python's `ast` for Python
  and a small shell lexer for shell. The project already runs its security
  checks this way, one script per class, each wired into `llm_qa.py` and
  `run_all.sh` (for example `check_error_hiding`, `audit_shell`).
- **Listing:** `./scripts/qa/llm_qa.py signal_targets` (writes
  `untracked/qa/signal_targets.json`). Direct: `python scripts/qa/check_signal_targets.py [--json]`.
- **Identifier resolution:** the four rule ids are documented in
  `CLAUDE/Security/UnprovenSignalTarget.md`, the page the failure message
  names. The project has no command that resolves an id to its docs; see the
  gaps below.
- **Single-rule harness:** none. The detector runs all four rules together.
  Fixture-level tests call `scan_source` and `scan_shell_source` directly, in
  `tests/unit/scripts/test_signal_target_checker.py`.
- **Calibration:** none recorded. Assumed: blocking, zero tolerance, no
  baseline and no suppression marker. The detector has no marker to honour.

## Defect and class

**Originating instance.** N53's never-merged branch `run_git` timeout path,
`os.killpg(os.getpgid(process.pid), SIGKILL)`. Its tests patch
`subprocess.Popen` with a `MagicMock`, whose pid coerces to 1. PID 1 is
`tini`, so the test killed the container, twice (exit 137, 11:07 and 11:36 UTC).

**Class: unproven signal target.** A nonzero signal is sent to a pid that
nothing proved is the intended process. Registered at
`CLAUDE/Security/UnprovenSignalTarget.md` and indexed in the Security README.

**Hazard.** The signal lands on a different process. That can be init (the
whole container), Claude Code itself, another project's daemon, or an
unrelated process that reused the pid. Signal 0 carries no hazard and is
exempt.

## Rule

The detector is `scripts/qa/check_signal_targets.py`, and every rule shares
one message. The message lists the helper routes and the shell proofs, and
names `CLAUDE/Security/UnprovenSignalTarget.md`, which documents all four ids.

| Id                        | Language | What it reports                                                                                                                                                                                      |
| ------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `raw-signal`              | Python   | `os.kill`/`os.killpg`/`signal.pthread_kill`, resolved through import aliases, unless the signal is the literal `0`. A starred or short call is reported.                                             |
| `unproven-process-handle` | Python   | `terminate`/`kill`/`send_signal` on a `psutil.Process(...)` or `process_iter()` handle, and `send_signal` on any receiver not bound from a Popen factory in the same scope.                          |
| `kill-command`            | Python   | A `kill`/`pkill`/`killall` argv passed to `subprocess`, other than `-0`.                                                                                                                             |
| `shell-unproven-kill`     | Shell    | `kill`/`pkill`/`killall` in command position, with a nonzero signal and an unproven target. This includes `kill` inside `$( )`, backticks, `trap`/`eval` strings and `sh -c` strings. Details below. |

**How the shell rule is drawn.** It scans every tracked `*.sh`/`*.bash` and
shell-shebang script outside `tests/`, which is 142 files. `pkill` and
`killall` choose targets by pattern and are always reported.

A `kill` target is proven only by one of these:

- `$$`;
- `$!`, or a variable whose every non-empty binding in the file is `$!`;
- a `%job`;
- an identity check (`_is_project_daemon_pid`, `_is_dummy_daemon_pid`,
  `_vb_process_identity`, `_vb_job_running`, `_venv_parent_of`, `_rv_parent_of`)
  on that variable, earlier in the same function.

A group target is proven only by an identity check. Anything read from a
file, a substitution, `pgrep`, a literal or a positional parameter is
unproven.

**Proof in Python.** In Python a pid is proven only through
`utils/safe_signal.py`, the one exempt module, or through a handle it returned.
A Popen's own methods count as proven.

**Deliberate exclusions, each of which carries no hazard:**

- signal 0 and `kill -l`, which deliver nothing;
- words inside comments, quoted prose and quoted-heredoc bodies, which the
  shell never runs. An unquoted heredoc body is still scanned for
  substitutions.

`read_pid_file(verify_daemon=True)` was accepted as proof by the first rule
(`904f1c314`). It was **removed**, because it proves "a daemon", not this
project's daemon.

**The next wider rule, named and not built.** It would report a `$!` pid
signalled from a scope that cannot see that job still running. Examples are a
detached watchdog subshell, a trap, or a function other than the one that
started the job. The current rule exempts `$!` everywhere. That exemption was
the lead's specification for the shell rule. It is referred below, because
the hazard does arise there: `resolve_venv.sh` was an instance.

## Proof

Two red commits, each on its own, before the instances they report were fixed:

- **`904f1c314`** (Python rules). Run over an archive of main `9f83b9ff9`,
  it reported `client_validator.py:320,329` and `process_verification.py:184,192`.
  The N53 `killpg(getpgid(process.pid))` shape is a kept fixture
  (`TestTheCrashShapesAreFound`).
- **`548403a0d`** (shell rule, and the PID-file proof removed).
  - `untracked/scratch/n59_shell_audit.py scripts/qa <main archive>` reported
    main's five shell sites: `upgrade.sh:494`, `dummy-client-repo.sh:133`,
    `install/venv.sh:498`, `venv_bootstrap.sh:378` and `venv_bootstrap.sh:445`.
  - On the branch at that commit, `python scripts/qa/check_signal_targets.py`
    exited 1 with three findings: `cli.py:788`, `dummy-client-repo.sh:139` and
    `venv_bootstrap.sh:378`.
  - Kept fixtures in `TestTheShellInstancesOnMainAreFound` pin each main
    shape.

Behavioural RED, against real child processes, before each fix. The session
safety net was active throughout:

- On main, `client_validator` sent SIGTERM to a bystander, which exited -15.
- `upgrade.sh` sent a non-daemon exit 143.
- The dummy teardown killed the survivor's group-mate.
- The watchdog sent 143 to a pid stand-in.
- The heartbeat stop sent 143 to a stand-in.
- The resolver killed a 3 s candidate at its 1 s bound.
- `cmd_stop` sent SIGTERM (-15) to another project's daemon and to a
  non-daemon bystander.
- `_is_dummy_daemon_pid`'s three tests failed while the function was absent.

## Independent search

The searcher worked on main before the rule existed and without sight of it.
It used two techniques:

- a text search for `os.kill`, `os.killpg`, `pthread_kill`, `send_signal`,
  `.terminate(`, `.kill(`, `psutil` kills, and shell `kill`/`pkill`/`killall`;
- reading each hit's pid provenance.

It found 11 sites: 4 with the hazard and 7 without.

**What text search found that reading could not have checked.** It found every
site, including the byte-identical shipped template copies. Its enumeration is
what shows no site is missing. The same technique checked the shell lexer:
a plain word search over the 142 tracked shell files found the same kill
sites as the lexer's 23 command-position sites, with none missed. The only
extra matches were prose lines in `.md` files.

**What reading found that text search could not have.**

- Pid provenance: a PID file, `pgrep`, `$!` or a parameter.
- The `venv_bootstrap.sh` N7 comment, which admits the group id may belong to
  someone else by the bound.
- The `ps -o pgid=` round trip in the dummy teardown.
- Two timing hazards the searcher judged safe but my own reading found:
  - `venv_heartbeat_stop` signals a heartbeat pid minutes after the
    heartbeat could have ended.
  - The `resolve_venv.sh` watchdog KILLs a pid `wait` has already reaped.
- `cmd_stop`: the searcher called it SAFE, but `read_pid_file(verify_daemon=True)`
  proves only "a daemon". The lead ruled it an instance.

**Instances the rule first missed, and how it widened.**

- The first rule (`904f1c314`) read Python only, so it missed all four shell
  sites:
  - the searcher's `upgrade.sh`, `venv_bootstrap` watchdog and dummy
    teardown;
  - the heartbeat stop, found by reading.
- It also accepted `cmd_stop`.
- It was widened in `548403a0d`: the shell rule was added, and the
  `verify_daemon` proof was removed.
- The widened rule also reports `_vb_signal_group`, a group kill that is
  safe only because its one caller checks first. The searcher did not list
  it.
- The rule still passes the `resolve_venv.sh` watchdog, because its pid is a
  `$!`. That is the named wider rule, referred below. The instance itself is
  fixed.

The search won everywhere it disagreed, except where the lead ruled.

## Sweep and count

**Scope.** First-party source in both languages the pattern occurs in:

- Python in `src/claude_code_hooks_daemon`, `scripts`, `.claude/ccy` (the ccy
  supervisor) and `bin`;
- every tracked shell script, including `CLAUDE/Plan`, `.claude/hooks`, `bin`,
  the skill installer and the install templates.

Together that is 795 files: 653 Python and 142 shell. No generated or
vendored code is tracked in those trees. The project had no recorded sweep
decision; this is it.

**Excluded: `tests/`.** Scanning it reports 6 sites, each examined
individually:

- three in the safety net's own tests, which call `os.kill(1, …)`/`killpg` on
  purpose to prove the net refuses them;
- two test-local identity checks: `venv_bootstrap_sandbox.py:299` and
  `test_venv_bootstrap_driver.py:626`;
- `test_supervisor.py:276`, a `pthread_kill` to our own main thread.

None carries the hazard. The exclusion is still not hazard-free as a rule for
new test code, so it is referred.

**Total instances across all scans:** 11 on the branch, of which 10 are on
main. The eleventh is the N53 branch shape, which never merged and is covered
by a fixture.

**Narrowing:** none within the scanned trees.

## Fixes

Every instance was examined individually; none received its fix by pattern.

| Instance                                               | Fix                                                                                                                     | Commit    |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | --------- |
| `install/client_validator.py` `_check_running_daemon`  | `stop_verified_daemon(pid, project_root=…)`; anything else is named in a warning and left running                       | 2817ef0e0 |
| `daemon/process_verification.py` `kill_daemon_process` | Removed; enforcement uses `stop_verified_daemon`, and signals nothing without a project root                            | 2817ef0e0 |
| `daemon/cli.py` `cmd_stop`                             | `verified_daemon_process(pid, project_root=…)`, then `terminate()`/`wait()` on the handle; a refused target is an error | 93d350d76 |
| `scripts/upgrade.sh` `_stop_running_daemons`           | `_is_project_daemon_pid PID ROOT`, a shell twin of the cmdline and root check                                           | dc7ab0e0b |
| `scripts/dummy-client-repo.sh` teardown (group)        | Signals only the proven pid, never its group                                                                            | dc7ab0e0b |
| `scripts/dummy-client-repo.sh` teardown (stale pgrep)  | `_is_dummy_daemon_pid` re-reads the cmdline immediately before the kill                                                 | 93d350d76 |
| `scripts/venv_bootstrap.sh` `_vb_watchdog`             | Records the build's start time and TERMs only a pid that still has it                                                   | dc7ab0e0b |
| `scripts/venv_bootstrap.sh` `_vb_signal_group`         | Folded into `_vb_signal_job`, with the job-table check beside the kill                                                  | 93d350d76 |
| `scripts/install/venv.sh` `venv_heartbeat_stop`        | Kills only while the pid still has the parent recorded at start                                                         | dc7ab0e0b |
| `scripts/lib/resolve_venv.sh` probe watchdog           | KILLs only while the candidate still has the recorded parent                                                            | dc7ab0e0b |
| N53 `run_git` (other branch)                           | Must call `signal_own_session_child`; the detector reports the raw `killpg` when that branch rebases                    | N53       |

Also landed:

- **The safety net, built first** (`d59056b5f`).
  `tests/signal_safety_net.py` refuses nonzero signals to init, the test
  process, its group, its ancestors and Claude Code, and fails any test that
  leaves a refusal behind.
- **The one helper** (`62e342c8e`, hardened in `ff1b4f9fe`).

No instance was satisfied by suppressing the rule, and none was left with the
hazard in place. The detector has no suppression marker. No QA exclusion was
added: a stale `error_hiding` entry was removed, and one drifted line number
was realigned.

**A shared shell helper.** The lead asked for one helper script, sourced by
each script. It was not built, for two reasons:

- `upgrade.sh` must run standalone, because it can be fetched by itself.
- `resolve_venv.sh` is copied standalone into many test fixtures.

A sourced helper would break both. Each script therefore keeps its own
identity function. The shell rule names every one of them, and the upgrade
twin has a parity test. The detector's shell lexer is likewise its own, not
the daemon's `utils/shell_segmentation.py`. That module segments a single
Bash command at top level, for runtime guards. It does not recurse into
`$( )`, skip a script's comments and heredoc bodies, or carry line numbers.
Folding the two together belongs to the Plan 00464 shell-parser
consolidation.

## Decisions referred to the owner

1. **Leave the named wider rule unbuilt: a `$!` signalled after its job may
   have ended.**

   - Counts: 1 found (`resolve_venv.sh`), 1 fixed, 0 known remaining.

   - What stopped it: the lead specified `$!` as exempt. A useful form must
     tell a `$!` still inside its job's lifetime from one that is not, and
     text cannot show that.

   - The first cut would report a `$!` variable signalled in a different
     function, trap or detached subshell from the one that bound it. On
     today's tree that reports 5 sites:

     - the skill installer's aside heartbeat, `kill "$ASIDE_HEARTBEAT_PID"`,
       in both shipped copies;
     - the heartbeat's inner-sleep trap, `kill "$_hb_sleep"`, in both
       installer copies and in `install/venv.sh`.

     All were judged safe by construction: they are signalled only while
     alive, or in the instant after `wait` has reaped them, and reuse then
     would need a wrap of the pid space.

   - To build it: the rule above, plus a proof shape for those five (a
     parent check, as `resolve_venv.sh` now uses).

2. **Leave `tests/` outside the rule.**

   - Counts: 6 sites, all examined, 0 carrying the hazard, 0 remaining.
   - What stopped it: the net's own tests must signal pid 1 and our own
     group, to prove the net refuses them. Scanning `tests/` would need an
     exception for them, and exceptions are the owner's.
   - To build it:
     - a test-side proof helper the detector recognises, for the two
       identity-checked cleanups;
     - an owner-agreed exception for `tests/unit/test_signal_safety_net.py`;
     - `pthread_kill` taken out of `raw-signal` for thread targets. It
       cannot reach another process, so it carries no hazard.

3. **The shell proof is "a check ran earlier in the function", not "the check
   gates the kill".**

   - Counts: 0 known instances. All 6 verified shell sites gate the kill on
     the check's result: `upgrade.sh`, `dummy-client-repo.sh`, the
     `venv_bootstrap.sh` watchdog and `_vb_signal_job`, `venv.sh`
     `venv_heartbeat_stop`, and the `resolve_venv.sh` watchdog.
   - Why it is referred: gating is harder to check without false positives,
     which is not the same as the hazard being absent. So under section 4
     this is the owner's.
   - To build it: require the `kill` to sit in the success branch of an `if`
     or `&&` on the verifier, or after a `||` return on it.

The rule is merged at full width. Nothing was weakened while these wait.

## Permanence

- Blocking in `scripts/qa/run_all.sh` as check 33, in its summary table.
- Blocking as `llm_qa` tool `signal_targets`, with a `ToolConfig` and a
  violation summariser.
- `./scripts/qa/llm_qa.py signal_targets` exits 0 on the final commit, with
  795 files scanned and no findings.
- Also green through the entry point: `shell_check`, `error_hiding`,
  `shell_audit`, `lint`, `format`, `type_check`, `pyright`, `magic_values`,
  `canonical_callers`, `fail_open_inventory`, `semgrep`, `security` and
  `dangerous_invocation_corpus`.
- `run_all.sh` and `llm_qa.py all` were not run. That full run is the
  coordinator's gate.
- A test pins the repository clean on every scanned file
  (`TestTheRepository::test_the_repository_is_clean`).

## Toolchain and detector gaps

- No conforming DBF toolchain exists for Python or shell in the register, so
  the detector is bespoke.
- There is no single-rule harness. All four rules run together, and one rule
  can be exercised in isolation only through the fixture API.
- No command resolves a rule id to its documentation. The failure message
  names the page by path, and a test checks that the page documents every
  id.
- The shell rule is a lexer, not a parser. A `kill` reached through a
  variable command (`"$cmd" "$pid"`) is not seen. `case` patterns inside
  `$( )` can end a substitution early.
- Both limits are recorded on the Security page.

## The original defect

The originating `killpg(getpgid(MagicMock().pid))` is on N53's unmerged branch.
Its conventional fix is `signal_own_session_child(process, SIGKILL)`, which
refuses a mock pid (not a plain `int`, and `poll()` not None or an `int`) and
any group the child does not lead.

Tests that reproduce the defect and now pass:

- `tests/unit/utils/test_safe_signal.py`: a `MagicMock` pid, `True` and
  pid 1 are refused, and a real `start_new_session` child's group is killed
  only while it leads the group.
- `tests/unit/test_signal_safety_net.py`: the net refuses `os.kill(1, …)`
  and `os.killpg` of our own group without delivering, with pre-checks
  before any real call.
- `tests/unit/scripts/test_signal_target_checker.py::TestTheCrashShapesAreFound`:
  the detector reports the N53 shape.

**Commits.** The first red commit is `904f1c314`, and the shell-widening red
commit is `548403a0d`. The final commit is the one that carries this report;
its SHA is in the hand-off message to the lead.
