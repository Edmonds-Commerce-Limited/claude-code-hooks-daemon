"""Tests for npm utility functions.

Comprehensive test coverage for LLM command detection in package.json.
"""

import json
from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.utils.npm import has_llm_commands_in_package_json


class TestHasLlmCommandsInPackageJson:
    """Test suite for has_llm_commands_in_package_json()."""

    def test_returns_true_when_llm_scripts_exist(self, tmp_path: Path) -> None:
        """Returns True when package.json has llm: prefixed scripts."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps(
                {
                    "name": "test-project",
                    "scripts": {
                        "build": "tsc",
                        "llm:build": "tsc --json > ./var/qa/build.json",
                        "llm:lint": "eslint . --format json",
                    },
                }
            )
        )
        assert has_llm_commands_in_package_json(tmp_path) is True

    def test_returns_true_with_single_llm_script(self, tmp_path: Path) -> None:
        """Returns True even with just one llm: script."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps(
                {
                    "name": "test-project",
                    "scripts": {
                        "build": "tsc",
                        "llm:build": "tsc --json > ./var/qa/build.json",
                    },
                }
            )
        )
        assert has_llm_commands_in_package_json(tmp_path) is True

    def test_returns_false_when_no_llm_scripts(self, tmp_path: Path) -> None:
        """Returns False when package.json has no llm: scripts."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps(
                {
                    "name": "test-project",
                    "scripts": {
                        "build": "tsc",
                        "lint": "eslint .",
                        "test": "jest",
                    },
                }
            )
        )
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_returns_false_when_package_json_missing(self, tmp_path: Path) -> None:
        """Returns False when package.json does not exist."""
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_returns_false_when_package_json_malformed(self, tmp_path: Path) -> None:
        """Returns False when package.json is not valid JSON."""
        package_json = tmp_path / "package.json"
        package_json.write_text("this is not json {{{")
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_returns_false_when_scripts_section_missing(self, tmp_path: Path) -> None:
        """Returns False when package.json has no scripts section."""
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "test-project", "version": "1.0.0"}))
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_returns_false_when_scripts_is_not_dict(self, tmp_path: Path) -> None:
        """Returns False when scripts is not a dictionary."""
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "test-project", "scripts": "not a dict"}))
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_returns_false_when_scripts_is_empty(self, tmp_path: Path) -> None:
        """Returns False when scripts section is empty."""
        package_json = tmp_path / "package.json"
        package_json.write_text(json.dumps({"name": "test-project", "scripts": {}}))
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_ignores_script_values_containing_llm(self, tmp_path: Path) -> None:
        """Only checks script keys, not values for llm: prefix."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps(
                {
                    "name": "test-project",
                    "scripts": {
                        "build": "llm:build something",
                    },
                }
            )
        )
        assert has_llm_commands_in_package_json(tmp_path) is False

    def test_uses_project_context_when_no_path_given(self) -> None:
        """Uses ProjectContext.project_root() when no path provided."""
        with patch("claude_code_hooks_daemon.utils.npm.ProjectContext.project_root") as mock_root:
            mock_root.return_value = Path("/nonexistent/path")
            result = has_llm_commands_in_package_json()
            mock_root.assert_called_once()
            assert result is False

    def test_accepts_path_argument(self, tmp_path: Path) -> None:
        """Accepts explicit path argument instead of using ProjectContext."""
        package_json = tmp_path / "package.json"
        package_json.write_text(
            json.dumps({"name": "test", "scripts": {"llm:test": "jest --json"}})
        )
        assert has_llm_commands_in_package_json(tmp_path) is True
