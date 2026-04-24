"""Tests for project_path_slug() and slug-prefixed python_venv_fingerprint().

Plan 00100 Task 3.0.5: venv dir names embed a human-readable path slug
derived from the project root. This distinguishes venvs for the same Python
interpreter viewed from different project roots — the core anti-collision
property when the SAME project is opened from the SAME image as both a
host (``/home/dev/proj``) and a container (``/workspace``).

Slug algorithm:
    1. Resolve path to absolute form.
    2. Strip leading ``/``; replace remaining ``/`` with ``_``.
    3. Remove any character not in ``[A-Za-z0-9_-]``.
    4. If length > 40: keep first 36 chars + ``-`` + 4-hex md5 suffix computed
       on the original absolute path.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    get_venv_path,
    project_path_slug,
    python_venv_fingerprint,
)


class TestProjectPathSlugBasic:
    """Basic conversions for typical paths."""

    def test_home_user_proj(self) -> None:
        assert project_path_slug("/home/user/proj") == "home_user_proj"

    def test_workspace(self) -> None:
        assert project_path_slug("/workspace") == "workspace"

    def test_root_path_yields_nonempty_slug(self) -> None:
        """Degenerate ``/`` input must not produce an empty slug."""
        result = project_path_slug("/")
        assert result, "slug must be non-empty"
        assert re.match(r"^[A-Za-z0-9_-]+$", result)

    def test_accepts_path_object(self) -> None:
        assert project_path_slug(Path("/workspace")) == "workspace"

    def test_accepts_string(self) -> None:
        assert project_path_slug("/workspace") == "workspace"


class TestProjectPathSlugNormalization:
    """Non-safe characters are stripped or replaced."""

    def test_dots_stripped(self) -> None:
        result = project_path_slug("/home/user/my.proj")
        assert "." not in result
        assert result.startswith("home_user_my")

    def test_spaces_stripped(self) -> None:
        result = project_path_slug("/home/user with spaces/proj")
        assert " " not in result
        assert re.match(r"^[A-Za-z0-9_-]+$", result)

    def test_unicode_stripped(self) -> None:
        result = project_path_slug("/home/日本語/proj")
        assert re.match(r"^[A-Za-z0-9_-]+$", result)

    def test_filesystem_safe_chars_only(self) -> None:
        tricky_inputs = [
            "/home/user with spaces/proj",
            "/path/with/dots.here/and-special-chars",
            "/some/ProjectName_v2",
        ]
        for path in tricky_inputs:
            result = project_path_slug(path)
            assert re.match(r"^[A-Za-z0-9_-]+$", result), f"Unsafe chars in {result!r} for {path!r}"


class TestProjectPathSlugTruncation:
    """Long paths are truncated to 36 chars + ``-`` + 4-hex suffix."""

    _long_path = (
        "/aaaaaaaa/bbbbbbbb/cccccccc/dddddddd/eeeeeeee/ffff"
    )  # 50 chars; slug would be 49 > 40

    def test_long_path_truncated_to_36_plus_hash(self) -> None:
        result = project_path_slug(self._long_path)
        assert len(result) == 41, f"expected 41 chars (36+1+4), got {len(result)}: {result}"
        assert re.match(r"^[A-Za-z0-9_-]{36}-[0-9a-f]{4}$", result), f"Bad format: {result}"

    def test_short_path_not_truncated(self) -> None:
        result = project_path_slug("/home/user/proj")
        assert result == "home_user_proj"
        assert len(result) <= 40

    def test_truncation_is_deterministic(self) -> None:
        assert project_path_slug(self._long_path) == project_path_slug(self._long_path)

    def test_different_long_paths_with_same_prefix_differ(self) -> None:
        """Same 36-char prefix must still be distinguished by hash suffix."""
        p1 = "/aaaaaaaa/bbbbbbbb/cccccccc/dddddddd/eeeeeeee/aaaa"
        p2 = "/aaaaaaaa/bbbbbbbb/cccccccc/dddddddd/eeeeeeee/bbbb"
        s1 = project_path_slug(p1)
        s2 = project_path_slug(p2)
        # Prefix is the same (36 chars); hash suffix must diverge.
        assert s1 != s2
        assert s1[:36] == s2[:36], f"prefixes differ: {s1!r} vs {s2!r}"

    def test_suffix_is_md5_of_original_absolute_path(self) -> None:
        """Determinism: suffix = md5(absolute_path)[:4]."""
        abs_path = str(Path(self._long_path).resolve())
        expected_suffix = hashlib.md5(
            abs_path.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:4]
        result = project_path_slug(self._long_path)
        assert result.endswith(f"-{expected_suffix}"), (
            f"{result!r} should end with -{expected_suffix}"
        )


class TestProjectPathSlugHostContainerIsolation:
    """Core anti-collision property: host and container views of the same
    project produce different slugs even with matching Python fingerprints."""

    def test_host_path_differs_from_container_path(self) -> None:
        host = project_path_slug("/home/dev/my-project")
        container = project_path_slug("/workspace")
        assert host != container

    def test_distinct_containers_with_distinct_mounts_differ(self) -> None:
        a = project_path_slug("/workspace")
        b = project_path_slug("/app")
        assert a != b


class TestPythonVenvFingerprintWithRoot:
    """python_venv_fingerprint(root) prepends the path slug to the fingerprint."""

    def test_with_root_prepends_slug(self) -> None:
        result = python_venv_fingerprint("/workspace")
        assert result.startswith("workspace-py"), f"Expected workspace-py prefix, got: {result}"

    def test_with_root_format(self) -> None:
        result = python_venv_fingerprint("/workspace")
        assert re.match(r"^[A-Za-z0-9_-]+-py\d{2,3}-[0-9a-f]{8}$", result), f"Bad: {result}"

    def test_without_root_preserves_legacy_format(self) -> None:
        """No-arg call remains backwards-compatible: ``pyMM-XXXXXXXX``."""
        result = python_venv_fingerprint()
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", result), f"Bad: {result}"

    def test_different_roots_produce_different_fingerprints(self) -> None:
        """Same Python env + different project roots -> distinct keys.

        This is the whole point of the slug: prevent collision when two
        views of one project (host vs container) share a Python fingerprint.
        """
        with (
            patch.object(sys, "base_prefix", "/usr"),
            patch.object(sys, "version", "3.11.5 fixed"),
        ):
            fp_host = python_venv_fingerprint("/home/dev/proj")
            fp_container = python_venv_fingerprint("/workspace")
        assert fp_host != fp_container

    def test_path_object_and_string_yield_same_fingerprint(self) -> None:
        """Path object and string input produce identical output."""
        assert python_venv_fingerprint("/workspace") == python_venv_fingerprint(Path("/workspace"))


class TestGetVenvPathEmbedsSlug:
    """get_venv_path() embeds the slug in the venv directory name."""

    def test_venv_dir_name_includes_slug_self_install(self, tmp_path: Path) -> None:
        """Self-install: dir name is ``venv-{slug}-py{MM}-{hash}``."""
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        result = get_venv_path(tmp_path)
        expected_slug = project_path_slug(tmp_path)
        assert f"venv-{expected_slug}-py" in str(result.name), (
            f"Expected slug {expected_slug!r} in dir name {result.name!r}"
        )

    def test_venv_dir_name_includes_slug_normal_install(self, tmp_path: Path) -> None:
        """Normal install: same slug embedding applies."""
        result = get_venv_path(tmp_path)
        expected_slug = project_path_slug(tmp_path)
        assert f"venv-{expected_slug}-py" in str(result.name)

    def test_different_project_dirs_produce_different_venv_paths(
        self, tmp_path: Path
    ) -> None:
        """Two project dirs on the same host get distinct venv paths."""
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        path_a = get_venv_path(tmp_path / "a")
        path_b = get_venv_path(tmp_path / "b")
        assert path_a != path_b
        assert path_a.name != path_b.name


class TestSlugFilesystemSafety:
    """Parametrized confirmation: every slug is filesystem-safe."""

    @pytest.mark.parametrize(
        "input_path",
        [
            "/workspace",
            "/home/user/proj",
            "/home/user with spaces/proj",
            "/path/with/unicode/日本語/proj",
            "/path/with.dots/proj",
            "/some/ProjectName_v2",
            "/" + "a" * 100,
            "/a/b/c/d/e/f/g/h/i/j/k/l/m/n/o/p/q/r/s/t/u/v/w/x/y/z",
        ],
    )
    def test_slug_uses_only_safe_characters(self, input_path: str) -> None:
        result = project_path_slug(input_path)
        assert re.match(r"^[A-Za-z0-9_-]+$", result), f"Unsafe slug {result!r} from {input_path!r}"
        assert result, "slug must be non-empty"
