"""Tests for AcceptanceTest dataclass."""

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, TestType


class TestAcceptanceTestDataclass:
    """Test AcceptanceTest dataclass structure and validation."""

    def test_acceptance_test_creation_minimal(self):
        """Test creating AcceptanceTest with minimal required fields."""
        test = AcceptanceTest(
            title="Test git reset --hard",
            command='echo "git reset --hard"',
            description="Blocks destructive git reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"destroys.*uncommitted"],
        )

        assert test.title == "Test git reset --hard"
        assert test.command == 'echo "git reset --hard"'
        assert test.description == "Blocks destructive git reset"
        assert test.expected_decision == Decision.DENY
        assert test.expected_message_patterns == [r"destroys.*uncommitted"]
        assert test.safety_notes is None
        assert test.setup_commands is None
        assert test.cleanup_commands is None
        assert test.requires_event is None
        assert test.test_type == TestType.BLOCKING

    def test_acceptance_test_creation_full(self):
        """Test creating AcceptanceTest with all fields."""
        test = AcceptanceTest(
            title="Test sed -i",
            command='sed -i "s/foo/bar/" /tmp/test.txt',
            description="Blocks destructive sed in-place edit",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"Use Edit tool", r"sed -i"],
            safety_notes="Uses /tmp file - harmless",
            setup_commands=['echo "test" > /tmp/test.txt'],
            cleanup_commands=["rm /tmp/test.txt"],
            requires_event="PreToolUse",
            test_type=TestType.BLOCKING,
        )

        assert test.title == "Test sed -i"
        assert test.safety_notes == "Uses /tmp file - harmless"
        assert test.setup_commands == ['echo "test" > /tmp/test.txt']
        assert test.cleanup_commands == ["rm /tmp/test.txt"]
        assert test.requires_event == "PreToolUse"
        assert test.test_type == TestType.BLOCKING

    def test_acceptance_test_advisory_type(self):
        """Test creating advisory (non-blocking) test."""
        test = AcceptanceTest(
            title="British English suggestion",
            command='echo "color organization"',
            description="Suggests British spellings",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"colour", r"organisation"],
            test_type=TestType.ADVISORY,
        )

        assert test.test_type == TestType.ADVISORY
        assert test.expected_decision == Decision.ALLOW

    def test_acceptance_test_context_type(self):
        """Test creating context injection test."""
        test = AcceptanceTest(
            title="Git context injection",
            command="echo 'test prompt'",
            description="Injects git status",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"git.*status"],
            test_type=TestType.CONTEXT,
        )

        assert test.test_type == TestType.CONTEXT


class TestTestTypeEnum:
    """Test TestType enum."""

    def test_test_type_values(self):
        """Test TestType enum has expected values."""
        assert TestType.BLOCKING == "blocking"
        assert TestType.ADVISORY == "advisory"
        assert TestType.CONTEXT == "context"

    def test_test_type_membership(self):
        """Test TestType enum membership."""
        assert "blocking" in [t.value for t in TestType]
        assert "advisory" in [t.value for t in TestType]
        assert "context" in [t.value for t in TestType]


class TestAcceptanceTestValidation:
    """Test validation of AcceptanceTest fields."""

    def test_empty_title_rejected(self):
        """Test that empty title is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="",
                command='echo "test"',
                description="Test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )

    def test_empty_command_rejected(self):
        """Test that empty command is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="Test",
                command="",
                description="Test",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )

    def test_empty_description_rejected(self):
        """Test that empty description is rejected."""
        with pytest.raises((ValueError, TypeError)):
            AcceptanceTest(
                title="Test",
                command='echo "test"',
                description="",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
            )
