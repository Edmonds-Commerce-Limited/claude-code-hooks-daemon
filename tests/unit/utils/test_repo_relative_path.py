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
    validate_repo_root_token_placement,
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


class TestValidateRepoRootTokenPlacement:
    """Plan 00305 Task 1.2: a placement-only check for token-exempt fields.

    ``PluginConfig.path``/``ProjectHandlersConfig.path`` are exempt from the
    repo-relative-only rule (an absolute path is a deliberate override), but
    still accept the optional ``{REPO_ROOT}`` token, and a misplaced token
    must be a named config validation error rather than a startup traceback
    from the unguarded ``expand_repo_root_token`` call sites.
    """

    def test_no_token_is_returned_unchanged(self) -> None:
        assert validate_repo_root_token_placement("/srv/plugins", "label") == "/srv/plugins"

    def test_token_alone_is_returned_unchanged(self) -> None:
        assert (
            validate_repo_root_token_placement(REPO_ROOT_PLACEHOLDER, "label")
            == REPO_ROOT_PLACEHOLDER
        )

    def test_token_prefix_is_returned_unchanged(self) -> None:
        value = f"{REPO_ROOT_PLACEHOLDER}/plugins/foo"
        assert validate_repo_root_token_placement(value, "label") == value

    def test_plain_relative_path_is_returned_unchanged(self) -> None:
        assert validate_repo_root_token_placement("plugins/foo", "label") == "plugins/foo"

    def test_token_not_at_start_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start"):
            validate_repo_root_token_placement(f"plugins/{REPO_ROOT_PLACEHOLDER}/foo", "label")

    def test_token_without_following_slash_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="start"):
            validate_repo_root_token_placement(f"{REPO_ROOT_PLACEHOLDER}suffix", "label")

    def test_error_message_includes_the_label(self) -> None:
        with pytest.raises(ValueError, match="my thing"):
            validate_repo_root_token_placement(f"x/{REPO_ROOT_PLACEHOLDER}/y", "my thing")

    def test_does_not_reject_repo_escaping_dotdot(self) -> None:
        """Placement-only: this check does not enforce repo-relativity or ``..`` rules --
        those are left to `expand_repo_root_token`'s own escape check at expansion time.
        """
        value = f"{REPO_ROOT_PLACEHOLDER}/../elsewhere"
        assert validate_repo_root_token_placement(value, "label") == value
