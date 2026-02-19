"""Tests for AcceptanceTest dataclass."""

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest, RecommendedModel, TestType


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
        assert test.recommended_model is None
        assert test.requires_main_thread is False

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


class TestRecommendedModelEnum:
    """Test RecommendedModel enum."""

    def test_recommended_model_values(self):
        """Test RecommendedModel enum has expected values."""
        assert RecommendedModel.HAIKU == "haiku"
        assert RecommendedModel.SONNET == "sonnet"
        assert RecommendedModel.OPUS == "opus"

    def test_recommended_model_membership(self):
        """Test RecommendedModel enum membership."""
        assert "haiku" in [m.value for m in RecommendedModel]
        assert "sonnet" in [m.value for m in RecommendedModel]
        assert "opus" in [m.value for m in RecommendedModel]

    def test_recommended_model_is_str_enum(self):
        """Test RecommendedModel values compare equal to strings."""
        assert RecommendedModel.HAIKU == "haiku"
        assert RecommendedModel.SONNET == "sonnet"


class TestAcceptanceTestNewFields:
    """Test new recommended_model and requires_main_thread fields."""

    def test_default_recommended_model_is_none(self):
        """Test recommended_model defaults to None."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.recommended_model is None

    def test_default_requires_main_thread_is_false(self):
        """Test requires_main_thread defaults to False."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
        )
        assert test.requires_main_thread is False

    def test_set_recommended_model_haiku(self):
        """Test setting recommended_model to HAIKU."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.HAIKU,
        )
        assert test.recommended_model == RecommendedModel.HAIKU
        assert test.recommended_model == "haiku"

    def test_set_recommended_model_sonnet(self):
        """Test setting recommended_model to SONNET."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.SONNET,
        )
        assert test.recommended_model == RecommendedModel.SONNET

    def test_set_recommended_model_opus(self):
        """Test setting recommended_model to OPUS."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.DENY,
            expected_message_patterns=[],
            recommended_model=RecommendedModel.OPUS,
        )
        assert test.recommended_model == RecommendedModel.OPUS

    def test_set_requires_main_thread_true(self):
        """Test setting requires_main_thread to True."""
        test = AcceptanceTest(
            title="Test",
            command='echo "test"',
            description="Test description",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[],
            requires_main_thread=True,
        )
        assert test.requires_main_thread is True

    def test_both_new_fields_together(self):
        """Test setting both new fields together."""
        test = AcceptanceTest(
            title="Advisory test",
            command='echo "test advisory"',
            description="Advisory test requiring main thread",
            expected_decision=Decision.ALLOW,
            expected_message_patterns=[r"advisory.*context"],
            test_type=TestType.ADVISORY,
            recommended_model=RecommendedModel.SONNET,
            requires_main_thread=True,
        )
        assert test.recommended_model == RecommendedModel.SONNET
        assert test.requires_main_thread is True
        assert test.test_type == TestType.ADVISORY

    def test_blocking_test_typical_config(self):
        """Test typical BLOCKING test config: haiku, not main thread."""
        test = AcceptanceTest(
            title="Block git reset",
            command='echo "git reset --hard"',
            description="Blocks destructive reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[r"destroys"],
            test_type=TestType.BLOCKING,
            recommended_model=RecommendedModel.HAIKU,
            requires_main_thread=False,
        )
        assert test.recommended_model == RecommendedModel.HAIKU
        assert test.requires_main_thread is False


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
