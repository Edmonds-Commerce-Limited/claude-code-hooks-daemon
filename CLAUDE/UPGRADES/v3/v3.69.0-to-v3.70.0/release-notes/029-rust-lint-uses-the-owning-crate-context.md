# Callout: `lint_on_edit` checks a Rust file as a module of its own crate, so valid modules of an edition-2024 crate are no longer denied

**Plan**: 00507
**Audience**: operators

`lint_on_edit` compiled every `.rs` file as a standalone edition-2021 library, so a let chain, a `use crate::sibling`, or an integration test importing its crate was denied with `R-LINT-FAILURE` although the code was valid. `rustc` now runs from the nearest `Cargo.toml` with that crate's edition (`package.edition`, the workspace's `[workspace.package].edition`, or Cargo's default of 2015); a file with no `Cargo.toml` keeps edition 2021. An unresolved import, path, crate or module file (`E0432`, `E0433`, `E0463`, `E0583`) now ALLOWs with an advisory that the file was not checked when every error in the output is of that kind; syntax errors and other compiler errors still deny, including when they appear alongside an unresolved import. A `command_overrides` template may use `{edition}` as a whole argument; one without it runs as written, and no configuration change is needed (reported as issue #76, duplicate #89).
