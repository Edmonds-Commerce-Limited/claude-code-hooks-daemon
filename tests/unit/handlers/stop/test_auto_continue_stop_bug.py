"""Regression test for auto_continue_stop bug - GitHub Issue TBD.

Bug: Handler fails to match "Should I proceed with Phase 2?" pattern.
This test MUST FAIL before the fix is applied.
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import AutoContinueStopHandler


class TestAutoContinueStopBug:
    """Regression tests for auto_continue_stop handler bug."""

    def test_bug_should_i_proceed_pattern_not_matching(self, tmp_path: Path) -> None:
        """Bug: 'Should I proceed with Phase 2?' should match but doesn't.

        Real scenario from dogfooding:
        - Claude asked: "Should I proceed with Phase 2?"
        - Pattern exists: r"should I (?:continue|proceed|start|begin)"
        - Handler did NOT match (preventedContinuation: false in transcript)
        - User had to manually continue

        This test reproduces the exact scenario and MUST FAIL until bug is fixed.
        """
        # Create handler
        handler = AutoContinueStopHandler()

        # Create transcript with the exact message that failed
        transcript_file = tmp_path / "transcript.jsonl"
        assistant_message = {
            "type": "message",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "**Next Phase**: Phase 2 - Python Config Preservation Engine (4 modules using TDD)\n"
                            "- `config_differ.py` - Extract user customizations vs version example\n"
                            "- `config_merger.py` - Merge customizations into new default config  \n"
                            "- `config_validator.py` - Validate merged config with Pydantic\n"
                            "- CLI entry points for bash scripts\n\n"
                            "Should I proceed with Phase 2?"
                        ),
                    }
                ],
            },
        }

        with transcript_file.open("w") as f:
            json.dump(assistant_message, f)
            f.write("\n")

        # Create hook input
        hook_input = {
            "transcript_path": str(transcript_file),
            "stop_hook_active": False,  # Not in recursive stop
        }

        # THIS ASSERTION MUST FAIL (handler should match but doesn't)
        assert handler.matches(hook_input) is True, (
            "Handler should match 'Should I proceed with Phase 2?' pattern but didn't. "
            "This is the bug we're fixing."
        )

        # If matches() works, handle() should block the stop
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "AUTO-CONTINUE" in result.reason

    def test_bug_variations_of_should_i_proceed(self, tmp_path: Path) -> None:
        """Test variations of 'should I' pattern that should all match."""
        handler = AutoContinueStopHandler()

        test_cases = [
            "Should I proceed with Phase 2?",
            "Should I continue with the next task?",
            "Should I start implementing now?",
            "Should I begin the refactoring?",
            "should I proceed?",  # lowercase
            "SHOULD I PROCEED?",  # uppercase
            "  Should I proceed?  ",  # whitespace
        ]

        for message_text in test_cases:
            transcript_file = tmp_path / f"transcript_{hash(message_text)}.jsonl"
            assistant_message = {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": message_text}],
                },
            }

            with transcript_file.open("w") as f:
                json.dump(assistant_message, f)
                f.write("\n")

            hook_input = {
                "transcript_path": str(transcript_file),
                "stop_hook_active": False,
            }

            # All variations should match
            assert (
                handler.matches(hook_input) is True
            ), f"Handler should match '{message_text}' but didn't"

    def test_should_not_match_error_patterns(self, tmp_path: Path) -> None:
        """Verify handler correctly rejects error patterns (not a bug)."""
        handler = AutoContinueStopHandler()

        # These should NOT match (contain error patterns)
        error_messages = [
            "Error: something failed. Should I proceed?",
            "Failed: test didn't pass. Should I continue?",
            "What would you like me to do next?",
            "How should I handle this error?",
        ]

        for message_text in error_messages:
            transcript_file = tmp_path / f"transcript_{hash(message_text)}.jsonl"
            assistant_message = {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": message_text}],
                },
            }

            with transcript_file.open("w") as f:
                json.dump(assistant_message, f)
                f.write("\n")

            hook_input = {
                "transcript_path": str(transcript_file),
                "stop_hook_active": False,
            }

            # Error patterns should NOT match
            assert (
                handler.matches(hook_input) is False
            ), f"Handler should NOT match error pattern '{message_text}' but did"
