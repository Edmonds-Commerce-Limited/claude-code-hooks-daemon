"""Tests for the shared repo-relative-path validator (Plan 00303).

Config carries ZERO absolute paths (owner ruling): a repository is mounted at
different places on different machines, so an absolute path in committed
config is correct on exactly one of them. This module is the ONE
pydantic-free implementation of that rule, so both a pydantic field
validator (hard error) and a runtime resolver (skip + warn, never raise) can
share it instead of growing their own copies.
"""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.repo_relative_path import (
    REPO_ROOT_PLACEHOLDER,
    expand_repo_root_token,
    normalise_repo_relative_path,
)


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

    def test_token_prefixed_path_is_stripped(self) -> None:
        assert normalise_repo_relative_path(f"{REPO_ROOT_PLACEHOLDER}/web", "label") == "web"

    def test_token_alone_normalises_to_repo_root(self) -> None:
        assert normalise_repo_relative_path(REPO_ROOT_PLACEHOLDER, "label") == "."

    def test_token_followed_by_trailing_slash_normalises(self) -> None:
        assert normalise_repo_relative_path(f"{REPO_ROOT_PLACEHOLDER}/", "label") == "."

    def test_token_not_at_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start"):
            normalise_repo_relative_path(f"web/{REPO_ROOT_PLACEHOLDER}/x", "label")

    def test_token_without_following_slash_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start"):
            normalise_repo_relative_path(f"{REPO_ROOT_PLACEHOLDER}suffix", "label")

    def test_token_prefixed_escape_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not escape"):
            normalise_repo_relative_path(f"{REPO_ROOT_PLACEHOLDER}/../elsewhere", "label")

    def test_bare_relative_path_still_valid_without_token(self) -> None:
        assert normalise_repo_relative_path("web", "label") == "web"


class TestExpandRepoRootToken:
    def test_token_alone_expands_to_project_root(self) -> None:
        root = Path("/repo")
        assert expand_repo_root_token(REPO_ROOT_PLACEHOLDER, root) == str(root)

    def test_token_prefixed_path_expands_against_project_root(self) -> None:
        root = Path("/repo")
        assert expand_repo_root_token(f"{REPO_ROOT_PLACEHOLDER}/plugins/foo", root) == str(
            root / "plugins/foo"
        )

    def test_leading_slash_is_returned_unchanged(self) -> None:
        assert expand_repo_root_token("/opt/plugins", Path("/repo")) == "/opt/plugins"

    def test_plain_relative_path_is_returned_unchanged(self) -> None:
        assert expand_repo_root_token("plugins/foo", Path("/repo")) == "plugins/foo"

    def test_token_not_at_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start"):
            expand_repo_root_token(f"plugins/{REPO_ROOT_PLACEHOLDER}/foo", Path("/repo"))

    def test_token_prefixed_escape_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="must not escape"):
            expand_repo_root_token(f"{REPO_ROOT_PLACEHOLDER}/../elsewhere", Path("/repo"))
