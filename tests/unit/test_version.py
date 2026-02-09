"""Tests for version module."""

from claude_code_hooks_daemon.version import __version__


class TestVersion:
    """Test version information."""

    def test_version_is_defined(self) -> None:
        """Version is defined as a string."""
        assert isinstance(__version__, str)

    def test_version_follows_semver_format(self) -> None:
        """Version follows semantic versioning format."""
        parts = __version__.split(".")
        assert len(parts) == 3
        assert parts[0].isdigit()
        assert parts[1].isdigit()
        assert parts[2].isdigit()

    def test_version_is_not_empty(self) -> None:
        """Version is not an empty string."""
        assert __version__ != ""

    def test_version_has_expected_value(self) -> None:
        """Version matches expected value."""
        assert __version__ == "2.5.0"
