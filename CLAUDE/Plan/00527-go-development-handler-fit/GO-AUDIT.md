# Go support audit: claude-code-hooks-daemon

All paths are relative to `/workspace/src/claude_code_hooks_daemon/`. I excluded `tests/fixtures/cyber-flag` from every search.

## 1. tdd_enforcement
**Go-specific behaviour** (`strategies/tdd/go_strategy.py`)
- Source dirs are `/src/`, `/cmd/`, `/pkg/` and `/internal/` (`:17`).
- Skipped dirs are `vendor/` and `testdata/` (`:18`, used at `:51-52`).
- Test files are `*_test.go`, plus anything under `tests/`, `test/`, `__tests__/` or `spec/` (`:37-42`, `strategies/tdd/common.py:9-14`).
- Expected test name is `foo.go` → `foo_test.go` (`:54-56`).
- No file is ever excluded by name (`:47-49`).

**Handler** (`handlers/pre_tool_use/tdd_enforcement.py`)
- It only acts on Write (`:364`) and only when creating a new file; overwriting an existing file is ignored (`:393`).
- Collocated tests are searched by default (`:63-65`, `:584-588`, `:869-874`).
- The write is allowed if any candidate test file exists (`:485-490`).
- A `_test.go` file is never gated (`:445`).

**Gaps**
- **False positives on new files in a tested package.** Go tests per package, not per file. Writing `server_routes.go` when only `server_test.go` exists is denied. Each of these is also forced to have a matching test file:
  - `doc.go`
  - `cmd/x/main.go`
  - `types.go`
  - `errors.go`
- **No exemption for generated files** (`:47-49`). `should_skip` receives the file content but ignores it (`:51-52`), so the standard `// Code generated ... DO NOT EDIT.` header is not checked. These all get blocked:
  - `*.pb.go`
  - `*_gen.go`
  - `zz_generated*.go`
  - `mock_*.go`
  - `*_string.go`
- **False negatives from the directory allow-list.** The very common layouts are not enforced at all:
  - library packages at the repo root
  - top-level package dirs such as `api/`, `server/`, `handler/`
- **Anything under `test/` or `tests/` counts as a test.** For example, `test/e2e/helpers.go` is classed as a test file.
- `vendor/` and `testdata/` are handled correctly, and a `_test.go` file itself is never gated.

## 2. lint_on_edit (PostToolUse)
- The default command is `go vet {file}`; the extended command is `golangci-lint run {file}` (`strategies/lint/go_strategy.py:11-12`).
- **Inside a module** (go.mod found), it vets the whole package directory from the module root (`strategies/lint/module_context.py:69-86`, marker at `:138-142`). At the module root this becomes `.//`. A test pins that string (`tests/unit/strategies/lint/test_module_context.py:42-47`), but I did not check that real `go vet` accepts it.
- **Outside a module**, "cannot find main module" and "go.mod file not found" become an advisory ALLOW (`go_strategy.py:21-24`, `:54-64`; `lint_on_edit.py:463-487`).
- **Missing `go` or `golangci-lint`:** `shutil.which` fails, and the result is an advisory ALLOW, "lint tool not found" (`lint_on_edit.py:389`, `:430-440`, `:496-503`). The daemon's own PATH may not include `/usr/local/go/bin` or `~/go/bin`. It also runs golangci-lint automatically whenever it's installed, after vet passes (`:307-312`).
- A timeout fails open (`:505+`).

