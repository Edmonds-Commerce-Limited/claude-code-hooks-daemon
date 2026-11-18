"""A command that hands a whole directory to a reader is a read of every file in it.

Plan 00618 Task 2.1 and Plan 00615. ``find <dir> -exec cat {} +``,
``find <dir> | xargs cat``, ``tar cf - <dir>``, ``cp -r <dir> x``,
``diff -r <dir> <dir2>``, ``git diff --no-index <dir> <dir2>`` and ``zip -r`` /
``rsync`` name no protected file, yet put every file under ``<dir>`` into the
output. The twin tests hold the narrowing: the same shapes over a directory
with no protected file, and the actions that read no content, stay allowed.
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

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
_PROTECTED = f"demo.{_SUFFIX}"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose root and ``deep`` hold a protected file; ``sub`` and ``sub2`` hold none."""
    root = tmp_path / "project"
    root.mkdir()
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    for clean in ("sub", "sub2"):
        (root / clean).mkdir()
        (root / clean / "plain.txt").write_bytes(b"hello\n")
    (root / "deep").mkdir()
    (root / "deep" / f"key.{_SUFFIX}").write_bytes(b"not-a-real-secret\n")
    (root / "hop").mkdir()
    (root / "hop" / "up").symlink_to(Path("..") / "deep", target_is_directory=True)
    (root / "link").symlink_to(root / "deep", target_is_directory=True)
    (root / "cleanlink").symlink_to(root / "sub", target_is_directory=True)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _verdict(root: Path, command: str, *, cwd: Path | None = None) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


_DIRECTORY_READERS = [
    "git diff --no-index deep sub",
    "git diff --no-index sub deep",
    "git diff --no-index --stat deep sub",
    "git --no-pager diff --no-index deep sub",
    "diff -r deep sub",
    "diff -rq deep sub",
    "diff --recursive deep sub",
    "diff deep sub",
    "diff sub deep",
    "tar cf - deep",
    "tar -cf - deep",
    "tar czf x.tgz deep",
    "tar -C deep -cf - .",
    "tar -Cdeep -cf - .",
    "tar --directory=deep -cf - .",
    "tar --directory deep -cf - .",
    "tar -cf - -C deep .",
    "gtar cf - deep",
    "cp -r deep x",
    "cp -R deep x",
    "cp -a deep x",
    "cp -r deep/ x",
    "cp -rt x deep",
    "cp --recursive deep x",
    "zip -r x.zip deep",
    "rsync -r deep x",
    "rsync -a deep/ x",
    "rsync -av deep/ x/",
    "scp -r deep host:x",
]

_FIND_READERS = [
    "find deep -exec cat {} +",
    "find deep -exec cat {} \\;",
    "find deep -type f -exec head -n 5 {} +",
    "find deep -execdir cat {} +",
    "find deep -ok cat {} \\;",
    "find deep -okdir cat {} \\;",
    "find deep -exec sh -c 'cat \"$1\"' _ {} \\;",
    "find deep -exec bash -c 'cat \"$@\"' _ {} +",
    "find deep -exec file {} +",
    "find deep -exec cp {} x \\;",
    "find deep -exec python3 -c 'pass' {} +",
    "find deep -exec ./cat {} +",
    "find deep -exec $READER {} +",
    "find deep -exec ls {} \\; -exec cat {} \\;",
    "find deep -exec cat",
    "find deep | xargs cat",
    "find deep -print0 | xargs -0 cat",
    "find deep -type f | xargs -n 1 cat",
    "find deep | xargs -I{} cat {}",
    "find deep | xargs -I {} sh -c 'cat {}'",
    "find deep | xargs --max-args 1 cat",
    "find deep | xargs --arg-file=list cat",
    "find deep | xargs cp -t x",
    "find deep | sort | xargs cat",
    "find deep | xargs $READER",
    "find deep | xargs ./cat",
]

_WRAPPED = [
    "cd deep && find . -exec cat {} +",
    "cd deep && find . | xargs cat",
    "cd deep && tar cf - .",
    "cd deep && cp -r . ../x",
    "cd deep && diff -r . ../sub",
    "bash -c 'find deep -exec cat {} +'",
    "bash -c 'find deep | xargs cat'",
    "bash -c 'tar cf - deep'",
    "bash -c 'cd deep && cp -r . ../x'",
    "sudo find deep -exec cat {} +",
    "sudo tar cf - deep",
    "sudo cp -r deep x",
    "timeout 5 find deep -exec cat {} +",
    "timeout 5 tar cf - deep",
    "timeout 5 cp -r deep x",
    "find deep | sudo xargs cat",
    "find deep | timeout 5 xargs cat",
    "find deep | xargs sudo cat",
    "find deep | xargs timeout 5 cat",
    "eval 'find deep -exec cat {} +'",
    "echo hi; tar cf - deep",
]

