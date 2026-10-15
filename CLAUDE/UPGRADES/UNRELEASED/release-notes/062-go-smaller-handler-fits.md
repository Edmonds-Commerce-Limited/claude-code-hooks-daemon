# Callout: Go development gets six smaller handler fixes

**Plan**: 00527
**Audience**: client projects

- `qa_suppression` also blocks gosec's `//nosec` and `#nosec`. `//nolint` stays blocked even with a stated reason: a suppression is a human's conscious decision.
- `comment_size` treats a Go package doc comment (the comment block directly above the `package` clause, usually in `doc.go`) as API documentation, so it is exempt from the size limit. Every other Go comment keeps the limit, and `comment_changelog` still reads the package doc.
- `auto_continue_stop` recognises Go test failures (`--- FAIL: TestX`, `FAIL`, `FAIL<TAB><pkg>`) wherever it recognises pytest's.
- `lsp_enforcement` treats `func Name` as a definition search, like `def name`.
- `lsp_enforcement`'s one-named-file exemption no longer exempts a bare directory target such as `rg x src/pkg`: rg searches it recursively, so it is judged like any directory search.
- The `llm-command-wrappers` guide uses golangci-lint v2's `--output.json.path` (v1's `--out-format json` was removed in v2) and says golangci-lint is optional; `gofmt -l`, `go vet` and `go test -json` are the baseline.
