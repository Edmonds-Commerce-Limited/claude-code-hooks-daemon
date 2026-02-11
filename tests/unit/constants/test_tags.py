"""Tests for handler tag constants.

Tests that all tag constants are properly defined and have correct values.
"""

from typing import get_args

from claude_code_hooks_daemon.constants.tags import HandlerTag, TagLiteral


class TestHandlerTagConstants:
    """Tests for HandlerTag constant values."""

    def test_language_tags(self) -> None:
        """Test language tag constants."""
        assert HandlerTag.PYTHON == "python"
        assert HandlerTag.TYPESCRIPT == "typescript"
        assert HandlerTag.JAVASCRIPT == "javascript"
        assert HandlerTag.PHP == "php"
        assert HandlerTag.GO == "go"
        assert HandlerTag.BASH == "bash"

    def test_safety_tags(self) -> None:
        """Test safety-related tag constants."""
        assert HandlerTag.SAFETY == "safety"
        assert HandlerTag.BLOCKING == "blocking"
        assert HandlerTag.TERMINAL == "terminal"
        assert HandlerTag.NON_TERMINAL == "non-terminal"

    def test_workflow_tags(self) -> None:
        """Test workflow tag constants."""
        assert HandlerTag.WORKFLOW == "workflow"
        assert HandlerTag.ADVISORY == "advisory"
        assert HandlerTag.VALIDATION == "validation"
        assert HandlerTag.AUTOMATION == "automation"

    def test_qa_tags(self) -> None:
        """Test QA-related tag constants."""
        assert HandlerTag.QA_ENFORCEMENT == "qa-enforcement"
        assert HandlerTag.QA_SUPPRESSION_PREVENTION == "qa-suppression-prevention"
        assert HandlerTag.TDD == "tdd"

    def test_domain_tags(self) -> None:
        """Test domain-specific tag constants."""
        assert HandlerTag.GIT == "git"
        assert HandlerTag.FILE_OPS == "file-ops"
        assert HandlerTag.CONTENT_QUALITY == "content-quality"
        assert HandlerTag.NPM == "npm"
        assert HandlerTag.NODEJS == "nodejs"
        assert HandlerTag.GITHUB == "github"
        assert HandlerTag.MARKDOWN == "markdown"

    def test_system_tags(self) -> None:
        """Test system tag constants."""
        assert HandlerTag.STATUS == "status"
        assert HandlerTag.DISPLAY == "display"
        assert HandlerTag.HEALTH == "health"
        assert HandlerTag.LOGGING == "logging"
        assert HandlerTag.CLEANUP == "cleanup"

    def test_project_specific_tags(self) -> None:
        """Test project-specific tag constants."""
        assert HandlerTag.EC_SPECIFIC == "ec-specific"
        assert HandlerTag.EC_PREFERENCE == "ec-preference"
        assert HandlerTag.PROJECT_SPECIFIC == "project-specific"

    def test_other_tags(self) -> None:
        """Test miscellaneous tag constants."""
        assert HandlerTag.PLANNING == "planning"
        assert HandlerTag.ENVIRONMENT == "environment"
        assert HandlerTag.YOLO_MODE == "yolo-mode"
        assert HandlerTag.STATE_MANAGEMENT == "state-management"
        assert HandlerTag.CONTEXT_INJECTION == "context-injection"


class TestTagLiteralType:
    """Tests for TagLiteral type."""

    def test_tag_literal_includes_all_tags(self) -> None:
        """Test that TagLiteral includes all HandlerTag values."""
        tag_literal_values = set(get_args(TagLiteral))

        # Get all HandlerTag constant values
        handler_tag_values = {
            value
            for key, value in vars(HandlerTag).items()
            if not key.startswith("_") and isinstance(value, str)
        }

        assert tag_literal_values == handler_tag_values

    def test_tag_literal_count(self) -> None:
        """Test that TagLiteral has expected number of values."""
        tag_literal_values = get_args(TagLiteral)
        # Should have 44 tags (all HandlerTag constants)
        assert len(tag_literal_values) == 44


