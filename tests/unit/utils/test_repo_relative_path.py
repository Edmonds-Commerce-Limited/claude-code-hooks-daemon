"""Tests for the shared repo-relative-path validator (Plan 00303).

Config carries ZERO absolute paths (owner ruling): a repository is mounted at
different places on different machines, so an absolute path in committed
config is correct on exactly one of them. This module is the ONE
pydantic-free implementation of that rule, so both a pydantic field
validator (hard error) and a runtime resolver (skip + warn, never raise) can
share it instead of growing their own copies.
"""

import pytest

from claude_code_hooks_daemon.utils.repo_relative_path import normalise_repo_relative_path


class TestNormaliseRepoRelativePath:
    def test_relative_path_is_returned_normalised(self) -> None:
        assert normalise_repo_relative_path("web/", "label") == "web"

    def test_dot_prefix_is_normalised(self) -> None:
        assert normalise_repo_relative_path("./web", "label") == "web"

    def test_empty_string_normalises_to_repo_root(self) -> None:
        assert normalise_repo_relative_path("", "label") == "."

    def test_absolute_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="repository-relative"):
            normalise_repo_relative_path("/srv/web", "label")

    def test_home_relative_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="repository-relative"):
            normalise_repo_relative_path("~/code/web", "label")

    def test_escaping_path_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not escape"):
            normalise_repo_relative_path("../elsewhere", "label")

    def test_interior_dotdot_escape_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not escape"):
            normalise_repo_relative_path("apps/../../elsewhere", "label")

    def test_error_message_includes_the_label(self) -> None:
        with pytest.raises(ValueError, match="my thing"):
            normalise_repo_relative_path("/abs", "my thing")
