"""SessionEnd handlers for claude-code-hooks-daemon.

Empty since Plan 00237 removed ``cleanup``, the only handler here: it reaped a
``temp/hooks/`` directory that nothing in the codebase has ever written. The
package stays so the SessionEnd event remains a registered, dispatchable event
with a home for future handlers.
"""

__all__: list[str] = []
