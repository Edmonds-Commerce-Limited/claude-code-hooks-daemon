# Category: untrusted venv interpreter

**Defence**: `scripts/qa/check_venv_interpreter_trust.py`, run as llm_qa
`venv_interpreter_trust` (check 34 in `run_all.sh`). It reports code that judges
a venv interpreter usable, or selects it, without comparing the major.minor in
the venv's `pyvenv.cfg` with the interpreter that will run it. Its two rules:

| Rule id                    | What it reads                                                                                                                                                                                                                                                                                                                           |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `venv-exec-bit-trust`      | An existence or exec test (shell `[ -x/-f/-e ]`, `[[ ]]`, `test`; Python `.is_file()`, `.exists()`, `os.access`, `os.path.isfile/exists`) on a venv interpreter: a `bin/python`/`bin/python3` path, a variable bound from one or from the venv resolver, a `venv-*/bin/$name` scan variable, or a `python_path` read from venv metadata |
| `venv-weak-liveness-probe` | An interpreter run as `-c "import sys"`, `--version` or `-V` and nothing else; any Python at all passes it                                                                                                                                                                                                                              |

Index: [README.md](README.md). Found when the system Python moved from 3.11 to
3.13 (Plan 00555).

## The class

A venv's `bin/python` is a symlink to the system interpreter that built it. It
is built with `include-system-site-packages = false`, and its packages sit in
`lib/python<major.minor>/site-packages`. When the system Python changes minor
version, the symlink runs the new minor, which looks in
`lib/python<new>/site-packages` and finds nothing. The daemon cannot import
itself.

A defect belongs here when code decides a venv interpreter is usable, or picks
one, on evidence that still holds in that state: the file exists, it has the
exec bit, `import sys` runs, `--version` prints. The decision then stands and
the self-heal, which only fires when nothing resolves, never runs.

What is proof, computed from the source and not asserted:

| Proof                                                                                                 | Where it lives                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The same function reads `pyvenv.cfg`, mentions a version, and compares                                | Python: a `pyvenv.cfg` string or name, a `version`/`version_info`/major-minor reference and a comparison, docstrings ignored; shell: `pyvenv.cfg` and `version` outside comments                                                                                                              |
| The same function calls a gate whose OWN body passes the test above                                   | `GATES` in the Detector: the two public gates `venv_interpreter_usable` (`daemon/paths.py`) and `venv_python_usable` (`scripts/lib/resolve_venv.sh`), plus `_rv_cached_venv_current`; `proven_gates` reads each one's body, so a gate that only probes proves nothing and is itself a finding |
| The same function runs `<interp> -c "import claude_code_hooks_daemon..."` without touching `sys.path` | The venv cannot see its own site-packages after a minor change, so the import fails                                                                                                                                                                                                           |

What is NOT proof:

- **A file that exists and is executable.** Both hold for a symlink to any
  interpreter.
- **`import sys` or `--version`.** The interpreter runs; that says nothing about
  the venv it is meant to serve.
- **`pyvenv.cfg` read but not compared.** Reading it is not checking it.
- **A version comparison with no `pyvenv.cfg`.** It compares the running
  interpreter with a constant, not with the venv.
- **An import probe that puts the source tree on `sys.path` first.** The package
  then imports from source even when the venv's site-packages are unreachable.
- **A version number in a directory name.** It records the build interpreter,
  not what `bin/python` runs now.

There is no exemption marker: fix the site, or fix the Detector.

Shell scoping: a name declared `local`, `declare` or `typeset` inside a function
is a fresh variable there, so an outer interpreter binding of the same name does
not reach it (`0298f52c5`). A local the function itself binds to an interpreter
is still tracked, and a function that does not declare the name still sees the
outer binding. Proof is still per function.

Scope: every tracked first-party `*.py`, `*.sh`, `*.bash` and shell/python-shebang
file except `tests/` (test code builds and asserts on fake venvs and selects no
interpreter to run the product), any `fixtures` or `assets` directory,
`.claude/worktrees/`, `untracked/` and vendored code.

## Why a review finds it and the test suite does not

Every test ran on a host whose system Python and venv agreed. A fixture venv is
built by the Python running the test, so its `bin/python` is always the right
minor, and a mock of the probe returns what the code expects. The defect needs a
venv built before a system upgrade and a host after it; no fixture is in that
state unless it is built to be.

The checks that look wrong in review also look reasonable: "is it there, can it
run, does it start" is the usual definition of a working interpreter. The
missing question, "is it the interpreter this venv was built for", is only
visible by asking what the symlink does after the system changes.

## Instances

The Defence landed first (`b0dbbe5e4`, widened in the commit after it). The
core sites were then routed through the two public gates in `b51912cb8`, and
the remaining rows by the commits in the Fix column. Rows group findings of one
function or script.
Line numbers are those at the Defence commit.