**Gaps**
- **No gofmt or goimports check, and no staticcheck default.**
- **Vetting the whole package denies on problems you didn't introduce:**
  - pre-existing findings in sibling files
  - type errors partway through a multi-file change (a file using a symbol you haven't written yet)

  Rust gets an "unresolvable outside its crate means advisory" carve-out (E0432 etc.); Go has no equivalent. golangci-lint run on a package has the same problem, and is slow.
- **Build-tag handling.**
  - A `//go:build windows` file is silently skipped on Linux.
  - A package made up only of such files gives "build constraints exclude all Go files", which is not a recognised marker, so the write is denied.
- **GOTOOLCHAIN.** If go.mod needs a newer toolchain, `go` may try to download one, which can end in a timeout.

## 3. error_hiding_blocker (`strategies/error_hiding/go_strategy.py:13-29`)
There are two rules:
- `if\s+err\s*!=\s*nil\s*\{\s*\}`
- `\w+\s*,\s*_\s*:?=\s*\w`

The handler runs `re.search` over the raw new content (Write `content` or Edit `new_string`), with no stripping of comments or strings (`handlers/pre_tool_use/error_hiding_blocker.py:256-276`).

How the second rule treats common Go forms:

| Code | Blocked? | Verdict |
|---|---|---|
| `v, _ := m[key]` | Yes | False positive |
| `x, _ := y.(T)` | Yes | False positive |
| `for i, _ := range xs` | Yes | False positive (gofmt -s style) |
| `_, _ = fmt.Fprintf(w, …)` | Yes, since `_` matches `\w` | False positive on the explicit-discard idiom errcheck accepts |
| `n, _ := strconv.Atoi(s)` | Yes | Intended, sometimes legitimate |
| `a, b, _ := f()` | Yes | Intended |
| `v, ok := x.(T)` | No | Correct |
| `for _, v := range` | No | Correct |
| `_, err :=` | No | Correct |
| `x, _, err :=` | No | Correct |
| `v, _ := <-ch` | No, because `<` is not `\w` | Correct, by luck of the regex |

Other gaps:
- It matches inside comments, string literals and raw backtick strings.
- `*_test.go` and `testdata/` are not excluded; only `tests/fixtures`, `tests/assets`, `__fixtures__` and vendored dirs are (`error_hiding_blocker.py:65-82`). Tests commonly use `x, _ :=`.
- An Edit whose `new_string` carries unchanged existing code is blocked for that code.
- Missed true positives:
  - `if err != nil { // ignore }` (a comment in the body)
  - `if err != nil { return nil }`
  - `_ = f()`
  - `defer f.Close()`

## 4. Other handlers
- **qa_suppression** (`strategies/qa_suppression/go_strategy.py:12-19`)
  - Blocks `//\s*nolint` and `//\s*lint:ignore`, case-insensitive, skipping `vendor/` and `testdata/`.
  - It blocks even justified `//nolint:errcheck // reason`, with no allowance for a reason.
  - It misses `//nosec` / `#nosec` (gosec), `//revive:disable` and `//golangci-lint:ignore`.
  - It also matches inside strings.
- **security_antipattern** (`strategies/security/go_strategy.py:15-34`)
  - Only `template.HTML(`, `template.JS(` and `template.URL(` are caught (`template.CSS` and `template.HTMLAttr` are not); the universal secret strategy also applies.
  - Missing:
    - `exec.Command("sh","-c",…)` / `bash -c`
    - `fmt.Sprintf` into `db.Query` / `Exec` (SQL injection)
    - `InsecureSkipVerify: true`
    - `math/rand` used for secrets
    - `md5` / `sha1`
    - `unsafe`
    - `text/template` for HTML
- **comment_changelog / comment_size** (`strategies/comments/go_strategy.py:32-33`, `syntax.py:71-78`)
  - Uses `SLASH_SYNTAX`, with no doc-comment exemption.
  - Go doc comments are `//` lines, so a long package doc in `doc.go` (over 40 lines, `comment_size.py:63-64`) is denied when it grows.
  - `//go:build`, `//go:generate` and `//go:embed` directives are treated as ordinary comments.
- **lsp_enforcement**
  - Maps `rg -t go` (`lsp_enforcement.py:86`).
  - The definition-keyword regex has `function` but not `func`, so `func Foo` is not caught as a definition (`:176-178`); `type Foo` is.
  - Go camelCase and single-word identifiers are not caught; only PascalCase with at least two segments and snake_case are (`:183-187`).
- **lsp_noise** (`strategies/lsp_noise/go_strategy.py:55-87`) is gopls-aware and handles go.mod scoping well. It is advisory only.
- **pipe_blocker** (`strategies/pipe_blocker/go_strategy.py:8-12`)
  - Blacklists `^go test`, `^go build` and `^go vet`.
  - Every unrecognised producer is denied anyway, so this only changes the wording of the message.
  - `go run`, `go generate`, `golangci-lint`, `staticcheck` and `CGO_ENABLED=0 go test` fall through to the "unknown command" message, which offers a whitelist suggestion.
- **sed_blocker** has no Go relevance.

## 5. QA / guidance
- `guides/llm-command-wrappers.md:238-275` has Go wrappers: `go test -json`, and golangci-lint `--out-format json`. That flag was removed in golangci-lint v2; the replacement is `--output.json.path`.
- `handlers/pre_tool_use/verification_result_gate.py:120-121` covers `golangci-lint` and `go vet`, but not `go test`, `go build` or `staticcheck`.
- `handlers/stop/auto_continue_stop.py:604` recognises `go test`. But its failure patterns (`:619-630`) are pytest-shaped. `^FAILED\b` does not match Go's `--- FAIL:` or `FAIL\tpkg`, so Go test failures are not detected.

## 6. Test coverage with Go cases
- **Strategy tests** (`tests/unit/strategies/`):
  - `tdd/test_go_strategy.py`
  - `lint/test_go_strategy.py`
  - `lint/test_module_context.py`
  - `error_hiding/test_go_strategy.py`
  - `qa_suppression/test_go_strategy.py`
  - `security/test_go_strategy.py`
  - `comments/test_go_strategy.py`
  - `pipe_blocker/test_go_strategy.py`
  - `lsp_noise/test_go_strategy.py`
- **Handler tests:**
  - `tests/unit/handlers/test_tdd_enforcement.py` (around 792-1168)
  - `tests/unit/handlers/pre_tool_use/test_error_hiding_blocker.py:228-248`
  - `tests/unit/handlers/pre_tool_use/test_qa_suppression.py`
  - `tests/unit/handlers/pre_tool_use/test_staged_lint_gate_go.py`
  - `tests/unit/handlers/post_tool_use/test_lint_on_edit*.py`
  - `tests/unit/handlers/pre_tool_use/test_review7_false_positive_corpus.py:63-64`
  - `tests/unit/handlers/pre_tool_use/test_lsp_enforcement.py`
  - `tests/integration/test_pipe_blocker_integration.py`
- **Untested:**
  - error_hiding: map lookup, type assertion, `_, _ = fmt.Fprintf`, `for i, _ := range`, channel receive (only `_, _ := f()` is pinned as a match)
  - TDD: generated files, root-level packages, `cmd/` main files
  - lint: build tags

---

**Summary: top Go gaps, ranked by likely developer pain**

1. **TDD gate wants one `_test.go` per new file** (`tdd/go_strategy.py:54`). Go tests per package, so new `routes.go`, `doc.go`, `main.go` or `errors.go` files are denied even when the package has tests.
2. **TDD has no generated-file exemption** (`:47-52`). `*.pb.go`, `*_gen.go`, `zz_generated*` and mocks are blocked; the "Code generated" header is never checked.
3. **error_hiding blank-identifier regex has false positives** (`error_hiding/go_strategy.py:25`): `v, _ := m[k]`, `x, _ := y.(T)`, `for i, _ := range`, `_, _ = fmt.Fprintf`. It scans comments, strings and `_test.go` files, and misses `if err != nil { //ignore }`.
4. **lint_on_edit vets the whole package** (`module_context.py:83-86`). Sibling-file findings and half-finished multi-file edits deny; there's no Rust-style unresolved-symbol carve-out; build-tag-only packages deny; there's no gofmt check.
5. **qa_suppression blocks every `//nolint`**, even with a reason, and misses `//nosec` / `#nosec`.
6. **comment_size has no Go doc-comment exemption**, so long `doc.go` package docs are denied.
7. **auto_continue_stop doesn't detect Go test failures**: its patterns are pytest-shaped (`:619-630`), so `--- FAIL` / `FAIL\tpkg` are missed.
8. **security covers only `template.HTML`, `template.JS` and `template.URL`.** No `exec.Command` with `sh -c`, no SQL built with `Sprintf`, no `InsecureSkipVerify`.
9. **TDD source-dir allow-list** (`:17`) skips root-level and other top-level packages entirely.
10. **Smaller items:** the guide's golangci-lint `--out-format` flag is gone in v2; lsp_enforcement misses `func X`; pipe_blocker's Go list only changes wording.
