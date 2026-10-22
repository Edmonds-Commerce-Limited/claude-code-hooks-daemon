# Adviser rulings on OWNER-QUESTIONS.md (Plan 00546, Task 3.1, issue #130)

Branch reviewed: worktree `worktree-issue-130-p3-dbf` at `825689c7a`. Read-only apart from this file. Paths below are worktree-relative.

| Question        | Ruling                                                                                 | Mark  |
| --------------- | -------------------------------------------------------------------------------------- | ----- |
| Q1 allowlist    | Approve all 8 entries (option A), with two conditions that replace option C as written | CLEAR |
| Q2 rule scope   | B for CI; B (record as gaps) for shebangs and probes, with one concrete follow-up task | CLEAR |
| Q3 heredoc rule | B, do not build it                                                                     | CLEAR |

Nothing goes back to the owner. Every ruling rests on facts established in the code, not on product intent.

## Q1: approve the 8 allowlist entries. CLEAR.

**Ruling: approve all 8 entries as they stand (option A). Do NOT take option C as written, because it cannot be executed. Attach the two conditions below instead.**

### Claims verified

1. The allowlist pins 8 entries covering 11 lines: `scripts/qa/bare-python-allowlist.json:4-44`. The lines named in the question exist and match: `init.sh:325,344,360,1728` (entry 1, 4 occurrences), `init.sh:390`, `init.sh:581`, `init.sh:1128`, `init.sh:1394`, `init.sh:3041`, `init.sh:3727`, `install.sh:123`.
2. The checker passes on this branch: `scripts/qa/check_bare_python_invocation.py` reports "No shell script runs a bare python (149 scanned)", exit 0. Its unit tests pass (116 in `tests/unit/qa/test_check_bare_python_invocation.py`).
3. Conformance finding 2 (substring matching) is fixed. The entry is keyed on the whole rstripped line (`check_bare_python_invocation.py:208,608`) and reconciled by count (`:620-650`). I proved it against the real `init.sh`: an unchanged copy reports nothing; appending a second `    _hd_answer="$(python3 -c "` line reports BOTH lines (3041 and the new one) as `bare-python-invocation`; a new `    python3 -c "import tomllib; print(1)"` is reported; deleting one recovery line yields `bare-python-allowlist-stale`. The unit tests cover the same (`:284-335`, `:382`).
4. Entry 8 is sound: `install.sh:123` runs `python3 "$DAEMON_DIR/install.py" --force`, and `install.py:33-36` calls `require_min_python` via `runpy` of `python_floor.py` before `import tomllib` (`install.py:38`). `python_floor.py` uses nothing newer than f-strings (3.6). One line, exit 1, no traceback below 3.11. This is a validating bootstrap; the hazard cannot arise.
5. Entry 5 is sound: `init.sh:1394` is the version probe; its only job is to read the PATH interpreter's version with `%`-formatting valid on any 3.x.
6. Entries 1-4, 6, 7 are not interpreter probes. The conformance review (finding 1) is right about that, and the allowlist description (`bare-python-allowlist.json:2`) now says so honestly: category (2) "stdlib-only forwarder code that runs with no venv resolved". They belong on the list for a different reason than entries 5 and 8: they run exactly when no venv exists or may not be trusted, so there is no resolved interpreter to run. That reason holds on inspection of each site (`init.sh:316-325`, `:380-390`, `:1120-1128`, `:3038-3041`, `:3722-3727`).

### Claims NOT verified as stated

7. **"Pass on 3.8 and 3.9 in `tests/integration/test_init_sh_hot_path_runs_on_old_python.py`" is not reproducible here, and the test passes silently when it cannot run.** `tests/old_python.py:17-37` only `find`s an interpreter (`python3.N` on PATH, else `uv python find`); it never installs one, and `old_python_or_skip` skips. On this host there is no 3.8 or 3.9 (`python3.11` only; `uv python find 3.8` fails), so every test in the file is SKIPPED (22 skips, exit 0). Nothing in `.github/workflows/qa.yml` installs 3.8 or 3.9 either (`setup-python` is 3.11/3.12/3.13 throughout), and `run_test_matrix.py`'s `uv python install` (`:928`) serves the matrix's own versions, not this test. So the evidence in the question is a prior agent's run on a host that happened to have them, and the gate it describes is not standing. Under "no silent fallbacks" this is the defect to fix before the allowlist can claim the 3.8 floor as proven.
8. **Option C ("add a 3.6 interpreter to the old-Python test") cannot be executed.** `uv python list --all-versions` offers nothing below CPython 3.8.2; `uv python find 3.6` and `3.7` fail. Adding `"3.6"` to `OLD_VERSIONS` would add a permanent skip, not evidence. C is a recommendation to build a test that can never run.

