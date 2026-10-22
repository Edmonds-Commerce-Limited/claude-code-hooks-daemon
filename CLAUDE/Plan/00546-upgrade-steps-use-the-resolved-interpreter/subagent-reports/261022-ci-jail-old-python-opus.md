# CI red on main: doc-write jail crashes under Python 3.8/3.9

Branch `worktree-jail-old-python`. Not merged.

## Root cause

`tests/jail_site/sitecustomize.py` arms the doc-write jail in every child
Python on the run's `PYTHONPATH`, including the deliberately old interpreters
that `tests/unit/test_debug_info_old_python.py` spawns. The jail's audit hook
called `isinstance(target, str | bytes | os.PathLike)`, which raises
`TypeError` before Python 3.10. The hook only reaches that line on an
`open` for writing. On CI the freshly provisioned uv interpreter wrote
`runpy.cpython-38.pyc` (bytecode cache), and the hook crashed inside
`import runpy`, before the floor guard in `scripts/debug_info.py` ran.

### Why it passed locally

The local uv 3.8/3.9 stdlib `__pycache__` was already populated, so the
child wrote no bytecode, no open-for-write reached the hook, and the bad
line never ran. Reproduced the CI crash locally by pointing
`PYTHONPYCACHEPREFIX` at an empty directory with the jail env armed:
`python3.8 -c 'import runpy'` gave the same `TypeError` traceback.

## Defect class and second instance

The defect class is runtime code in the jail's child-side modules that needs
Python 3.9 or later. The new runtime test found a second instance once the
union was fixed: `_resolve` called `Path.readlink()` (3.9+) on the `dir_fd`
path, which gave `AttributeError` on 3.8. It is now
`Path("/proc/self/fd/N").resolve()`. Ruff's PTH115 rejects `os.readlink`, so
I did not use it.

## Test (red, then green)

New file: `tests/unit/test_doc_write_jail_old_python.py`. It has two parts:

- **Static check (every host).** Each `tests/jail_site/*.py` must
  `ast.parse` at the oldest `OLD_VERSIONS` version. An AST scan also rejects
  any `isinstance`/`issubclass` whose second argument contains a `BitOr`.
  `feature_version` alone cannot catch this, because the union is valid
  syntax.
- **Runtime check (each real old interpreter).** It arms the jail over a
  tmp `CLAUDE.md`, sets `PYTHONPYCACHEPREFIX` to an empty directory (to
  match CI), and drives open-for-write, rename, remove and remove with
  `dir_fd`. It asserts four refusals, no traceback, an unchanged doc, and
  that `.pyc` files were written.

Results:

- **Red, commit 25fb24a0f:** 3 failed. These were the union scan, the
  3.8 runtime test and the 3.9 runtime test.
- **After the union fix only:** 1 failed (3.8, `Path.readlink`).
- **Green:** 39 passed. This covers the new test,
  `test_doc_write_jail.py` and `test_debug_info_old_python.py`. The last one
  also passes with an empty bytecode cache, which matches CI.

## QA

Targeted run (`llm_qa.py changed`): `QA: 37/41 PASSED, 2/41 FAILED`. Both
failures came from my own changes:

- lint PTH115 on `os.readlink`
- pyright on the `feature_version` tuple type

I fixed both and re-checked directly: ruff passes, black reports no
changes, pyright reports 0 errors, and the 39 tests pass. I did not run the
full gate again.
