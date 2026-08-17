#!/bin/bash
#
# Single source of truth for WHICH PATHS the ruff / black / mypy gates examine.
#
# DBF (``CLAUDE.md`` Core Standard 15). All three gates were scoped to
# ``src/ tests/ .claude/ccy/claude-supervise.py``, leaving every other tracked
# Python file unexamined — including the whole of ``scripts/qa/``, i.e. the QA
# tooling itself. Nothing reported a gap: each gate said PASSED, because it had
# passed *on the subset it happened to look at*. The scope lived as a literal
# inside three separate scripts, so there was no single thing to read, review,
# or test.
#
# Widening it surfaced real defects immediately, not just annotation noise:
#   - install.py's create_forwarder_script was annotated "-> None" while
#     returning a Path that its caller collected into a list.
#   - The package shipped no PEP 561 "py.typed" marker, so every consumer of
#     claude_code_hooks_daemon -- including this repo's own scripts -- silently
#     resolved it to Any and lost all type checking.
#   - audit_handler_config_keys' return type was one level too shallow, making
#     each info[...] read look like indexing a string.
#
# Exposed as functions rather than arrays so that sourcing this file is not
# flagged as defining unused variables, and so callers read the scope through
# one documented interface. Sourced by run_lint.sh, run_format_check.sh and
# run_type_check.sh; asserted by tests/integration/test_qa_gate_scope.py so a
# silent narrowing fails the suite.

# Ruff and Black run over the whole repository. Deliberate exclusions (fixtures
# of intentionally-broken code) live in pyproject.toml's "extend-exclude",
# where they are declared once and visible to both tools.
qa_lint_paths() {
    printf '%s\n' "."
}

qa_format_paths() {
    printf '%s\n' "."
}

# Mypy cannot take "." — two directories are genuinely out of reach:
#
#   tests/            ~246 real findings under strict mode, on top of ~1,058
#                     missing-stub errors from third-party test dependencies.
#                     That is a project of its own, not a scope tweak. The
#                     "[[tool.mypy.overrides]] module = tests.*" block in
#                     pyproject.toml already exists for it and currently
#                     reports itself as an unused section — the standing
#                     reminder that this gap is open.
#
#   .claude/project-handlers/
#                     Mypy refuses the tree outright: "project-handlers
#                     contains __init__.py but is not a valid Python package
#                     name" (the hyphen). The __init__.py cannot simply be
#                     dropped — the co-located tests import their handlers
#                     relatively and stop resolving without it. The directory
#                     name is client-facing and documented, so renaming is not
#                     an option either. Their BEHAVIOUR is covered instead by
#                     the co-located tests, which
#                     scripts/qa/check_project_handler_tests.py runs as its own
#                     QA gate, and their LOAD-time integrity by
#                     "hooks-daemon validate-project-handlers".
#                     That gate exists because this note used to claim the test
#                     coverage while nothing enforced it: pyproject's testpaths
#                     is ["tests"], so no suite ever ran them.
#
# Both gaps are recorded here rather than left as an unexplained short list.
qa_type_paths() {
    printf '%s\n' \
        "src/" \
        "scripts/" \
        "install.py" \
        "examples/" \
        ".claude/ccy/claude-supervise.py"
}
