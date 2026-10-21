# Plan 00546 Phase 2, Task 2.1: one declared minimum Python, checked at the entry points

Branch `worktree-issue-130-p2-guard`.

## What was built

- `src/claude_code_hooks_daemon/python_floor.py`: the single declaration, `MIN_PYTHON = (3, 11)`, plus `require_min_python(entry_point)`. It is written in old syntax (no `|` annotations, no f-strings, no `__future__`, string annotations under `TYPE_CHECKING`), so it parses on any Python 3. On failure it writes ONE line to stderr and exits 1. Run as a script it checks the running interpreter.
- A test pins `MIN_PYTHON` to `requires-python` in `pyproject.toml`.
- Entry points:
  - `daemon/paths.py`: guard under `if __name__ == "__main__"`, after the stdlib imports and before `functools.cache`. Tolerates a lone copy with no sibling `python_floor.py`, because 13 test fixtures copy `paths.py` alone.
  - `daemon/signal_standalone.py`: `_MIN_PYTHON = (3, 8)` and `_check_python_version` are deleted and replaced by the shared guard. The file must still parse on 3.8 (`TestSyntaxFloor`), so the guard can run.
  - `install.py`: guard before `import tomllib`.
  - `claude_code_hooks_daemon/__init__.py`: guard first, which covers every `python -m claude_code_hooks_daemon...` form (the package `__init__` runs before any module).
  - `bin/hooks-daemon` and its template `install/templates/hooks-daemon` (identical files): the `signal` arm replaces `sys.version_info >= (3, 8)` with `python3 python_floor.py "hooks-daemon signal"`, keeping the probe's output so a crashing interpreter still shows its real reason. This is the launcher guard for `signal_standalone.py`, which cannot parse below 3.7.

## Parse time vs run time (verified on real 3.8 and 3.9)

`str | Path` in a `def` annotation and `functools.cache` fail at RUN time (TypeError or AttributeError), so a guard placed before the first `def` works for `paths.py`. `import tomllib` and `dataclass(slots=True)` also fail at run time. Parse-time failures need a launcher guard: `from __future__ import annotations` is a SyntaxError on 3.6 and below, which is why `bin/hooks-daemon` runs the old-syntax floor file itself before executing `signal_standalone.py`.

## Red (before the change, real interpreters via `uv python install 3.8 3.9`)

```
3.8 paths.py:      AttributeError: module 'functools' has no attribute 'cache'
3.9 paths.py:      TypeError: unsupported operand type(s) for |: 'type' and 'type'
3.8/3.9 signal:    TypeError: dataclass() got an unexpected keyword argument 'slots'
3.8/3.9 install:   ModuleNotFoundError: No module named 'tomllib'
3.8/3.9 -m paths:  ImportError: cannot import name 'StrEnum' from 'enum'
```

All ten commands exited 1 with a traceback. The new test module also failed at collection (`ImportError: cannot import name 'python_floor'`).

## Green

After the change all ten commands print one line and exit 1, for example
`install.py: needs Python 3.11 or newer, but this is Python 3.9.25 (/root/.local/share/uv/python/.../python3.9).`
Targeted run: 4904 passed (tests/unit/test_python_floor.py, tests/unit/daemon, tests/unit/install, the signal wrapper integration test, test_upgrade_eager_cleanup).

## Tests

- `tests/unit/test_python_floor.py`: pyproject match, no literal repeats, guard logic, and 7 entry points x 2 real old interpreters (script, `-m`, floor script).
- `tests/integration/test_bin_hooks_daemon_signal_without_venv.py`: the wrapper under a real 3.8 and 3.9 `python3`; the stub test now asserts the new "could not report its Python version" line.
- `tests/old_python.py`: finds `python3.N` on PATH or via `uv python find`; tests skip when none exists.
- `tests/venv_bootstrap_sandbox.py`: copies `python_floor.py` into the sandbox clone.
- `test_signal_standalone.py::TestVersionFloorEnforcement` is rewritten (the removed private function is no longer there).

## Limits

- The real-interpreter tests need 3.8 and 3.9 on the host (here from `uv python install`) and skip otherwise. Nothing below 3.8 was tried; 3.6 and below are covered by reasoning only (the floor file uses only syntax valid since Python 3.0 except annotations, 3.0+, and `typing`, 3.5+).
- `paths.py` skips the check when its sibling `python_floor.py` is absent (see above).
- `-m` runs print the package name as the entry point, not the module.
- Phase 3 (a QA rule over bare `python3` in shell scripts) is untouched.
