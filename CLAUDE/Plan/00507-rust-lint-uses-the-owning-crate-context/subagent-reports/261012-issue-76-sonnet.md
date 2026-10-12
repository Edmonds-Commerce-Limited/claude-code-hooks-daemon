# Plan 00507 report: Rust lint uses the owning crate context (GitHub #76)

## What changed

- `strategies/lint/rust_strategy.py`: both commands now carry `--edition {edition}`. New `resolve_edition(file_path)` reads the nearest `Cargo.toml` with `tomllib`. `package.edition` wins; `edition.workspace = true` or `edition = { workspace = true }` reads the nearest ancestor `[workspace.package].edition`; a package with no edition is `2015`. No manifest, an unreadable or malformed manifest, a virtual manifest with no `[package]`, a non-string edition, an inherited edition with no workspace value, or a value outside `{2015, 2018, 2021, 2024}` all return `2021` (today's framing); the problem cases log a warning and nothing raises. `is_tool_unavailable_output` also returns True for `error[E0432|E0433|E0463|E0583]`, and still recognises the rustup shim.
- `strategies/lint/protocol.py`: new optional runtime-checkable `ProvidesCommandValues` with `command_values(file_path) -> dict[str, str]`.
- `handlers/post_tool_use/lint_on_edit.py`: `"Rust": "Cargo.toml"` added to `_MODULE_ROOT_MARKERS` (working dir is the owning crate). `_run_lint_command` builds a placeholder map (`{file}` plus whatever the strategy provides) and substitutes it per whole template element.
- Docs: `get_claude_md` paragraph, `docs/guides/HANDLER_REFERENCE.md` lint_on_edit paragraph, release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/029-rust-lint-uses-the-owning-crate-context.md`. Tasks 1.1-1.3 ticked in PLAN.md.

## Mechanism choice

The handler already splits the template on whitespace and substitutes `{file}` as one argv element. The edition is per file, but `default_lint_command` is a file-independent property, so I added an optional capability (`ProvidesCommandValues`, same shape as `NarrowsByPath` and `ClassifiesToolUnavailable`) rather than a new parameter on the whole `LintStrategy` protocol, which would force a stub on eight other strategies. Substitution happens only where a placeholder is a whole element, and the only value the Rust strategy can return is a member of the known-edition set, so manifest text never reaches argv (a test pins a hostile edition string). A user override that omits `{edition}` runs exactly as written; one that includes it is filled (both tested).

## Coordinator fix: the staged lint gate (second commit)

`staged_lint_gate._syntax_check` substituted only `{file}`, so rustc would have received a literal `{edition}` and R-STAGED-LINT-FAILURE would have denied every commit staging a `.rs` file.

- One shared helper, `build_lint_argv(template, file_path, strategy, *, effective_path=None)` in `strategies/lint/common.py`, does the whole-element substitution of `{file}` plus any `ProvidesCommandValues` values. `lint_on_edit._run_lint_command` and `staged_lint_gate._syntax_check` both call it; the handler's own copy and its `_FILE_PLACEHOLDER` constant are gone.
- The gate did not consult `ClassifiesToolUnavailable`. It now does: a non-zero exit whose output is classified could-not-analyse (E0432/E0433/E0463/E0583, the clippy shim message) returns no finding and logs a warning that the file was not checked. Syntax errors still produce a finding.
- Working directory: the gate runs with no `cwd` (the daemon's own). That is fine for a syntax check on an absolute path, since `rustc` resolves `mod x;` relative to the file, not the cwd, and the edition comes from the file's path.
- Other places that run or print a strategy template: `lint_on_edit.get_enforcement_status` uses only the first word of the extended command (the executable); `strategies/lint/__init__.py` only mentions `default_lint_command` in a docstring; acceptance tests (`get_acceptance_tests`) build Write payloads and never run a template; no script under `scripts/` runs one. The only `--edition` text in docs is the HANDLER_REFERENCE paragraph, which describes behaviour. None executes an unfilled `{edition}`.
- Tests: `tests/unit/strategies/lint/test_build_lint_argv.py` (helper fills `{edition}`, leaves an override without it unchanged, keeps hostile paths as one element); `tests/unit/handlers/pre_tool_use/test_staged_lint_gate_rust.py` (edition filled before rustc runs, could-not-analyse output is not a finding, a syntax error still is; live rustc: a staged edition-2024 crate is not denied in block mode, a staged syntax error is). Targeted run: 1149 passed across the lint strategies, post_tool_use handlers, staged gate and handler-reference check; black, ruff and mypy clean.

## Behaviour notes

- The error-code match is `error\[E....\]`, so a code mentioned in prose does not match. An output containing both a crate-context code and an unrelated error is allowed (the ruling's "any of"). E0433 also covers a typo such as an undeclared type, so those are allowed unchecked too; that is inherent to the ruling.
- The `ClassifiesToolUnavailable` advisory text says "could not analyse this file" and quotes the first output line, so it reads correctly for the new cause.
- The extended clippy tier could only be unit-tested (shim is not a working clippy here). A clippy-driver run on a crate module gets the same edition and the same classification.

## Tests

- New `tests/unit/strategies/lint/test_rust_crate_context.py`: edition reading (package, both inherited spellings, absent, malformed, unreadable, unknown, non-string, virtual manifest, nearest wins), classification of each code, syntax error and E0308 deny, shim retained.
- New `tests/unit/handlers/post_tool_use/test_lint_on_edit_rust_crate.py`: cwd is the crate, edition is one argv element, hostile edition text, loose file, both override shapes, and live rustc tests (skipped when `rustc` is absent) for the issue's reproduction (all four files allowed), a let chain denied once the manifest says 2021, a syntax error in the crate denied, loose files unchanged.
- `tests/unit/strategies/lint/test_rust_strategy.py` updated for the `{edition}` placeholder.
- Test-first ordering: I wrote the tests and the implementation in the same pass and did not run the tests red before implementing, so the RED phase was not observed. The live let-chain test (edition 2021 denies, 2024 allows) is the one that discriminates the fix.
- Targeted run: 469 passed (strategies/lint, post_tool_use handlers, handler-reference check). black (py311), ruff and mypy are clean on all touched files.
