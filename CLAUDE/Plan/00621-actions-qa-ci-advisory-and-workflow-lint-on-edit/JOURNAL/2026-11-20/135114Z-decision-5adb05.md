## 13:51 · decision · 4.1

Decision: staged_lint_gate keeps running actions-qa on staged workflows at git commit, as built (warn: advisory, block: deny on exit 1, other exits only logged). Why: the gate is the only check for a workflow that reaches the index without an edit. The fail-open WARNING log line now names the tool's own error text (first 300 chars) so the unchecked file is visible. Test added in test_staged_lint_gate_workflow.py.