_THROUGH_A_LINK = [
    "find link -exec cat {} +",
    "find link | xargs cat",
    "tar cf - link",
    "tar cf - link/",
    "cp -r link x",
    "diff -r link sub",
    "git diff --no-index link sub",
    "cd link && cp -r . x",
    "cd link && find . -exec cat {} +",
    "find cleanlink/../link -exec cat {} +",
    # `..` after a link steps out of the link's TARGET, not out of its directory.
    "find hop/up/.. -exec cat {} +",
    "find hop/up/.. | xargs cat",
    "tar cf - hop/up/..",
    "cp -r hop/up/.. x",
]


class TestDirectoryReadersAreDenied:
    """The directory holds a protected file, so handing it to a reader is a read of it."""

    @pytest.mark.parametrize("command", _DIRECTORY_READERS)
    def test_archive_copy_and_diff_of_the_directory(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize("command", _FIND_READERS)
    def test_find_exec_and_xargs_reader_over_the_directory(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize("command", _WRAPPED)
    def test_through_cd_shell_and_wrappers(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize("command", _THROUGH_A_LINK)
    def test_through_a_symlinked_directory(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    def test_absolute_root_is_judged_from_elsewhere(self, project: Path) -> None:
        command = f"find {project / 'deep'} | sort | xargs cat"
        assert _verdict(project, command, cwd=project / "sub") is Decision.DENY

    @pytest.mark.parametrize("command", ["git ls-files | xargs cat", "ls | xargs cat"])
    def test_xargs_reader_fed_by_another_producer_judges_the_cwd(
        self, project: Path, command: str
    ) -> None:
        """The paths are unknown, so the working directory is the tree they come from."""
        assert _verdict(project, command) is Decision.DENY


class TestTwinsOverACleanDirectoryStayAllowed:
    """The same shapes over ``sub`` (no protected file) read nothing protected."""

    @pytest.mark.parametrize(
        "command",
        [
            "git diff --no-index sub sub2",
            "git diff --no-index --stat sub sub2",
            "diff -r sub sub2",
            "diff sub sub2",
            "tar cf - sub",
            "tar czf x.tgz sub",
            "tar -C sub -cf - .",
            "tar --directory=sub -cf - .",
            "cp -r sub x",
            "cp -a sub x",
            "zip -r x.zip sub",
            "rsync -r sub x",
            "rsync -a sub/ x",
            "find sub -exec cat {} +",
            "find sub -exec cat {} \\;",
            "find sub -type f -exec head -n 5 {} +",
            "find sub -execdir cat {} +",
            "find sub -exec sh -c 'cat \"$1\"' _ {} \\;",
            "find sub | xargs cat",
            "find sub -print0 | xargs -0 cat",
            "find sub | sort | xargs cat",
            "cd sub && find . -exec cat {} +",
            "cd sub && tar cf - .",
            "cd sub && cp -r . ../x",
            "bash -c 'find sub -exec cat {} +'",
            "sudo find sub -exec cat {} +",
            "timeout 5 tar cf - sub",
            "find sub | sudo xargs cat",
            "find cleanlink -exec cat {} +",
            "tar cf - cleanlink",
            "cp -r cleanlink x",
        ],
    )
    def test_clean_directory_is_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW

    @pytest.mark.parametrize("command", ["ls | xargs cat", "git ls-files | xargs cat"])
    def test_xargs_reader_fed_by_another_producer_from_a_clean_cwd(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command, cwd=project / "sub") is Decision.ALLOW


class TestActionsThatReadNoContentStayAllowed:
    """``find`` over the protected directory with an action that never opens a file."""

    @pytest.mark.parametrize(
        "command",
        [
            "find deep -name x -print",
            "find deep -name x",
            "find deep -type d",
            "find deep -exec ls {} +",
            "find deep -exec ls -l {} \\;",
            "find deep -exec stat {} +",
            "find deep -exec echo {} +",
            "find deep -exec basename {} \\;",
            "find deep -exec dirname {} \\;",
            "find deep -exec true {} \\;",
            "find deep -type f -exec rm {} +",
            "find deep -type f -exec chmod 600 {} +",
            "find deep -type d -exec mkdir -p x {} \\;",
            "find deep -exec touch {} +",
            "find deep | xargs echo",
            "find deep | xargs ls",
            "find deep | xargs -0 ls -l",
            "find deep | xargs -n 1 echo",
            "find deep | xargs -I{} echo {}",
            "find deep | xargs rm",
            "find deep | xargs",
            "find deep | xargs --max-args 1 echo",
            "find deep -exec ls {} \\; -exec echo {} \\;",
        ],
    )
    def test_content_free_action_is_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW


class TestWhatTheDirectoryReadersDoNotJudge:
    """Unchanged: history, files, and destinations are not a read of the directory."""

    @pytest.mark.parametrize(
        "command",
        [
            "git diff",
            "git diff HEAD",
            "git diff --stat",
            "git diff --cached",
            "git diff HEAD~1 -- sub",
            "git log --oneline",
            "cp sub/plain.txt sub/copy.txt",
            "cp sub/plain.txt .",
            "cp -r sub deep",
            "rsync -a sub/ deep/",
            "cp -t deep sub/plain.txt",
            "diff sub/plain.txt sub2/plain.txt",
            "tar cf - sub/plain.txt",
        ],
    )
    def test_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW
