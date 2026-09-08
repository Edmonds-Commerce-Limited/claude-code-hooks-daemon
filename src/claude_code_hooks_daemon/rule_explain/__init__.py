"""On-demand rule/handler lookup for the ``explain-rule``/``explain-handler``
CLI commands, documented as a capability of the hooks-daemon skill (Plan 00116 Phase 6,
Decision F).

Enumeration walks the ``handlers`` package the same way
:class:`~claude_code_hooks_daemon.daemon.docs_generator.DocsGenerator` does,
so it never requires a running daemon and new rules from sibling handler
migrations appear automatically — nothing here needs to change when a new
handler declares ``get_rules()``.
"""
