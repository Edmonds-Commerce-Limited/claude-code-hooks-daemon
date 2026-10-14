# Plan 00525: staged lint gate runs go vet from the module root

**Status**: In Progress
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #118

## Overview

`staged_lint_gate` says it runs the same cheap syntax check as `lint_on_edit`,
but for Go it does not. `lint_on_edit` finds the nearest `go.mod`
(`_find_module_root`), runs `go vet` from that directory, and vets the
package directory (`./<pkg>/`). `staged_lint_gate._syntax_check` runs
`go vet <file>` with no `cwd`, from the daemon's working directory. A Go file
in a nested module (a `go.mod` in a subdirectory) that imports its own
module's packages therefore fails to resolve the import.

Plan 00507 made the gate honour the strategy's could-not-analyse output, which
recognises `go.mod file not found` and `cannot find main module`. That covers
the wording in the report, but other Go versions word it differently.
Reproduced on this host (Go 1.19): `go vet sub/app/app.go` from the repository
root exits 1 with `package m/util is not in GOROOT`. That wording is not
recognised, so a correct commit is still denied. Even where it is recognised,
the file passes unchecked rather than being vetted.

## Goals

- The gate vets a Go file from its module root and package directory, exactly
  as `lint_on_edit` does, through one shared resolver rather than a copy.
- A correct nested-module package commits; a real `go vet` finding in it still
  denies.

## Non-Goals

- Changing `lint_on_edit`'s Go behaviour.
- Other languages' working directories, unless the shared resolver is the
  natural place for them; if so, report it rather than widen the scope.

## Tasks

### Phase 1: Fix (TDD)

- [x] ✅ **Task 1.1**: RED: a nested-module repository fixture (`go.mod` in a
  subdirectory, a package importing a sibling package by module path). A
  correct commit is allowed; a commit with a real vet finding (e.g. a
  `fmt.Printf` format mismatch) is denied and names the file. Skip cleanly
  when `go` is absent.
- [x] ✅ **Task 1.2**: GREEN: extract `lint_on_edit`'s module-root and
  effective-path resolution into a shared helper, and use it in both
  handlers. The gate passes `cwd` to `subprocess.run`.
- [x] ✅ **Task 1.3**: Add a release note.

## Success Criteria

- [ ] A correct nested-module Go commit is allowed and a real vet finding is
  denied, proven by tests that failed first.
- [ ] Release-bound consequences recorded in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00525-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by the issue-sdlc loop from #118. Prior art: Plan 00507 (the Rust
  owning-crate context and could-not-analyse handling).