| Where                                                                                                                                         | What it allowed                                                                                                        | Defence   | Fix                  |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | --------- | -------------------- |
| `daemon/paths.py` `_venv_interpreter_runs` (960), now `venv_interpreter_usable`                                                               | The resolver's liveness gate is `-c "import sys"`: a symlink to another minor passes (the originating instance)        | b0dbbe5e4 | b51912cb8            |
| `daemon/paths.py` `_best_ranked_scan_candidate` (998), `resolve_existing_venv_python` (1082), `_pick_interpreter` (1174)                      | Hot path and diagnostics path accept a venv on exec bit; the scan fallback takes any `venv-*` with no minor comparison | b0dbbe5e4 | b51912cb8            |
| `daemon/paths.py` metadata branch (1234, 1235)                                                                                                | `python_path` from `.daemon-metadata.json` is used on is_file + X_OK, chosen by `lock_hash` alone                      | b0dbbe5e4 | b51912cb8            |
| `daemon/paths.py` `live_venv_realpaths` (2977)                                                                                                | A venv whose interpreter exists is classed "live" for pruning (judged unsure by the independent search)                | b0dbbe5e4 | b51912cb8            |
| `scripts/lib/resolve_venv.sh` `_rv_candidate_runs` (216, 221)                                                                                 | The bash resolver's gate is `-c 'import sys'` (now `venv_python_usable`)                                               | b0dbbe5e4 | b51912cb8            |
| `scripts/lib/resolve_venv.sh` `_rv_pick_ranked_scan` (324), env override (355, 359), `resolve_venv_python_in_venv` (579, 583)                 | Scan, `HOOKS_DAEMON_VENV_PATH` and the in-venv resolver accept on `-x`                                                 | b0dbbe5e4 | b51912cb8            |
| `bin/hooks-daemon` and `install/templates/hooks-daemon` (278)                                                                                 | `exec "$PYTHON" -m claude_code_hooks_daemon.daemon.cli` after only `[ -x "$PYTHON" ]`                                  | b0dbbe5e4 | b51912cb8            |
| `init.sh` `_is_daemon_installed` (2197)                                                                                                       | "Installed" means `[[ -f "$PYTHON_CMD" ]]`                                                                             | b0dbbe5e4 | b51912cb8            |
| Skill scripts `daemon-cli.sh`, `health-check.sh`, `init-handlers.sh` (`.claude/skills` and `src/.../skills` copies, six)                      | Run the resolver's result after `[ ! -f "$PYTHON" ]` only                                                              | b0dbbe5e4 | 83fc85414            |
| `scripts/upgrade_version.sh` (804, 884, 1098, 1166, 1670)                                                                                     | Upgrade steps run the resolved venv Python after `-f`                                                                  | b0dbbe5e4 | e1a368063            |
| `scripts/upgrade.sh` (923, 932, 967, 998, 1052, 1106, 1158, 1253, 1289)                                                                       | A `venv-*py3*` glob picks the first executable; its path is written to metadata that the resolver later trusts         | b0dbbe5e4 | dc650805b            |
| `scripts/venv-include.bash` `venv_exists` (70), `venv_tool` (307)                                                                             | QA wrappers treat any `bin/python3` as a venv and run any `bin/<tool>` whose shebang points into it                    | b0dbbe5e4 | 10b2732e0            |
| `scripts/install/venv.sh` `verify_venv` (137, 143, 149)                                                                                       | Verification is exists, executable, `--version`; its import test puts `src` on `sys.path`                              | b0dbbe5e4 | 486b61a22            |
| `scripts/install/venv.sh` `venv_lock_hash_matches` fallback (366, 368), `eager_cleanup_stale_venvs` (1693), `install_package_editable` (1593) | Interpreter picked or used on exec bit                                                                                 | b0dbbe5e4 | 486b61a22            |
| `scripts/qa/run_canonical_callers_check.sh` (43), `run_strategy_pattern_check.sh` (44), `validate_worktrees.sh` (73), `debug_hooks.sh` (70)   | Tool scripts run the resolver's result after an existence or exec test                                                 | b0dbbe5e4 | ed51d5951, 9dc994c0f |
| `scripts/install_version.sh` (805), `setup_worktree.sh` (307)                                                                                 | A just-built venv is run on `-x` (low exposure; `setup_worktree.sh` compares the directory tag later, see below)       | b0dbbe5e4 | 9dc994c0f            |
| `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/verification.sh` (79), `v2.12-to-v2.13/verification.sh` (26)                                                 | Frozen historical upgrade checks on the retired `untracked/venv` layout (inline pyvenv.cfg compare, no library)        | b0dbbe5e4 | d262dd275            |

### Findings first reported as carrying no hazard, now resolved

The Detector has no exemption marker, so each of these was either fixed at the
site or the Detector was corrected. The Detector reports zero findings on the
tree.

