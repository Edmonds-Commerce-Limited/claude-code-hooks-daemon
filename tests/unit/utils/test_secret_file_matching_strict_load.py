"""The STRICT read of the protected set (Plan 00613 Task 2.1).

``resolve_configured_patterns`` falls back to the shipped defaults when the
config cannot be read, which is right for a seam-closer that must still
protect. A caller that decides whether to CREATE something (a worktree copy of
a file) needs the opposite: an unreadable config is an answer it cannot act
on, so the strict read raises instead of guessing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils import secret_file_matching as sfm


def _config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _load(config_path: Path) -> tuple[str, ...]:
    with (
        patch.object(ProjectContext, "is_initialized", return_value=True),
        patch.object(ProjectContext, "config_path", return_value=config_path),
    ):
        return sfm.load_protected_patterns_strict()


_GUARD = "version: '2.0'\nhandlers:\n  pre_tool_use:\n    secret_file_guard:\n      options:\n"


class TestReadable:
    def test_no_guard_block_gives_the_shipped_defaults(self, tmp_path: Path) -> None:
        assert _load(_config(tmp_path, "version: '2.0'\n")) == sfm.DEFAULT_PROTECTED_PATTERNS

    def test_additive_project_paths_are_merged(self, tmp_path: Path) -> None:
        patterns = _load(_config(tmp_path, _GUARD + "        protected_paths: ['*.key']\n"))
        assert patterns == (*sfm.DEFAULT_PROTECTED_PATTERNS, "*.key")

    def test_replace_mode_uses_only_the_project_list(self, tmp_path: Path) -> None:
        body = _GUARD + "        mode: replace\n        protected_paths: ['*.key']\n"
        assert _load(_config(tmp_path, body)) == ("*.key",)

    def test_a_read_is_not_cached(self, tmp_path: Path) -> None:
        """The process-lifetime cache of the lenient read must not leak in."""
        path = _config(tmp_path, "version: '2.0'\n")
        assert _load(path) == sfm.DEFAULT_PROTECTED_PATTERNS
        path.write_text(_GUARD + "        protected_paths: ['*.late']\n", encoding="utf-8")
        assert "*.late" in _load(path)


class TestUnreadableRaises:
    def test_uninitialised_context(self) -> None:
        with (
            patch.object(ProjectContext, "is_initialized", return_value=False),
            pytest.raises(sfm.ProtectedSetUnreadable),
        ):
            sfm.load_protected_patterns_strict()

    def test_missing_config_file(self, tmp_path: Path) -> None:
        with pytest.raises(sfm.ProtectedSetUnreadable):
            _load(tmp_path / "hooks-daemon.yaml")

    def test_malformed_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(sfm.ProtectedSetUnreadable):
            _load(_config(tmp_path, "handlers: [unclosed\n"))

    def test_protected_paths_that_is_not_a_list(self, tmp_path: Path) -> None:
        """A bare string would otherwise be split into one-character globs."""
        with pytest.raises(sfm.ProtectedSetUnreadable):
            _load(_config(tmp_path, _GUARD + "        protected_paths: '*.key'\n"))

    def test_protected_paths_holding_a_non_string(self, tmp_path: Path) -> None:
        with pytest.raises(sfm.ProtectedSetUnreadable):
            _load(_config(tmp_path, _GUARD + "        protected_paths: [12]\n"))

    def test_a_mode_that_is_not_a_string(self, tmp_path: Path) -> None:
        with pytest.raises(sfm.ProtectedSetUnreadable):
            _load(_config(tmp_path, _GUARD + "        mode: [replace]\n"))

    def test_the_reason_names_no_config_content(self, tmp_path: Path) -> None:
        with pytest.raises(sfm.ProtectedSetUnreadable) as excinfo:
            _load(_config(tmp_path, _GUARD + "        protected_paths: 'zz-private-shape'\n"))
        assert "zz-private-shape" not in str(excinfo.value)


class TestProtectingPatternUnderAnExplicitRoot:
    def test_an_anchored_glob_matches_under_the_given_root(self, tmp_path: Path) -> None:
        target = tmp_path / "config" / "prod.creds"
        assert (
            sfm.protecting_pattern_under(str(target), ("/config/prod.creds",), str(tmp_path))
            == "/config/prod.creds"
        )

    def test_the_realpath_is_judged_too(self, tmp_path: Path) -> None:
        (tmp_path / "real.creds").write_text("x\n", encoding="utf-8")
        (tmp_path / "alias").symlink_to("real.creds")
        assert (
            sfm.protecting_pattern_under(str(tmp_path / "alias"), ("*.creds",), str(tmp_path))
            == "*.creds"
        )

    def test_no_match(self, tmp_path: Path) -> None:
        assert sfm.protecting_pattern_under(str(tmp_path / "a.txt"), ("*.creds",), None) is None
