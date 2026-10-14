# Plan 00525 sub-agent report: staged_lint_gate vets Go from its module root

## RED

`tests/unit/handlers/pre_tool_use/test_staged_lint_gate_go.py` (nested module `sub/` with `sub/util`
and `sub/app`, no root go.mod, skipped when `go` is absent):

- Correct package: `AssertionError: BLOCKED [R-STAGED-LINT-FAILURE] ... assert <Decision.DENY: 'deny'> == 'allow'`
  (Go 1.19: `package m/util is not in GOROOT`, not recognised as could-not-analyse).
- Vet-finding case passed already, for the wrong reason (same GOROOT error). Tightened it to
  require `Printf` in the reason and no `# m/app` banner, which is the real finding.
- `tests/unit/strategies/lint/test_module_context.py` failed at collection (module absent).

## GREEN

- New shared resolver `src/claude_code_hooks_daemon/strategies/lint/module_context.py`
  (`MODULE_ROOT_MARKERS`, `find_module_root`, `resolve_module_context` -> `ModuleContext`).
- `lint_on_edit` uses it (its `_find_module_root` and `_MODULE_ROOT_MARKERS` removed). Behaviour unchanged.
- `staged_lint_gate._syntax_check` passes `effective_path` and `cwd=module_root`.
- Package-mode `go vet` output leads with `# m/app`; added `_headline()` so the finding line names the file.
- Existing tests that referenced the removed handler members (3 files) now import from the shared module.
- Release note 059; plan tasks 1.1 to 1.3 ticked; Success Criteria untouched.

## Disagreement / scope note

The shared resolver also applies to Ansible and Rust in the gate (cwd = `ansible.cfg` / `Cargo.toml`
directory, path unchanged), because the gate claims parity with lint_on_edit and a Go-only branch would be
a special case. Existing Rust gate tests stay green. Noted in the release note. Say if you want it Go-only.

## QA

`./scripts/qa/llm_qa.py changed` first run: exit 1 (format needed fixing by `run_autofix.sh`; the two
edited handlers reported `too-broad` unmapped). Re-run with `--allow-unmapped`: exit 0, 40/40 PASSED,
changed_tests 2244 passed, 0 failed, 5 skipped.
