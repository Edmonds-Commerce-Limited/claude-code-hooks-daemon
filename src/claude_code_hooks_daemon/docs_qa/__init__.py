"""Documentation SSoT enforcement check core (Plan 00284).

Sibling of :mod:`claude_code_hooks_daemon.plan_qa`, mirroring its layout: a
pure check core (:mod:`types`, :mod:`context`, :mod:`corpus`,
:mod:`checks`, :mod:`runner`, :mod:`report`) consumed by three thin
enforcement surfaces (edit-time handler, commit-gate handler, session
sweep — none of which ship in this slice) plus the ``docs-qa`` CLI.

See ``CLAUDE/DocumentationStrategy.md`` for the ruleset being enforced and
``CLAUDE/Plan/00284-documentation-ssot-enforcement/DESIGN-enforcement.md``
for the architecture this package implements.
"""
