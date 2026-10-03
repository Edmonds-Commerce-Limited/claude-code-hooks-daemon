"""Notification handlers for claude-code-hooks-daemon.

Plan 00237 removed ``notification_logger``, which appended every Notification event
to ``notifications.jsonl`` that nothing read. The one handler here now records only
what something reads: ``quota_resume_recorder`` writes down how a usage-limit wait
ended (Plan 00470 Task 3.2), and ``user_prompt_submit.limit_rebrief`` acts on it,
because a Notification hook cannot inject context.
"""

__all__: list[str] = []
