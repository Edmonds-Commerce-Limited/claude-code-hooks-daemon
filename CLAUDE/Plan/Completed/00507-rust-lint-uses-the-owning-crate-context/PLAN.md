# Plan 00507: rust lint uses the owning crate context

**Status**: Complete
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #76

## Overview

`strategies/lint/rust_strategy.py` frames every `.rs` file as a standalone
`--edition 2021 --crate-type lib` crate, and `lint_on_edit` runs `rustc` (and
`clippy-driver` for the extended tier) on that one file from the workspace
root. Cargo.toml is never read. Valid modules of a Cargo crate are therefore
denied with R-LINT-FAILURE in three cases:

- edition-2024 syntax such as let chains fails;
- `use crate::sibling` fails, because the file is its own crate root;
- an integration test that imports the crate by name, or code that imports a
  dependency, fails.

#89 reports the same defect and is closed with this plan.

Coordinator ruling, following the Go precedent in `lint_on_edit`:

- Rust gets a module-root marker, `Cargo.toml`, so the command runs from the
  owning crate.

- The edition is read from that `Cargo.toml`:

  - `package.edition` when the package sets it;
  - when it sets `edition.workspace = true`, the workspace root's
    `[workspace.package].edition`;
  - Cargo's default when no edition is set.

  A `.rs` file with no `Cargo.toml` above it keeps today's framing.

- Errors that only mean "this file cannot be resolved outside its crate" are
  classified as could-not-analyse through the existing
  `ClassifiesToolUnavailable` route, so the write is ALLOWED with an advisory.
  This is what Go gets outside a module. The errors are:

  - `E0432`, an unresolved import;
  - `E0433`, a failed path resolution or undeclared crate or module;
  - `E0463`, a crate that cannot be found;
  - `E0583`, a module file that is not found.

  Syntax errors stop `rustc` before name resolution, so they are still caught
  and still deny.

Not adopted: running `cargo check` for the owning package. A first build of the
dependencies does not fit the 15 s budget, and a timeout fails open. A
`rustfmt` parse-only check is not adopted either, because the component is often
absent; rustup ships a shim that refuses.

## Goals

- The report's reproduction is allowed: an edition-2024 crate with a let chain,
  `use crate::a::thing`, and an integration test importing the crate.
- A file with a genuine syntax error inside a Cargo crate is still denied.
- A loose `.rs` file with no Cargo.toml behaves as today.

## Non-Goals

- Running cargo, or resolving the real crate graph.
- Changing other languages.

## Tasks

### Phase 1: Fix

- [x] ✅ **Task 1.1**: RED. Tests with live `rustc` where it is installed, skipped
  with a stated reason where it is not. Mirror how existing Rust lint tests
  handle tool absence. Cover:
  - the edition read for a package, for a workspace-inherited edition, and for
    a manifest with no edition;
  - the Cargo.toml working directory;
  - classification of each crate-context error code, while a syntax error and
    a type error unrelated to resolution still deny;
  - the report's reproduction end to end through the handler;
  - a loose file unchanged.
- [x] ✅ **Task 1.2**: GREEN. Implement in `rust_strategy.py` and `lint_on_edit.py`.
  Edition parsing uses `tomllib` and must not raise on a malformed manifest: it
  falls back, logged.
- [x] ✅ **Task 1.3**: Document the Rust behaviour in the handler's user-facing
  guidance and its HANDLER_REFERENCE entry. Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [x] ✅ **Task 2.1**: Review, coordinator checks, merge; comment on and close
  #76 and #89. Merged `601ba02f9`, range-QA fix `b7552acfb`.

## Success Criteria

- [x] Valid modules of an edition-2024 Cargo crate are not denied, and a syntax
  error still is.
- [x] The behaviour is stated in the user-facing guidance.
- [x] The release-bound consequence, a behaviour change in Rust linting, is in the
  pending-release holding area as release note 029 in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Issue #76 triaged and claimed; #89 marked a duplicate.
