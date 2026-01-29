"""TranscriptArchiverHandler - archives conversation transcript before compaction."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import DaemonPath, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision, Handler, HookResult


class TranscriptArchiverHandler(Handler):
    """Archive conversation transcript before compaction.

    Saves transcript to timestamped file for historical reference and debugging.
    Non-terminal to allow compaction to proceed.
    """

    def __init__(self) -> None:
        """Initialise handler as non-terminal archiver."""
        super().__init__(
            name="transcript-archiver",
            priority=Priority.TRANSCRIPT_ARCHIVER,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ARCHIVING, HandlerTag.NON_TERMINAL],
        )

    def matches(self, _hook_input: dict[str, Any]) -> bool:
        """Match all pre-compact events.

        Args:
            _hook_input: Hook input dictionary from Claude Code (unused)

        Returns:
            Always True (archive all compactions)
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Archive transcript to file.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with allow decision (silent archiving)
        """
        try:
            # Create archive directory
            archive_dir = Path(DaemonPath.UNTRACKED_DIR) / "transcripts"
            archive_dir.mkdir(parents=True, exist_ok=True)

            # Generate timestamp filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_file = archive_dir / f"transcript_{timestamp}.json"

            # Build archive data
            archive_data = {
                "archived_at": datetime.now().isoformat(),
                "transcript": hook_input.get("transcript", []),
            }

            # Write to JSON file with pretty formatting
            with archive_file.open("w") as f:
                json.dump(archive_data, f, indent=2)

        except OSError:
            # Silently ignore file write errors
            pass

        return HookResult(decision=Decision.ALLOW)
