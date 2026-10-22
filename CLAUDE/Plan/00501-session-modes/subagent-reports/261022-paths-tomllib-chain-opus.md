# paths.py tomllib chain (main CI red after Plan 00501 Phase 1)

Branch `worktree-paths-tomllib-chain`, fix commit `9ec43c206` (pushed). Not merged.

## Red reproduced

`tests/unit/daemon/test_paths_import_under_310.py::test_paths_imports_when_tomllib_unavailable`
failed at a04878079 with `ModuleNotFoundError: import of tomllib halted`.

## Exact chain (from the traceback, tomllib blocked via sitecustomize)

```
daemon.paths (import_module)
-> claude_code_hooks_daemon/__init__        (core.front_controller)
-> core/__init__                            (core.data_layer)
-> core/data_layer                          (core.session_mode_registry)   <- Plan 00501 Phase 1
-> core/session_mode_registry               (utils.session_modes)
-> utils/session_modes                      (skill_scan.constants)
-> skill_scan/__init__                      (skill_scan.pipeline)          <- the real seam
-> skill_scan/pipeline -> digest -> utils/claude_plugins -> utils/markdown_format
-> mdformat -> mdformat._compat -> import tomllib
```

`skill_scan.constants` and `skill_scan.extraction` are themselves light; it is
the package `__init__` that eagerly re-exported `pipeline` / `models` names.

## Fix

`src/claude_code_hooks_daemon/skill_scan/__init__.py` now imports nothing
(docstring only, explaining why). No caller in src/tests/scripts imports any
name from the package root, nor uses `skill_scan.<name>` attribute access; every
consumer (`daemon/cli.py`, `handlers/session_start/skill_opportunity_detector.py`,
`utils/session_modes.py`, `utils/human_presence.py`, tests) imports submodules.
Behaviour identical. No function-local imports added; `session_modes` unchanged.

Post-fix trace with tomllib blocked: `utils.session_modes` and
`skill_scan.extraction` load, `skill_scan.pipeline` and `mdformat` do not.

## Verification

- Target test file + `tests/unit/utils/test_session_modes.py`,
  `tests/unit/core/test_session_mode_registry.py`, `tests/unit/skill_scan/`,
  `tests/unit/utils/test_autonomy.py`, `tests/unit/core/test_chain_autonomy_gate.py`,
  `tests/unit/utils/test_human_presence.py`: all pass.
- Sibling old-Python guards (`test_paths_check_venv_fresh_under_310.py`,
  `test_paths_resolve_venv_under_any_python.py`, `test_old_python_provisioning.py`,
  `core/test_project_layout.py`, `test_paths_python_discovery.py`): pass.
- Targeted QA: `QA: 41/41 PASSED` (no autofixes).

## Is this a class?

Yes. The class is "a package `__init__` with eager re-exports turns any import of
a light submodule into an import of the whole package", combined with the fact
that `paths.py`'s module chain runs the top-level package `__init__`, which
imports `core` -> `data_layer` -> anything the data layer grows a dependency on.
Every new data-layer dependency silently lengthens the pre-3.11 import surface.

Detector status: `test_paths_imports_when_tomllib_unavailable` is the only guard
that catches this. The sibling under-3.10 tests were GREEN on red main, because
they run `paths.py` as a file (no package `__init__`), so they do not exercise
the package chain. The existing test is correct and sufficient as a detector;
it is just late (fires in CI after merge, not at edit time).

Other old-Python-guarded modules: none share the new chain — the siblings all
execute `paths.py` standalone, and the doc-write jail (Plan 00546) is a separate
site directory.

## Suggested cheaper/broader guard (not built)

1. A unit test asserting that importing `claude_code_hooks_daemon.core.data_layer`
   (or the top-level package) under a `sys.modules['tomllib'] = None` site does
   not load `mdformat` / `skill_scan.pipeline`, naming the offending edge in the
   failure. Same cost as the existing test but localised to the data layer,
   which is where the chain grows.
2. Broader: a structural test that every package `__init__.py` under `src/` that
   is reachable from `daemon.paths` has no eager re-exports of heavy submodules
   (or simply: `skill_scan/__init__.py` stays import-free). Cheaper option: make
   the existing test's failure message print the import chain (it already does
   via the traceback), and add `core.data_layer` to the plan's checklist for any
   new registry dependency.
3. Consider whether `daemon.paths` should stop importing via the package root at
   all (the CLI helpers already work as a standalone file); that would remove
   the class entirely but is a larger change.
