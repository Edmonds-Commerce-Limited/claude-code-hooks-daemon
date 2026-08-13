"""Notification handlers for claude-code-hooks-daemon.

Empty since Plan 00237 removed ``notification_logger``, the only handler here:
it appended every Notification event to ``notifications.jsonl``, which nothing
in the codebase — and no doc prescribing a diagnostic step — has ever read. The
package stays so Notification remains a registered, dispatchable event with a
home for future handlers.
"""

__all__: list[str] = []