- `daemon/paths.py` `_probe_python_version` (418): fixed (`780babfad`). A venv
  interpreter on `PATH` (a `pyvenv.cfg` two levels up) that
  `venv_interpreter_usable` refuses is no base interpreter, so the probe returns
  `None`. A plain system interpreter is probed as before. No lexical narrowing.
- `scripts/install/rollback.sh` (132, 133, 210): fixed (`e0515c094`). A usable
  venv records the interpreter's version and takes the `pip freeze`. A drifted
  one is still recorded, from its `pyvenv.cfg`, as `3.11.2 (interpreter drifted)`
  (the field has no reader beyond the manifest itself), and its pip is skipped.
- `scripts/install/venv.sh` `get_venv_python_version`: deleted, it had no caller
  (`486b61a22`).
- `scripts/venv-include.bash` (157): routed through the gate (`10b2732e0`).
- `scripts/upgrade.sh` (345): the message now takes the version from the
  discovery library's own `_pd_probe_version`, so the interpreter is not run
  inline; no Detector narrowing was needed (`dc650805b`).
- `scripts/upgrade.sh` (967): a Detector bug, fixed by the local-shadow rule
  above (`0298f52c5`); the variable was not renamed.

A `--version` whose exit status is never consumed (only its text printed) was
considered as a Detector narrowing and not built: the consumed-status shapes
(`if`, `&&`/`||`, `$?`, `set -e`, a test on the output, an assignment tested
later) cannot be told apart from it by the line-local reader, and the one site
that needed it was fixed instead.

## What the Defence does not catch

Each of these is a root cause the independent search named, and none has a
lexical signature a Detector can read without matching hazard-free code. The
first three were fixed by hand in `b51912cb8`, with tests that fail on the code
before it; the Detector cannot confirm that, so a regression here stays silent.

- **(d) Freshness decided by `lock_hash` or the `.daemon-version` stamp.**
  Fixed by hand in `b51912cb8`: `_cli_check_venv_fresh` returns STALE when an
  interpreter fails the gate, and `_write_venv_metadata` refuses to stamp one.
  `_cli_check_venv_fresh`, `_venv_is_fresh` and `ensure_venv` ask whether the
  dependency pins changed, never whether the interpreter did. There is no
  interpreter-bearing call to find; the defect is a missing term in a hash. The
  wider rule considered: "a freshness predicate must mention the interpreter
  minor". Not built: "freshness predicate" is a role, not a spelling.
- **(e) Self-heal, repair and advisories gated on "nothing resolves".**
  Fixed by hand in `b51912cb8`: the resolvers now return nothing for a drifted
  venv, so the self-heal and repair arms fire; `_repair_venv_locked` also checks
  the built minor against the fingerprint.
  `_venv_self_heal`, the `bin/hooks-daemon` repair arm and
  `_warn_if_venv_not_built_for_source` run only when the resolver finds no venv
  (or judge lock drift only), so a resolvable wrong-minor venv leaves them
  dormant. The defect is a branch condition's meaning. The wider rule
  considered: "repair must be reachable from a resolvable-but-unusable venv".
  Not built: it needs control flow across the resolver and its callers.
- **(f) Success judged by "the resolver returned something".**
  Fixed by `b51912cb8` through the resolver: `_vb_build_under_lock` is correct
  once the resolver is version-aware. Its test passes on the code before the
  commit (the Python resolver already refused drift), so it is a regression
  guard, not a reproduction.
  `_vb_build_under_lock` and callers that run `resolve_venv_python`'s output
  with no test at all (`run-qa-runner.sh`, `init.sh` `_resolve_python_cmd`, the
  `_resolve-venv.sh` shims, `_hooks_daemon_run_cli_helper`) contain no
  existence test to report. Nothing in them is wrong in isolation; the
  resolver they delegate to is.
- **(c) A cache keyed on `untracked/` mtime.** The hot-path cache
  `.python-cmd-cache` is invalidated by a timestamp a system upgrade does not
  move. `_rv_cached_venv_current` is the named gate, but a missing invalidator
  is an absence.
- **Delegation.** The Detector judges a function by its own body. A caller that
  inherits a bad resolver is clean until the resolver is reported; once it is
  fixed the callers follow.

### The next wider rule, considered and not built

"Any execution of a venv interpreter not obtained from the single-source-of-truth
resolver." It would catch hand-built `venv/bin/python` paths wherever they run,
including those with no existence test. It needs cross-function data flow: to
know that `$PYTHON` came from the resolver (or not) the Detector must follow the
value through assignments, arguments and sourced files. That is the same shape
of analysis the signal-targets Detector declines for pid provenance, for the
same reason: a name-based approximation reports correct callers, and a rule that
is wrong in the safe direction too often gets suppressed.
