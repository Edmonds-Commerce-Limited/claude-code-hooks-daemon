"""A walk that stops early never ends in an allow (Plan 00623, phase 1).

Every test here asserts a handler verdict or a function result on a synthetic
project: a throwaway directory that holds a dummy named like a protected file
OUTSIDE it, and links inside it that lead there. The process cwd is ``/``
throughout, as in the daemon. Protected names are assembled so this file never
spells one.
"""

import errno
import os
import shlex
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import (
    flaggable_content_channel_guard as flaggable_module,
)
from claude_code_hooks_daemon.handlers.pre_tool_use import (
    quarantine_artefact_read_guard as quarantine_module,
)
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_content_channel_guard import (
    FlaggableContentChannelGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.quarantine_artefact_read_guard import (
    QuarantineArtefactReadGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.protected_file_index import ProtectedFileIndex
from claude_code_hooks_daemon.utils.resolution_failure import ResolutionFailedError

_PROTECTED = "id_" + "rsa"
_DUMMY = b"DUMMY\n"
#: A directory name long enough that a 4,050-byte word joined to the project exceeds PATH_MAX.
_LONG_ROOT_NAME = "R" * 150
_PATH_MAX = 4096


@dataclass(frozen=True)
class Project:
    """The project the daemon serves, and the directory outside it the links lead to."""

    root: Path
    outside: Path
    index: ProtectedFileIndex


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    """A project with a file link, a directory link and a link inside a subdirectory."""
    base = tmp_path.resolve() / _LONG_ROOT_NAME
    outside = base / "outside"
    outside.mkdir(parents=True)
    (outside / _PROTECTED).write_bytes(_DUMMY)
    root = base / "proj"
    root.mkdir()
    (root / "readme.txt").write_bytes(b"hello\n")
    (root / "flink").symlink_to(os.path.relpath(outside / _PROTECTED, root))
    (root / "olink").symlink_to(os.path.relpath(outside, root))
    (root / "plain").mkdir()
    (root / "plain" / "note.txt").write_bytes(b"hello\n")
    inner = root / "inner"
    inner.mkdir()
    (inner / "rel").symlink_to(os.path.relpath(outside / _PROTECTED, inner))
    (root / "own").mkdir()
    (root / "own" / _PROTECTED).write_bytes(_DUMMY)
    monkeypatch.chdir("/")
    protected_file_index.reset_index_cache()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index = index_project(root, SecretFileGuardHandler()._patterns())
        yield Project(root=root, outside=outside, index=index)
    protected_file_index.reset_index_cache()


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _decision(hook_input: dict[str, Any]) -> Decision:
    """The secret guard's decision on ``hook_input`` (an exception counts as no verdict)."""
    handler = SecretFileGuardHandler()
    try:
        if not handler.matches(hook_input):
            return Decision.ALLOW
        return handler.handle(hook_input).decision
    except Exception:
        return Decision.ASK


def _bash_decision(project: Project, command: str) -> Decision:
    return _decision(_bash(command, project.root))


def _nested(command: str, levels: int) -> str:
    """``command`` inside ``levels`` nested ``bash -c`` bodies."""
    for _ in range(levels):
        command = f"bash -c {shlex.quote(command)}"
    return command


class TestNestingDepth:
    """N664 and the N662 depth item: a body past the depth limit is judged, not skipped."""

    @pytest.mark.parametrize("levels", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_a_nested_search_through_a_link_out_is_denied_at_any_depth(
        self, project: Project, levels: int
    ) -> None:
        command = _nested("grep -r x olink", levels)
        assert _bash_decision(project, command) is Decision.DENY

    @pytest.mark.parametrize("levels", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_a_nested_directory_change_and_read_is_denied_at_any_depth(
        self, project: Project, levels: int
    ) -> None:
        command = _nested("env -C inner cat rel", levels)
        assert _bash_decision(project, command) is Decision.DENY

    @pytest.mark.parametrize("levels", [1, 2, 6, 8])
    def test_a_nested_command_that_reads_nothing_is_still_allowed(
        self, project: Project, levels: int
    ) -> None:
        assert _bash_decision(project, _nested("echo hello", levels)) is Decision.ALLOW


class TestPlacementStat:
    """N663: a word the kernel opens but the guard cannot place is denied."""

    @pytest.mark.parametrize("hops", [448, 449, 450])
    def test_a_word_that_fits_path_max_only_relative_to_the_project_is_denied(
        self, project: Project, hops: int
    ) -> None:
        word = "plain/../" * hops + "flink"
        joined = f"{project.root}/{word}"
        assert len(word.encode()) < _PATH_MAX <= len(joined.encode())
        assert _bash_decision(project, f"cat {word}") is Decision.DENY

    def test_a_long_word_that_is_no_path_is_allowed(self, project: Project) -> None:
        assert _bash_decision(project, "echo " + "x" * 5000) is Decision.ALLOW

    def test_a_long_prose_word_with_slashes_is_allowed(self, project: Project) -> None:
        word = "/".join(["aGVsbG8gd29ybGQ" * 4] * 90)
        assert len(word.encode()) > _PATH_MAX
        assert _bash_decision(project, f"echo {word}") is Decision.ALLOW

    def test_a_word_with_a_component_over_name_max_is_allowed(self, project: Project) -> None:
        word = "q" * 300 + "/z"
        assert _bash_decision(project, f"echo {word}") is Decision.ALLOW


class TestProcSelf:
    """N668: a path through the daemon's own /proc/self cannot be placed, so it is denied."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat /proc/self/cwd/flink",
            "cat /proc/self/cwd/olink/i*",
            "grep -r x /proc/self/cwd/olink",
            "cat /dev/fd/../cwd/flink",
            "cat /proc/thread-self/cwd/flink",
            "cat //proc//self/./cwd/flink",
            "cd / && cat proc/self/cwd/flink",
            "cd /proc && cat self/cwd/flink",
        ],
    )
    def test_a_word_through_proc_self_is_denied(self, project: Project, command: str) -> None:
        assert _bash_decision(project, command) is Decision.DENY

    def test_the_read_tool_through_proc_self_is_denied(self, project: Project) -> None:
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "/proc/self/cwd/flink"}}
        assert _decision(hook_input) is Decision.DENY

    def test_the_grep_tool_through_proc_self_is_denied(self, project: Project) -> None:
        hook_input = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "x", "path": "/proc/self/cwd/olink"},
            "cwd": str(project.root),
        }
        assert _decision(hook_input) is Decision.DENY

    @pytest.mark.parametrize("command", ["cat /proc/self/status", "cat /proc/self/cgroup"])
    def test_an_ordinary_proc_self_read_is_denied_too(
        self, project: Project, command: str
    ) -> None:
        """The rule is as specified: it cannot tell these from a read through ``cwd``."""
        assert _bash_decision(project, command) is Decision.DENY

    def test_a_proc_path_that_is_not_self_is_allowed(self, project: Project) -> None:
        assert _bash_decision(project, "cat /proc/version") is Decision.ALLOW


class TestSilentStops:
    """Item 6: a slice or an unreadable parent never drops what was not looked at."""

    def test_a_globbed_move_from_more_bases_than_the_cap_is_unscanned(
        self, project: Project, tmp_path: Path
    ) -> None:
        bases = []
        for number in range(sfm.LINK_DIRECTORY_CAP + 4):
            directory = tmp_path / f"base{number}"
            (directory / "sub").mkdir(parents=True)
            bases.append(str(directory))
        command = " ; ".join(f"cd {base}" for base in bases) + " ; cd su*"
        cwds = sfm.effective_cwds(command, str(project.root))
        assert cwds.unscanned

    def test_a_relative_move_from_more_bases_than_the_cap_is_unscanned(
        self, project: Project, tmp_path: Path
    ) -> None:
        bases = []
        for number in range(sfm.LINK_DIRECTORY_CAP + 4):
            directory = tmp_path / f"base{number}"
            (directory / "sub").mkdir(parents=True)
            bases.append(str(directory))
        command = " ; ".join(f"cd {base}" for base in bases) + " ; cd sub"
        assert sfm.effective_cwds(command, str(project.root)).unscanned

    def test_a_wildcard_parent_that_cannot_be_listed_is_unresolvable(
        self, project: Project
    ) -> None:
        real_scandir = os.scandir

        def refuse(path: Any) -> Any:
            if str(path) == str(project.root):
                raise PermissionError(errno.EACCES, "refused", str(path))
            return real_scandir(path)

        with (
            patch.object(protected_file_index.os, "scandir", refuse),
            pytest.raises(ResolutionFailedError),
        ):
            project.index.glob_matches("ol*/x", [str(project.root)])

    def test_a_wildcard_parent_that_does_not_exist_expands_nothing(self, project: Project) -> None:
        assert project.index.glob_matches("nothere/ol*/x", [str(project.root)]) is None

    def test_a_symlinked_directory_parent_that_cannot_be_listed_is_unresolvable(
        self, project: Project
    ) -> None:
        real_scandir = os.scandir

        def refuse(path: Any) -> Any:
            if str(path) == str(project.root):
                raise PermissionError(errno.EACCES, "refused", str(path))
            return real_scandir(path)

        with (
            patch.object(protected_file_index.os, "scandir", refuse),
            pytest.raises(ResolutionFailedError),
        ):
            project.index._matching_symlinked_directories(
                [*str(project.root).strip("/").split("/"), "ol*"]
            )

    def test_a_symlinked_directory_parent_that_does_not_exist_holds_none(
        self, project: Project
    ) -> None:
        missing = [*str(project.root).strip("/").split("/"), "nothere", "ol*"]
        assert project.index._matching_symlinked_directories(missing) == []


class TestGuardsMapAFailedPlacementToADeny:
    """Item 2: every guard that calls the walkers denies on a placement that failed."""

    def test_the_quarantine_guard_denies_when_its_literal_recheck_cannot_place_a_word(
        self, project: Project
    ) -> None:
        handler = QuarantineArtefactReadGuardHandler()
        hook_input = _bash("cat readme.txt", project.root)
        with (
            patch.object(handler, "_evaluate_matched_pattern", side_effect=TimeoutError),
            patch.object(
                quarantine_module.sfm,
                "find_protected_mention_strict",
                side_effect=ResolutionFailedError("unplaceable"),
            ),
        ):
            found = handler._matched_pattern(hook_input)
        assert found is not None
        assert found[0] != quarantine_module._NOT_JUDGED_PATTERN

    def test_the_flaggable_guard_denies_when_a_word_cannot_be_placed(
        self, project: Project
    ) -> None:
        handler = FlaggableContentChannelGuardHandler()
        handler._flaggable_path_globs = ["flagged/**"]
        hook_input = _bash("grep x readme.txt", project.root)
        with patch.object(
            flaggable_module.sfm,
            "find_protected_mention",
            side_effect=ResolutionFailedError("unplaceable"),
        ):
            try:
                matched = handler.matches(hook_input)
                decision = handler.handle(hook_input).decision if matched else Decision.ALLOW
            except ResolutionFailedError:
                decision = Decision.ASK
        assert decision is Decision.DENY