### The residual hazard, settled statically

The hazard the question leaves open is "a PATH `python3` older than 3.8". I checked it by grammar and by API, without an interpreter:

- Every allowlisted snippet body parses under `ast.parse(..., feature_version=(3, 6))`, `(3, 7)` and `(3, 8)`: the recovery source (`init.sh:156-311`) alone and with each of its four suffixes (`:326-333`, `:345-350`, `:361-363`, `:1729-1731`); provision (`:391-438`); needs-provision encoder (`:582-605`); `emit_hook_error` encoder (`:1129-1198`); the socket transport (`:3042-3643`, with `$_recovery_py` spliced in at `:3131`); the stop reader (`:3728-3740`).
- The stdlib surface used across all of `init.sh`'s Python is `os.path`, `os.environ`, `shlex.quote`, `json.loads/dumps/load`, `sys.stdin`, `socket.socket/AF_UNIX/SOCK_STREAM/SHUT_WR/timeout/gethostname`. Every one exists in 3.6. No `shlex.join` (3.8), no walrus, no positional-only parameters, no `removeprefix`.

So the snippets are 3.6-clean today. The floor is not "assumed", it is checkable, and it should be checked by a test that runs on every host rather than by an interpreter nobody can provision.

### Conditions attached to the approval

- **Condition 1 (replaces C): a static floor test.** Add a unit test that extracts each allowlisted snippet body from `init.sh` (the allowlist already names the invoking lines; the bodies end at the closing quote line, and the transport body needs `$_recovery_py` substituted) and asserts `ast.parse(body, feature_version=(3, 6))` succeeds and that the imported modules are within a declared stdlib set. Cost: milliseconds, no interpreter, no network, no hot-path change. Note the limit honestly in the test docstring: `feature_version` rejects grammar (walrus, positional-only, `async` identifiers), not library APIs, which is why the import set is asserted too.
- **Condition 2: the old-Python runtime test must not pass by skipping.** When `uv` is on PATH, `tests/old_python.py` should provision (`uv python install N`, the same call `run_test_matrix.py:928` already makes) rather than skip; skip only when `uv` itself is absent, and say so loudly in the skip reason. Until that lands, the "proven on 3.8 and 3.9" sentences in `bare-python-allowlist.json` entries 1-4, 6, 7 describe a test that does not run in QA.
- Keep option B off the table. The hot path is latency-sensitive; replacing stdlib Python with `jq` would add a dependency the transport deliberately dropped (`init.sh:1120-1123`), and resolving a venv interpreter per hook adds a lookup to every call (`bare-python-allowlist.json:33`). The static gate gives the same assurance at zero runtime cost.

Follow-up tasks:

1. Write `tests/unit/test_init_sh_snippets_parse_at_floor.py` (or equivalent) per Condition 1; declare the floor once (a `FORWARDER_PYTHON_FLOOR = (3, 6)` constant in `tests/old_python.py` is the natural home, since `OLD_VERSIONS` already lives there).
2. Change `tests/old_python.py:find_old_python` to install via `uv` when `find` fails; make the skip reason name the missing `uv`.
3. Reword the six "Proven on 3.8 and 3.9" reasons in the allowlist to cite both gates once they exist.

## Q2: rule scope. CLEAR.

**Ruling: B for CI. B for the shebangs and the probe sites, recorded as known gaps, with one concrete follow-up task for the shebang entry points. No widening on this branch.**

### CI (`.github/workflows/qa.yml`)

Verified: 7 bare `python` lines (`:126,171,249,338,559,621,634`) and every one sits in a job that ran `actions/setup-python@v5` first (`:68,116,226,552,610`, pinned 3.11, 3.12, 3.13 or the matrix). PATH `python` there IS the pinned interpreter. No hazard, no rule needed. The sentence in the question is the right sentence to record.