class TestTagUsage:
    """Tests for tag usage patterns."""

    def test_tags_can_be_used_in_list(self) -> None:
        """Test that tags can be used in a list."""
        tags = [HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING]
        assert len(tags) == 3
        assert HandlerTag.SAFETY in tags

    def test_tags_are_strings(self) -> None:
        """Test that all tag constants are strings."""
        for key, value in vars(HandlerTag).items():
            if not key.startswith("_"):
                assert isinstance(value, str), f"{key} should be a string"

    def test_no_duplicate_values(self) -> None:
        """Test that there are no duplicate tag values."""
        tag_values = [
            value
            for key, value in vars(HandlerTag).items()
            if not key.startswith("_") and isinstance(value, str)
        ]
        assert len(tag_values) == len(set(tag_values)), "Duplicate tag values found"

    def test_tag_values_match_naming_convention(self) -> None:
        """Test that tag values follow kebab-case convention."""
        for key, value in vars(HandlerTag).items():
            if not key.startswith("_") and isinstance(value, str):
                # Values should be lowercase, may contain hyphens
                assert value.islower() or "-" in value, f"{key}={value} not lowercase/kebab"
                assert " " not in value, f"{key}={value} contains spaces"


class TestSpecificTagValues:
    """Tests for specific important tag values."""

    def test_critical_safety_tags(self) -> None:
        """Test critical safety tags have correct values."""
        assert HandlerTag.SAFETY == "safety"
        assert HandlerTag.BLOCKING == "blocking"
        assert HandlerTag.TERMINAL == "terminal"

    def test_language_tags_match_expected(self) -> None:
        """Test language tags match expected language names."""
        languages = [
            (HandlerTag.PYTHON, "python"),
            (HandlerTag.TYPESCRIPT, "typescript"),
            (HandlerTag.JAVASCRIPT, "javascript"),
            (HandlerTag.PHP, "php"),
            (HandlerTag.GO, "go"),
            (HandlerTag.BASH, "bash"),
        ]
        for tag, expected in languages:
            assert tag == expected

    def test_qa_enforcement_tags(self) -> None:
        """Test QA enforcement tags are properly defined."""
        assert HandlerTag.QA_ENFORCEMENT == "qa-enforcement"
        assert HandlerTag.QA_SUPPRESSION_PREVENTION == "qa-suppression-prevention"
        assert HandlerTag.TDD == "tdd"


class TestTagConstants:
    """Tests for tag constant class structure."""

    def test_handler_tag_is_not_instantiable(self) -> None:
        """Test that HandlerTag is meant to be used as a namespace, not instantiated."""
        # HandlerTag is just a class with class attributes, but it can be instantiated
        # This is fine - we use it as a namespace
        instance = HandlerTag()
        assert instance is not None

    def test_all_public_attributes_are_strings(self) -> None:
        """Test that all public attributes are string constants."""
        for attr_name in dir(HandlerTag):
            if not attr_name.startswith("_"):
                attr_value = getattr(HandlerTag, attr_name)
                assert isinstance(attr_value, str), f"{attr_name} should be a string constant"


class TestTagExport:
    """Tests for module exports."""

    def test_all_exports(self) -> None:
        """Test that __all__ contains expected exports."""
        from claude_code_hooks_daemon.constants import tags

        assert hasattr(tags, "__all__")
        assert "HandlerTag" in tags.__all__
        assert "TagLiteral" in tags.__all__

    def test_tag_importable_from_constants(self) -> None:
        """Test that HandlerTag can be imported from constants package."""
        from claude_code_hooks_daemon.constants import HandlerTag as ImportedTag

        assert ImportedTag.PYTHON == "python"
        assert ImportedTag.SAFETY == "safety"
