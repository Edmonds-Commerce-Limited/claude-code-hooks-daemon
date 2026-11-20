## 00:56 · action · — — Task 2.1 built; staged_lint_gate gap closed

Task 2.1 (slice 1) built, test first, against a stub `actions-qa` on PATH.

- Registry holds a list of strategies per extension. `register()` refuses sharing unless every strategy on the extension implements `NarrowsByPath` (both directions: a non-narrowing newcomer, and any newcomer onto a non-narrowing owner), and checks before recording so a refusal changes nothing. `filter_by_languages` drops individual strategies and empty keys.
- Protocol gains `DeclaresFindingsExitCodes` and `DeclaresOptionalTool`; `common.py` has `is_findings_exit` and `lint_tool_is_optional`, the one answer both lint gates read.
- `lint_on_edit`: a non-findings exit allows with a "NOT checked" advisory quoting the first output line; an optional tool missing (unresolvable OR FileNotFoundError at launch) returns no result and prints nothing. `get_acceptance_tests` now iterates `strategies()` instead of the registry's private dict.
- `GitHubWorkflowLintStrategy` (`actions-qa check --file {file}`, findings code 1, optional, path-only `handles_file`: parent `workflows`, grandparent `.github`) registered after Ansible.

Gap in DESIGN.md: `staged_lint_gate` shares the registry and treated every non-zero exit as a diagnosis, so an exit 2/3/4 on a staged workflow would have failed the commit. It now applies `is_findings_exit` too (stub test added).

Left for later slices / Task 1.1: `lint_on_edit.get_claude_md` still says workflows are left alone (Task 2.3). The Ansible acceptance probe "a GitHub workflow is not claimed" (content `jobs: {}`) and the new strategy's ALLOW probe may DENY on a host with the real linter installed; check both when Task 1.1 runs the tool.
