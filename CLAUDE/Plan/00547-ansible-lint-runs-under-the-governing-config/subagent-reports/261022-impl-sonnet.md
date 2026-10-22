# Plan 00547 implementation report (GitHub #128)

## Red output (before any source change)

- `tests/unit/strategies/lint/test_module_context_governing_config.py`: collection error,
  `ImportError: cannot import name 'GoverningConfigError' from ...strategies.lint.module_context`.
- `tests/unit/handlers/test_ansible_governing_config_gates.py` and
  `tests/unit/config/test_layout_ansible_configs.py`: every test failed with
  `TypeError: ProjectLayout.__init__() got an unexpected keyword argument 'ansible_configs'`.
- The no-declaration agreement test (`TestNoDeclarationAgreesOnTheWorkspaceRoot`) encodes the
  original defect: before the change the commit gate passed `cwd=None` and lint_on_edit the
  workspace root. It could not run red on its own because the layout field did not exist yet.

## Design

- One declaration, `layout.ansible_configs` (play glob to repo-relative `ansible.cfg`), in
  `LayoutConfig` (validated repo-relative, no absolute or `..`), carried by `ProjectLayout`
  (root via `from_config`, declared projects via `for_project`). Both handlers read it through
  `self.layout_for(file_path)`, so it is not duplicated on either handler.
- Decided once in `strategies/lint/module_context.py`: `resolve_module_context(..., project_root, ansible_configs)`. A matching glob wins over the marker walk: module root is the config's
  directory, `governing_config` is set, `env` carries `ANSIBLE_CONFIG`. A declared file that does
  not exist raises `GoverningConfigError`; lint_on_edit denies with it, the commit gate fails the
  file with it. Glob dialect is the shared `path_matches_globs`.
- `ModuleContext.working_dir(workspace_root)` is the single fallback: module root else workspace
  root. Both gates use it. The commit gate takes the root from `resolve_project_root()` (file's
  directory only when no ProjectContext, same as lint_on_edit).
- `missing_config_note()`: a FAILED Ansible check with no governing config still denies, with one
  extra line "no ansible.cfg was in effect ... Declare ... layout.ansible_configs". Timeouts and
  missing tools keep their own paths.
- `env` is passed to `subprocess.run` only when non-empty (otherwise `None`), so other languages
  are unchanged apart from the commit gate now running from the project root, not the daemon cwd.
- Docs: `docs/guides/HANDLER_REFERENCE.md` (layout section, hand-written, not generated),
  `LayoutConfig` docstring, `lint_on_edit.get_claude_md`. Release note
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/018-ansible-lint-runs-under-the-governing-config.md`
  (renumbered from 017 at the coordinator's request; audience `client projects`, the shape check
  requires one of the four fixed values).

## QA

Final run: `QA: 39/40 PASSED, 1/40 FAILED`. The one failure is
`test_safety_handlers_hostile_input_performance.py::...test_bash_command[double_star_glob]`, a
timing test unrelated to this change; it passes alone (`2 passed`) and failed under load in the
QA run. An earlier run's format, magic_values and release-note-shape failures were fixed.
Note: the worktree venv points at main's src, so tests were run with `PYTHONPATH=<worktree>/src`.

## Commits

- 2f2125205 (code, tests, docs, release note). The report commit follows.
