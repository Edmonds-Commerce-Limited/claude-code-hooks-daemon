# Phase 2 report: lint_on_edit Go path

## Real go 1.19 shapes captured (scratch modules)

- `vet: ./a.go:3:12: undeclared name: syscall` (go 1.19; newer go says `undefined:`)
- `vet: ./b.go:3:8: "os" imported but not used` (newer: `imported and not used`)
- `vet: ./c.go:3:12: x declared but not used` (newer: `declared and not used`)
- genuine: `./d.go:5:12: fmt.Printf format %d has arg "s" of wrong type string` (no `vet:` prefix)
- syntax via vet: `vet: ./f.go:3:9: expected ')', found '{'`; `missing return` is also `vet:`-prefixed
- `package example.com/i: build constraints exclude all Go files in <dir>` (exit 1)
- `gofmt -l -e` syntax error exits 2 listing every error; an unformatted file prints its name and exits 0

## Design

- `strategies/lint/protocol.py`: two optional capabilities, `ClassifiesMidEditOutput.is_mid_edit_output(output, file_path)` and `HasPrecheckCommands.precheck_lint_commands`.
- `go_strategy.py`: mid-edit = every located finding is either in a sibling file (2.2) or the unresolved-name class on the edited file (2.1); one genuine finding on the edited file, or output with no located finding, denies. The `build constraints exclude all Go files` marker joins the tool-unavailable markers (2.3). `gofmt -l -e {file}` is a precheck (2.4).
- `lint_on_edit.py`: prechecks run first and only a DENY ends the run; a mid-edit result is an ALLOW whose context carries the full vet output.

## gofmt: advisory vs deny

A syntax error denies. An unformatted file is neither denied nor reported: `gofmt -l` exits 0 for it, and this repo does not deny on style at edit time for other languages (ruff check, not ruff format; formatting is the autofix step's job). Reporting it would need new plumbing for exit-0 output, which is not justified yet.

## Not done / notes

- `staged_lint_gate` is unchanged on purpose: at commit time an unresolved name is a real error.
- The Python ruff F821 two-edit false deny is NOT carved out here; the carve-out is language-wide only in mechanism (the protocol), not applied to Python.
- Missing return is deliberately still a deny (not the unresolved-name class).
- If gofmt is missing the precheck advisory is dropped so vet still runs.
- Release note: `CLAUDE/UPGRADES/UNRELEASED/release-notes/061-lint-on-edit-go-no-longer-denies-half-a-change.md`.
- Tests: `tests/unit/strategies/lint/test_go_strategy.py`, `tests/unit/handlers/post_tool_use/test_lint_on_edit_go.py` (28 failed first; live tests use the real toolchain).
