# Callout: lint_on_edit no longer denies the first half of a Go change

**Plan**: 00527
**Audience**: client projects

`lint_on_edit` ran `go vet` on the edited package after every Edit, so a change that needs two edits (add a call, then its import) was denied after the first: `vet: x_test.go:48:12: undefined: syscall`. Now:

- `go vet` findings in the unresolved-name class on the edited file (`undefined:` / `undeclared name:`, `imported and not used` / `imported but not used`, `declared and not used` / `declared but not used`) are an advisory ALLOW that shows the finding. Genuine findings (printf misuse, unreachable code, a syntax error, a missing return) still deny.
- A `go vet` finding located only in a sibling file is an advisory, not a deny of the file you just wrote.
- `build constraints exclude all Go files` (every file in the package carries a build tag) is an advisory, not a deny.
- A `gofmt -l -e` syntax check now runs first on the edited file and denies a syntax error. An unformatted file is not denied (formatting is left to the autofix step, as for other languages). It needs only the Go toolchain; `golangci-lint` stays an optional extended tier.

The commit-time `staged_lint_gate` is unchanged: a half-made change is still refused at commit.
