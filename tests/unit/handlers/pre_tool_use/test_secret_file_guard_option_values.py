"""Text that is not a path is not judged as one (GitHub #200).

(a) the value of a git search option is a search string; (b) the value of a
grep/rg filename filter is a basename filter scoped to the searched path; (c) a
colon split never yields a wildcard-only part. Genuinely named protected paths
still deny.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
_PROTECTED = f"demo.{_SUFFIX}"
_SEARCH_STRING = "org.freedesktop." + _SUFFIX + "s"


def _reindex(root: Path) -> None:
    index_project(root, SecretFileGuardHandler()._patterns())


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose root holds a protected file; ``sub`` holds none."""
    root = tmp_path / "project"
    root.mkdir()
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    (root / "sub").mkdir()
    (root / "sub" / "plain.txt").write_bytes(b"hello\n")
    (root / "deep").mkdir()
    (root / "deep" / f"key.{_SUFFIX}").write_bytes(b"not-a-real-secret\n")
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        _reindex(root)
        yield root
    protected_file_index.reset_index_cache()


def _verdict(root: Path, command: str) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestGitSearchStringIsNotAFile:
    """(a) -S/-G/--grep/--author/--committer values are search strings."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git log --oneline -1 -S {_SEARCH_STRING} | cat",
            f"git log -S{_SEARCH_STRING}",
            f"git log -G {_SEARCH_STRING}",
            f"git log -G{_SEARCH_STRING}",
            f"git log --grep {_SEARCH_STRING}",
            f"git log --grep={_SEARCH_STRING}",
            f"git log --author={_SEARCH_STRING}",
            f"git log --author {_SEARCH_STRING}",
            f"git log --committer={_SEARCH_STRING}",
            f"git log --grep-reflog={_SEARCH_STRING}",
            f"git rev-list --all --grep={_SEARCH_STRING}",
            f"git whatchanged -S {_SEARCH_STRING}",
            f"git show --grep={_SEARCH_STRING} HEAD",
        ],
    )
    def test_search_string_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW

    @pytest.mark.parametrize(
        "command",
        [
            f"git log -- {_PROTECTED}",
            f"git show HEAD:{_PROTECTED}",
            f"git diff {_PROTECTED}",
            f"git log -S foo -- {_PROTECTED}",
            f"git log --grep=foo {_PROTECTED}",
            f"git log -S {_PROTECTED}x -- {_PROTECTED}",
        ],
    )
    def test_named_pathspec_still_denied(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY


class TestGrepFilterValueIsScopedToSearchedPath:
    """(b) --include/--exclude/-g values are basename filters under the searched path."""

    @pytest.mark.parametrize(
        "command",
        [
            "grep -rl zz sub --include=* | wc -l",
            "grep -rl zz sub --include '*' | wc -l",
            "grep -rl zz sub --exclude=* | wc -l",
            "grep -rl zz sub --exclude-dir=* | wc -l",
            "rg -l zz sub -g '*'",
            "rg -l zz sub --glob '*'",
            "rg -l zz sub --glob=*",
            "rg -l zz sub --iglob '*'",
        ],
    )
    def test_filter_over_clean_directory_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -r x . --include=*.{_SUFFIX}",
            "grep -r x . --include=*",
            "grep -r x deep --include=*",
            "rg x --glob=*",
            "grep -r x sub deep --include=*",
            "grep -r x * --include=*",
            f"grep -r x deep --include=*.{_SUFFIX}",
            "rg x . -g '*'",
            f"rg x . --glob '*.{_SUFFIX}'",
            f"grep -r x {_PROTECTED}",
        ],
    )
    def test_filter_that_can_match_protected_file_still_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY


class TestGrepFilterRelaxationNeedsRootsInsideProject:
    """The index only vouches for the project: roots outside it, or reached by a link, deny."""

    @pytest.fixture()
    def outside(self, project: Path) -> Path:
        """A directory beside the project holding a protected file, plus link fixtures."""
        out = project.parent / "outside"
        out.mkdir()
        (out / f"o.{_SUFFIX}").write_bytes(b"not-a-real-secret\n")
        (project / "outlnk").symlink_to(out)
        (project / "clean").mkdir()
        (project / "clean" / "lnk").symlink_to(project / "deep")
        return out

    def test_absolute_root_outside_project_denied(self, project: Path, outside: Path) -> None:
        command = f"grep -r . --include=* {outside}"
        assert _verdict(project, command) is Decision.DENY

    def test_absolute_root_outside_project_with_secret_glob_denied(
        self, project: Path, outside: Path
    ) -> None:
        command = f"grep -r . --include=*.{_SUFFIX}* {outside}"
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize("root", ["/etc", "/root/.ssh"])
    def test_system_roots_denied(self, project: Path, root: str) -> None:
        assert _verdict(project, f"grep -r . --include=* {root}") is Decision.DENY
        assert _verdict(project, f"grep -r . --include=*.{_SUFFIX}* {root}") is Decision.DENY

    def test_symlink_root_resolving_outside_denied(self, project: Path, outside: Path) -> None:
        assert _verdict(project, "grep -r . --include=* outlnk") is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -R x --include=* clean",
            "grep --dereference-recursive x --include=* clean",
            "rg -L x clean --glob=*",
            "rg --follow x clean --glob=*",
        ],
    )
    def test_symlink_following_flags_denied(
        self, project: Path, outside: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "rg --follow x clean -g '*'",
            "rg -L x clean -g '*'",
            "rg --follow x clean --glob '*'",
            "rg --follow x clean --iglob '*'",
            'rg -L x clean -g "*"',
            "grep -R x clean --include '*'",
            "rg x outlnk -g '*'",
            "rg x /etc -g '*'",
        ],
    )
    def test_separate_value_filter_judged_like_attached(
        self, project: Path, outside: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        ["rg x sub -g '*'", "rg x sub --glob '*'", "grep -rl zz sub --include '*'"],
    )
    def test_separate_value_filter_over_clean_root_allowed(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.ALLOW

    def test_clean_root_inside_project_still_allowed(self, project: Path) -> None:
        (project / "untracked" / "scratch" / "sub").mkdir(parents=True)
        command = "grep -rl zz untracked/scratch/sub --include=*"
        assert _verdict(project, command) is Decision.ALLOW

    def test_clean_absolute_root_inside_project_still_allowed(self, project: Path) -> None:
        assert _verdict(project, f"grep -rl zz {project / 'sub'} --include=*") is Decision.ALLOW


class TestColonSplitYieldsNoWildcardOnlyPart:
    """(c) ``2:**`` is bold markdown, not ``prefix:path``."""

    def test_bold_markdown_in_python_heredoc_allowed(self, project: Path) -> None:
        command = "python3 - <<'PY'\n" 's = "x"\n' 'print("**Option 2:** build" in s)\n' "PY"
        assert _verdict(project, command) is Decision.ALLOW

    def test_wildcard_only_parts_are_dropped(self) -> None:
        assert sfm._colon_path_parts("2:**") == []
        assert sfm._colon_path_parts("a:*") == []
        assert "**" not in sfm._colon_path_parts("a:b:**")

    @pytest.mark.parametrize(
        "token",
        [f"host:{_PROTECTED}", f"HEAD:{_PROTECTED}", f"rev:path/{_PROTECTED}"],
    )
    def test_real_colon_path_parts_kept(self, token: str) -> None:
        assert token.split(":", 1)[1] in sfm._colon_path_parts(token)

    @pytest.mark.parametrize(
        "command",
        [
            f"scp host:{_PROTECTED} .",
            f"git show HEAD:{_PROTECTED}",
            f"git show rev:path/{_PROTECTED}",
        ],
    )
    def test_colon_path_naming_protected_file_still_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY
