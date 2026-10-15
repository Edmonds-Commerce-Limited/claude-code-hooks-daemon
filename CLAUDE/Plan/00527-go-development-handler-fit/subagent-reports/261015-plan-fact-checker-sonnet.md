# Fact check: PLAN.md (00527) and GO-AUDIT.md spot-checks

Summary: 15 claims, 13 verified, 1 refuted (stale line cite), 1 unverifiable.

## REFUTED
1. GO-AUDIT.md cites lsp_enforcement.py:176-178 for the definition-keyword regex and :183-187 for the camelCase rule. In the current tree (uncommitted Phase 1 edit) the regex is at lsp_enforcement.py:253-255. Substance holds (no `func`); only the line number is stale. Plan tasks do not depend on the number.

## Table
| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | tdd source dirs /src/ /cmd/ /pkg/ /internal/ | VERIFIED | strategies/tdd/go_strategy.py:17 |
| 2 | tdd test name foo.go -> foo_test.go, per file | VERIFIED | go_strategy.py:54-56 |
| 3 | generated files not exempt, should_skip ignores content | VERIFIED | go_strategy.py:47-52 |
| 4 | error_hiding blank-identifier regex `\w+\s*,\s*_\s*:?=\s*\w` | VERIFIED | strategies/error_hiding/go_strategy.py:25 |
| 5 | empty-error-check regex | VERIFIED | same file :16 |
| 6 | lint default is `go vet {file}`, extended golangci-lint | VERIFIED | strategies/lint/go_strategy.py:11-12 |
| 7 | module_context vets whole package dir when go.mod found | VERIFIED | strategies/lint/module_context.py:83-86 |
| 8 | auto_continue_stop failure patterns pytest-shaped, no `--- FAIL` / `FAIL\t` | VERIFIED | handlers/stop/auto_continue_stop.py:619-630; `go test` at :604 |
| 9 | lsp_enforcement definition regex lacks `func` | VERIFIED (cite stale) | lsp_enforcement.py:253-255 lists class/def/function/...; no func |
| 10 | guide uses golangci `--out-format json` | VERIFIED | guides/llm-command-wrappers.md:242,250,385 |
| 11 | Rust has an E0432 carve-out to mirror | VERIFIED | strategies/lint/rust_strategy.py:50 |
| 12 | qa_suppression blocks nolint / lint:ignore only, not nosec | VERIFIED | strategies/qa_suppression/go_strategy.py:12-15 |
| 13 | No gofmt check exists | VERIFIED | grep gofmt in src *.py: no hits |
| 14 | Release note 059 exists; 00474 header names issue #59; Plan 00204 exists | VERIFIED | release-notes/059-lsp-enforcement-surveys-bare-directory-targets.md; 00474 PLAN.md:9; CLAUDE/Plan/00204-security-antipattern-dataflow-categories |
| 15 | #59 is assigned to another account; same multi-edit false deny hits Python ruff F821 (reproduced 4x) | UNVERIFIABLE-HERE | Needs `gh issue view 59` and a live reproduction; python lint default command not confirmed as F821-producing. Python extended cmd is `ruff check` (python_strategy.py:14) |
