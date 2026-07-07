"""Plan QA core — pure, daemon-decoupled parsing and validation of plan trees.

Built by Plan 00144. This package contains NO handler or daemon coupling:
parsers (``model``, ``readme_index``), git fact gathering (``gitfacts``),
the check catalogue (``checks``), and the runner/report layers are all
independently unit-testable. Handlers and the ``plan-qa`` CLI subcommand are
thin consumers that build a context and render findings.
"""
