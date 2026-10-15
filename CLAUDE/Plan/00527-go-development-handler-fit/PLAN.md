# Plan 00527: go development handler fit

**Status**: In Progress
**Created**: 2026-10-15
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked the desktop team (fedora-desktop, md-viewer) to make sure the daemon works well for Go development.
Every handler on the Go path has a Go strategy, but several fire on ordinary, idiomatic Go. The worst cases are a
per-file TDD gate in a per-package test language, a blank-identifier rule that blocks map lookups and type assertions,
and a per-edit `go vet` that denies the first half of any change split across two edits.

The evidence is a read-only audit with file:line citations, [GO-AUDIT.md](GO-AUDIT.md), plus field reports from the
fedora-desktop seat on daemon v3.69.0. The owner's direction for Go QA tooling, relayed by fedora-desktop: the daemon's
Go handlers assume only the plain Go toolchain (`gofmt`, `go vet`, `go test`). `go-qa` or `golangci-lint` may add to
them where present, but must never be required.

Two unrelated niggles found in the same session could not go into the open ledger (00474 is tied to issue #59, which is
assigned to another account). They are recorded in [NIGGLES-FOUND.md](NIGGLES-FOUND.md).

## Goals

- Idiomatic Go raises no false deny from tdd_enforcement, error_hiding_blocker, lint_on_edit, qa_suppression or
  comment_size, with each false-positive form pinned by a test that failed first.
- Nothing in the Go path requires a tool beyond the Go toolchain.
- Go test failures are recognised wherever pytest failures are.

## Non-Goals

- New Go security categories that need data-flow analysis (SQL built with `Sprintf`): that is Plan 00204's ground.
- Installing or pinning Go QA tools: go-qa-ci owns that (fedora-desktop is building self-install).

## Tasks

### Phase 1: lsp_enforcement directory targets (field report)

- [x] ✅ **Task 1.1**: A grep/rg (or Grep `path`) whose targets are all directories and that names no file type is
  judged by a bounded survey of the files those directories hold, so a YAML-only tree is not covered by a Python
  server. An undecided survey (too large, unreadable) keeps the old answer.

### Phase 2: per-edit lint is syntax-and-format, package checks move later

- [x] ✅ **Task 2.1**: TDD: a change split across two edits (call, then import) draws no deny on the first edit. The
  candidate design runs `gofmt -l -e` per edit and treats `go vet`'s unresolved-name class (`undefined:`, imported and
  not used) as advisory, mirroring Rust's E0432 carve-out. The same multi-edit false deny hits Python (ruff F821) and
  was reproduced four times in this session, so decide whether the carve-out is language-wide.
- [x] ✅ **Task 2.2**: A findings-only-in-sibling-files `go vet` result is advisory, not a deny of this write.
- [x] ✅ **Task 2.3**: "build constraints exclude all Go files" is a recognised advisory marker.
- [x] ✅ **Task 2.4**: Add a `gofmt` check (toolchain-only); no default needs golangci-lint.

### Phase 3: tdd_enforcement for per-package tests

- [x] ✅ **Task 3.1**: A new `.go` file in a package that already has any `_test.go` passes.
- [x] ✅ **Task 3.2**: Generated files are exempt: the `// Code generated ... DO NOT EDIT.` header, plus `*.pb.go`,
  `*_gen.go`, `zz_generated*`.
- [x] ✅ **Task 3.3**: `doc.go` and `cmd/*/main.go` pass; root-level and other top-level packages are enforced
  (the `/src/ /cmd/ /pkg/ /internal/` allow-list misses them).

### Phase 4: error_hiding_blocker Go precision

- [x] ✅ **Task 4.1**: `v, _ := m[k]`, `x, _ := y.(T)`, `for i, _ := range` and `_, _ = fmt.Fprintf` pass; matches
  inside comments and string literals are ignored.
- [x] ✅ **Task 4.2**: Catch `if err != nil { // ignore }` (comment-only body; the multi-line form, since the
  one-line form puts the closing brace inside the comment and is not valid Go).

### Phase 5: smaller items

- [x] ✅ **Task 5.1**: qa_suppression: decide whether `//nolint:<linter> // <reason>` is allowed; cover `//nosec`.
- [x] ✅ **Task 5.2**: comment_size: a Go package doc comment in `doc.go` is exempt or has its own limit.
- [x] ✅ **Task 5.3**: auto_continue_stop recognises `--- FAIL:` and `FAIL\t<pkg>`.
- [x] ✅ **Task 5.4**: lsp_enforcement treats `func X` as a definition search.
- [x] ✅ **Task 5.6**: lsp_enforcement's one-named-file exemption also exempts a single bare directory target
  (`rg x src/pkg`, no trailing `/`), which rg searches recursively. Judge it as a directory: with the Phase 1
  survey, a directory holding no served file is still only advised.
- [x] ✅ **Task 5.5**: `guides/llm-command-wrappers.md`: replace golangci-lint v1's `--out-format json`.

## Success Criteria

- [ ] Every false-positive form listed in GO-AUDIT.md and the field reports is pinned by a test that failed first.
- [ ] The fedora-desktop and md-viewer seats confirm, after upgrading, that no Go-path misfire remains.
- [ ] Release-bound consequences recorded in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` (Phase 1: note 059).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00527-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Phase 1 (lsp_enforcement directory survey): this plan's first commit.
