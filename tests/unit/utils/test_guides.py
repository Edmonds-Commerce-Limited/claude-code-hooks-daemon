"""Tests for guide path resolution utility."""

from pathlib import Path

from claude_code_hooks_daemon.utils.guides import get_llm_command_guide_path


class TestGetLlmCommandGuidePath:
    """Test suite for get_llm_command_guide_path."""

    def test_returns_string_path(self) -> None:
        """Returns a string path."""
        result = get_llm_command_guide_path()
        assert isinstance(result, str)

    def test_returned_path_exists(self) -> None:
        """Returned path points to an existing file."""
        result = get_llm_command_guide_path()
        assert Path(result).exists(), f"Guide file does not exist at: {result}"

    def test_returned_path_is_absolute(self) -> None:
        """Returned path is absolute."""
        result = get_llm_command_guide_path()
        assert Path(result).is_absolute(), f"Guide path is not absolute: {result}"

    def test_returned_path_ends_with_expected_filename(self) -> None:
        """Returned path ends with the expected guide filename."""
        result = get_llm_command_guide_path()
        assert result.endswith("llm-command-wrappers.md")

    def test_returned_path_is_inside_guides_package(self) -> None:
        """Returned path is inside the guides package directory."""
        result = get_llm_command_guide_path()
        assert "/guides/" in result

    def test_guide_file_is_not_empty(self) -> None:
        """Guide file has content."""
        result = get_llm_command_guide_path()
        content = Path(result).read_text(encoding="utf-8")
        assert len(content) > 0, "Guide file is empty"

    def test_guide_file_contains_philosophy_section(self) -> None:
        """Guide file contains the Philosophy section."""
        result = get_llm_command_guide_path()
        content = Path(result).read_text(encoding="utf-8")
        assert "## Philosophy" in content

    def test_guide_file_contains_stdout_contract(self) -> None:
        """Guide file contains the Stdout Contract section."""
        result = get_llm_command_guide_path()
        content = Path(result).read_text(encoding="utf-8")
        assert "Stdout Contract" in content

    def test_guide_file_contains_json_contract(self) -> None:
        """Guide file contains the JSON Output Contract section."""
        result = get_llm_command_guide_path()
        content = Path(result).read_text(encoding="utf-8")
        assert "JSON Output Contract" in content
