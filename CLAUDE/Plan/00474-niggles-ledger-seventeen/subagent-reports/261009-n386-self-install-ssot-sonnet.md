# N386: one self-install rule

Branch `agent-aad776239ba17caaa-f439650b`. The rule is `daemon/install_layout.is_self_install_mode`
(`.is_dir()` on `src/claude_code_hooks_daemon`); the shell twin is `is_self_install_checkout` in
`scripts/install/mode_guard.sh`.

## Sites

| Site                                                                                                 | Outcome                                                                                                                                                                                                                                                                                                                                         |
| ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `daemon/cli.py` `_daemon_untracked_dir`                                                              | The function is gone; `get_untracked_dir` is imported under that name. Inside the package, so a plain import.                                                                                                                                                                                                                                   |
| `install/client_validator.py`                                                                        | Calls `is_self_install_mode`.                                                                                                                                                                                                                                                                                                                   |
| `utils/ccy_supervisor.py`                                                                            | `_SELF_INSTALL_MARKER_PARTS` and the two untracked-path tuples are gone; `daemon_untracked_dir` calls `get_untracked_dir`.                                                                                                                                                                                                                      |
| `scripts/debug_info.py`                                                                              | Runs on a bare interpreter, so `_load_daemon_util` gained a `subpackage` argument and loads `daemon/install_layout.py` by file path. Tested in a `-S -I` subprocess.                                                                                                                                                                            |
| `.claude/ccy/claude-supervise.py` (not in the ledger)                                                | The `.exists()` copy the ledger and the fact-check both missed. Stdlib-only, so it loads `install_layout.py` by path from its OWN checkout (`src/` or `.claude/hooks-daemon/src/`), not from the project dir; no rule file found raises `FileNotFoundError`. One test that copied the script to a bare tmp dir now models a real client deploy. |
| `setup_worktree.sh`, `health_check.sh`                                                               | Call `is_self_install_checkout`. `health_check.sh` keeps its config flag (a separate fact: the flag says what was configured, the function says what is on disk); it now gets its colours from `output.sh` through `mode_guard.sh` instead of redefining them.                                                                                  |
| `mode_guard.sh` `detect_self_install_mode`                                                           | The marker term calls the function. The stricter variant ALSO requires `pyproject.toml` and that `.claude/hooks-daemon` is not a real clone, so a client that vendored the daemon is not misread as the daemon repo (Plan 00455). That is a separate question and stays.                                                                        |
| `bootstrap-self-install.sh`, `CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh` (not in the ledger) | Found by the detector or the search behind it; both call the function.                                                                                                                                                                                                                                                                          |

## `.exists()` versus `.is_dir()`

No caller depended on a FILE at the marker path. The existing tests for all touched sites pass; the new tests pin
that a file at the path is a client install at every site, and the shell/Python parity test covers dir, file at the
marker, `src` as a file, and absent.

## `daemon/validation.py:105-125`

A different question, left alone. It asks whether `pyproject.toml` NAMES this package, so it is also true for the
daemon's own clone vendored under a client's `.claude/hooks-daemon/`, where `src/claude_code_hooks_daemon` is NOT at
the project root. Folding it into the install-mode rule would change that answer.

## Detector

`scripts/qa/check_install_mode_marker.py`, tool `install_mode_marker`, rules `install-mode-marker` and
`install-mode-marker-unreadable` in `qa-rules.json`; registered in `llm_qa.py` (registry, `CHANGED_TOOL_NAMES`,
summariser), `run_all.sh`, `CLAUDE/QA.md`, and the walker lists in the two QA integration tests. Python half (AST):
a stat call (`exists`, `is_dir`, `os.path.isdir` ...) on a path that ends at the package directory, directly or via
a bound name, `joinpath(*TUPLE)`, `os.path.join` or an f-string, UNLESS the path's root is anchored to `__file__`
(scan roots like `_REPO_ROOT / "src" / ...`, which is how it tells scanning from deciding). Shell half: `[ -d ]`,
`[[ -e ]]`, `test -d` on a path ending at the directory, or a variable assigned from one. Paths that go deeper
(`.../version.py`) are not matched. Only the two definitions are exempt, by relative path. Python that does not parse
decides nothing (the tree keeps deliberate syntax-error fixtures).

## Residual, not fixed

`init.sh:2394`, `provision.sh:68` and the top of the v2.11 `verification.sh` decide "is this the daemon repo" from
`src/claude_code_hooks_daemon/version.py`, a file marker. The detector does not match it (a path that deep is also
read legitimately, e.g. to read the version). They need an owner decision on whether init.sh and provision.sh may
source `mode_guard.sh`.

## Round-1 review changes

- `.claude/ccy/claude-supervise.py` is reverted to main: it must start with no daemon clone present, so it keeps its own copy (a deliberate residual). The v2.11 `verification.sh` is reverted too. The detector does not scan `.claude/ccy/` or `CLAUDE/UPGRADES/`, by design (module docstring).
- `tests/acceptance/conftest.py` now calls `is_self_install_mode`; a `__file__`-anchored stat whose answer is kept as a value is still flagged.
- The definitions are exempt by absolute path, so `--path src` does not flag them.
- Both rows for those two files in the Sites table above are superseded by this section.