### Probe-result sites

The question's count of 4 is right (`scripts/bootstrap-self-install.sh:55`, `bin/hooks-daemon:193` and its template, `.claude/ccy/claude-supervise:64`). But the question understates what is already there, which is why no decision on "what a bootstrap may assume" is needed to close this:

- `bin/hooks-daemon:193-210`: the probe result is checked by `python_floor.py` run as a script before `signal_standalone.py` is touched; a too-old interpreter gets one line and exit 5. Guarded.
- `scripts/bootstrap-self-install.sh:55,65`: the result goes to `uv sync --python "$PYTHON_CMD"`, and `requires-python = ">=3.11"` (`pyproject.toml:27`) makes `uv` refuse an older interpreter loudly. Guarded by the tool.
- `.claude/ccy/claude-supervise:58-80`: `command -v python3` is inside `warn_unsupported`, a version-report path, not an execution path. The probe is doing its job.

So "probe result executed without a floor check" has 0 instances today. A rule for it would be a rule with no red. Record the gap; build it when an instance appears.

### Shebangs

The count is 56 on this branch, not 54 (immaterial drift). The five client-run candidates split as follows:

- `install.py`: guarded (`install.py:33-36`).
- `scripts/handler_status.py`, `src/claude_code_hooks_daemon/core/error_response.py`, `scripts/audit_handler_config_keys.py`: their first 3.11+ construct is the package import, and `src/claude_code_hooks_daemon/__init__.py:7-11` calls `require_min_python` first. Guarded.
- `scripts/debug_info.py:18`: `from datetime import UTC, datetime` runs BEFORE any package import. `datetime.UTC` is 3.11+, so on an older `python3` this is an `ImportError` traceback, exactly the shape Phase 2 set out to end. I found no caller of `debug_info.py` in `bin/hooks-daemon`, `init.sh`, `scripts/*.sh` or the skills, so it is a human-run diagnostic and the hazard is low, but it is a real instance of the shebang class and it contradicts Success Criterion 2 as literally written.

A shebang rule is a different detector (Python files, not shell) and the question is right that it does not belong on this branch. But the gap should carry its one known instance, with a count, per §3.4.

Follow-up tasks (a separate plan, not this branch):

1. Guard `scripts/debug_info.py` the way `install.py` is guarded, or move the `datetime` import below the package import. Count: 1 found, 0 fixed.
2. Decide the shebang detector's universe (which Python files a client may start with a bare `python3`), then build it; the five files above are its first fixture set.
3. Record the probe-result form as a known gap with the sentence: "every probe result today is floor-checked (`python_floor.py`) or handed to `uv`, which enforces `requires-python`".

## Q3: heredoc-generated shell. CLEAR.

**Ruling: B, do not build it.**

Verified: `.claude/skills/acceptance-test/invoke.sh:72` now reads `TOTAL_TESTS=\$(jq length untracked/scratch/acceptance_tests.json)`. The scanner skips heredoc bodies by design (`check_bare_python_invocation.py:298-308`). A grep for residual `python`/`python3` across every tracked `.sh`/`.bash`, `bin/`, `.claude/skills` and `.claude/ccy` file, minus the 11 allowlisted lines, comments, `echo`/`printf` text and `command -v`, leaves: markdown code fences (`dev-handlers.md`, `troubleshooting.md`), resolved-variable uses (`scripts/ci/*.bash`, `scripts/venv_bootstrap.sh`, `scripts/lib/resolve_venv.sh`), plan-folder prototypes the rule excludes on purpose, and the `tests/fixtures/error_hiding` snapshot. Zero heredoc-generated agent-run `python3` remains.

A rule whose universe cannot be defined by syntax (the harness cannot tell a prompt-generating heredoc from a data heredoc), with 0 instances and a measured-nowhere false-positive rate, would be a blocking rule that only ever fires wrongly. Record the gap with the one historical instance and the sentence above; revisit if a second instance appears.

No follow-up tasks.

## Summary of what blocks Task 3.1

Q1 is approved subject to Conditions 1 and 2, both engineering work on this branch. Q2 and Q3 need only the gap records (and the `debug_info.py` instance logged). None of the three needs the owner.
