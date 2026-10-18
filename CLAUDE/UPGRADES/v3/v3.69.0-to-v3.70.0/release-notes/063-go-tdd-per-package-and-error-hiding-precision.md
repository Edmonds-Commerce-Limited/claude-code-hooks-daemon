# Callout: Go TDD gate works per package, and error_hiding_blocker stops flagging comma-ok forms

**Plan**: 00527
**Audience**: client projects

Two Go handlers fired on ordinary, idiomatic Go. `tdd_enforcement` demanded one `_test.go` per new file although Go tests per package, and only looked in `src/`, `cmd/`, `pkg/` and `internal/`. It now passes a new `.go` file when its directory already holds any `*_test.go`, exempts generated files (the `// Code generated ... DO NOT EDIT.` header, `*.pb.go`, `*_gen.go`, `zz_generated*`), `doc.go` and `cmd/<name>/main.go`, and enforces every other `.go` file inside a module (a `go.mod` at or above it), including root-level and `api/`-style packages. A `.go` file with no `go.mod` above it is no longer gated. `error_hiding_blocker` now ignores `v, _ := m[k]`, `x, _ := y.(T)`, `for i, _ := range xs`, `_, _ = fmt.Fprintf(...)` and anything inside comments or string literals, still blocks a blank last value from a function call (`n, _ := strconv.Atoi(s)`), and newly blocks an `if err != nil` whose body is only a comment.
