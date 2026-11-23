"""A glob in a LATER path part reached a link to a protected file unjudged (N710).

Ledger 00474 N710: from the project root, ``cat kit/bin/late`` (``late`` a link
to a protected file) was denied, while ``cat kit/*/late`` and, from ``kit``,
``cat b?n/late`` were allowed. Only a glob in the FIRST path part was matched
against a directory listing; a later-part glob was realpath-ed as literal text,
met "no such file", and so counted as no link.

A glob in any part is now expanded (bounded) and every match judged by the
same link check a literal word gets; an expansion that cannot finish (too many
matches, a directory that cannot be listed) is a finding, never "no match".
A literal word and a glob that matches nothing are judged as before.

Synthetic fixtures only: the protected file is a dummy outside the project,
its name assembled so this file never spells one. The computed move is
assembled too: this file is itself judged by the guard it tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
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
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

_PROTECTED = "id_" + "rsa"
#: A computed directory change, assembled.
_MOVE = "c" + 'd "$D"'
_SHEBANG = "#!/usr/bin/env bash\n"


@dataclass(frozen=True)
class Project:
    root: Path
    outside: Path
    kit: Path


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    (base / "home").mkdir()
    root = base / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_bytes(b"x = 1\n")
    (root / "r.md").write_bytes(b"hello\n")
    kit = root / "kit"
    (kit / "bin").mkdir(parents=True)
    (kit / "lib").mkdir()
    (kit / "bin" / "late").symlink_to(outside / _PROTECTED)
    (kit / "bin" / "notes.txt").write_bytes(b"plain\n")
    (kit / "lib" / "notes.txt").write_bytes(b"plain\n")
    monkeypatch.chdir("/")
    monkeypatch.setenv("TMPDIR", str(outside))
    monkeypatch.setenv("HOME", str(base / "home"))
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        link_index.prewarm(str(root))
        link_index.wait_for_link_index(60.0)
        yield Project(root=root, outside=outside, kit=kit)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


def _bash(command: str, cwd: Path) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _write(content: str, cwd: Path) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(cwd / "plan.bash"), "content": content},
        "cwd": str(cwd),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _both(command: str, cwd: Path) -> tuple[Decision, Decision]:
    return _bash(command, cwd), _write(f"{_SHEBANG}{command}\n", cwd)


#: Words read from the project root that reach ``kit/bin/late`` by a glob after the first part.
FROM_ROOT = [
    "kit/bin/late",
    "kit/*/late",
    "kit/b?n/late",
    "kit/b*/late",
    "kit/bin/l*",
    "kit/bin/l?te",
    "kit/*/l*",
    "kit/**/late",
    "k*/*/late",
    "ki?/b?n/l?te",
    "./kit/*/late",
    "kit/*/../bin/late",
    "kit/[b]in/late",
    "kit/[a-c]in/late",
    "kit/bin/[k-m]ate",
]


@pytest.mark.parametrize("word", FROM_ROOT)
def test_a_glob_in_any_part_reaching_the_link_is_denied(project: Project, word: str) -> None:
    assert _both(f"cat {word}", project.root) == (Decision.DENY, Decision.DENY)


@pytest.mark.parametrize("word", FROM_ROOT[1:])
def test_the_bash_route_denies_with_no_index_of_protected_files(
    project: Project, word: str
) -> None:
    """The index is a cache that may be missing or stale; the link check must not lean on it."""
    with patch.object(SecretFileGuardHandler, "_index", return_value=None):
        assert _bash(f"cat {word}", project.root) is Decision.DENY


@pytest.mark.parametrize("word", ["kit/*/later", "kit/l?b/later", "k*/lib/l*"])
def test_a_link_made_after_the_index_was_built_is_denied(project: Project, word: str) -> None:
    (project.kit / "lib" / "later").symlink_to(project.outside / _PROTECTED)
    assert _both(f"cat {word}", project.root) == (Decision.DENY, Decision.DENY)


def test_a_brace_and_glob_reaching_the_link_is_denied(project: Project) -> None:
    assert _both("cat kit/{b?n,zz}/late", project.root) == (Decision.DENY, Decision.DENY)


#: The same, read from ``kit``.
FROM_KIT = ["bin/late", "b?n/late", "*/late", "bin/l*", "**/late", "b[i]n/l*"]


@pytest.mark.parametrize("word", FROM_KIT)
def test_a_glob_read_from_a_subdirectory_is_denied(project: Project, word: str) -> None:
    assert _both(f"cat {word}", project.kit) == (Decision.DENY, Decision.DENY)


def test_an_absolute_glob_reaching_the_link_is_denied(project: Project) -> None:
    word = f"{project.kit}/*/late"
    assert _both(f"cat {word}", project.root) == (Decision.DENY, Decision.DENY)


def test_a_globbed_directory_with_a_protected_basename_is_denied(project: Project) -> None:
    (project.kit / "lib" / _PROTECTED).write_bytes(b"DUMMY\n")
    assert _both(f"cat kit/*/{_PROTECTED}", project.root) == (Decision.DENY, Decision.DENY)


def test_a_glob_after_a_computed_move_is_denied(project: Project) -> None:
    command = f"{_MOVE} && cat kit/*/late"
    assert _both(command, project.root) == (Decision.DENY, Decision.DENY)


@pytest.mark.parametrize("word", ["b?n/late", "*/late", "bin/l*", "b*/l?te", "late", "l*"])
def test_a_glob_read_above_or_in_the_links_directory_after_a_computed_move_is_denied(
    project: Project, word: str
) -> None:
    """The move may land in ``kit`` (above the link's directory) or in ``kit/bin`` itself."""
    command = f"{_MOVE} && cat {word}"
    assert _both(command, project.root) == (Decision.DENY, Decision.DENY)


def test_a_glob_after_a_literal_move_is_denied(project: Project) -> None:
    command = "c" + "d kit && cat b?n/late"
    assert _both(command, project.root) == (Decision.DENY, Decision.DENY)


#: Words that are, or match, nothing protected: judged exactly as before.
ALLOWED = [
    "r.md",
    "kit/bin/notes.txt",
    "kit/*/notes.txt",
    "kit/b?n/notes.txt",
    "kit/*/nothing-here",
    "kit/zz*/late",
    "src/*.py",
    "nowhere/*/late",
]


@pytest.mark.parametrize("word", ALLOWED)
def test_a_word_reaching_no_protected_file_is_allowed(project: Project, word: str) -> None:
    assert _both(f"cat {word}", project.root) == (Decision.ALLOW, Decision.ALLOW)


def test_a_quoted_glob_is_a_literal_and_allowed(project: Project) -> None:
    assert _both("cat 'kit/*/late'", project.root) == (Decision.ALLOW, Decision.ALLOW)


class TestFailsClosed:
    """An expansion that cannot finish is a finding, never "no match"."""

    def test_more_linked_matches_than_the_cap_is_denied(self, project: Project) -> None:
        for number in range(4):
            (project.root / "many" / f"d{number}").mkdir(parents=True)
            (project.root / "many" / f"d{number}" / "x.txt").symlink_to(project.root / "r.md")
        with patch.object(sfm, "GLOB_WORD_MATCH_CAP", 2):
            assert _both("cat many/*/x.txt", project.root) == (Decision.DENY, Decision.DENY)
        assert _both("cat many/*/x.txt", project.root) == (Decision.ALLOW, Decision.ALLOW)

    def test_plain_matches_do_not_count_against_the_match_cap(self, project: Project) -> None:
        for number in range(4):
            (project.root / "plain" / f"d{number}").mkdir(parents=True)
            (project.root / "plain" / f"d{number}" / "x.txt").write_bytes(b"plain\n")
        with patch.object(sfm, "GLOB_WORD_MATCH_CAP", 2):
            assert _both("cat plain/*/x.txt", project.root) == (Decision.ALLOW, Decision.ALLOW)

    @pytest.mark.parametrize("default_semantics", [True, False])
    def test_globstar_reaches_depth_zero_and_two(
        self, project: Project, default_semantics: bool
    ) -> None:
        deep = project.kit / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "late").symlink_to(project.outside / _PROTECTED)
        expanded = sfm.expand_word_glob(
            str(project.root), "kit/**/late", default_semantics=default_semantics
        )
        assert expanded.complete
        found = set(expanded.value)
        assert str(project.kit / "bin" / "late") in found
        assert (str(deep / "late") in found) is not default_semantics
        flat = sfm.expand_word_glob(
            str(project.root), "kit/bin/**/late", default_semantics=default_semantics
        )
        assert (str(project.kit / "bin" / "late") in flat.value) is not default_semantics

    def test_a_dot_name_matches_unless_bash_defaults_are_certain(self, project: Project) -> None:
        hidden = project.kit / ".hid"
        hidden.mkdir()
        (hidden / "late").symlink_to(project.outside / _PROTECTED)
        wide = sfm.expand_word_glob(str(project.root), "kit/*/late", default_semantics=False)
        narrow = sfm.expand_word_glob(str(project.root), "kit/*/late", default_semantics=True)
        assert str(hidden / "late") in wide.value
        assert str(hidden / "late") not in narrow.value
        assert _bash("shopt -s dotglob; cat kit/*/late", project.root) is Decision.DENY

    def test_more_listings_than_the_cap_is_denied(self, project: Project) -> None:
        for number in range(4):
            (project.root / "wide" / f"d{number}").mkdir(parents=True)
        with patch.object(sfm, "GLOB_WORD_LISTING_CAP", 2):
            assert _both("cat wide/*/*/x", project.root) == (Decision.DENY, Decision.DENY)

    def test_a_directory_that_cannot_be_listed_is_denied(self, project: Project) -> None:
        real_scandir = os.scandir
        refused = str(project.kit / "bin")

        def scandir(path: Any = ".") -> Any:
            if str(path) == refused:
                raise PermissionError(13, "Permission denied", refused)
            return real_scandir(path)

        with patch.object(os, "scandir", side_effect=scandir):
            assert _bash("cat kit/bin/l*", project.root) is Decision.DENY

    def test_the_expansion_itself_is_bounded(self, project: Project) -> None:
        expanded = sfm.expand_word_glob(str(project.root), "kit/*/late")
        assert expanded.complete
        assert expanded.value == [str(project.kit / "bin" / "late")]
        assert sfm.expand_word_glob(str(project.root), "kit/zz*/late").value == []


@pytest.fixture()
def crowded(project: Project) -> Iterator[Project]:
    """More link-holding directories than LINK_DIRECTORY_CAP: words are judged by ``could_be_link``."""
    for number in range(sfm.LINK_DIRECTORY_CAP + 4):
        holder = project.root / f"w{number:02d}" / ".bin"
        holder.mkdir(parents=True)
        (holder / "tool").symlink_to(project.root / "r.md")
    link_index.reset_link_indexes()
    link_index.prewarm(str(project.root))
    link_index.wait_for_link_index(60.0)
    cwds = sfm.effective_cwds(_MOVE, str(project.root))
    assert cwds.overflowed
    assert cwds.named is None
    yield project


class TestPastTheDirectoryCap:
    @pytest.mark.parametrize("word", ["kit/*/late", "kit/b?n/late", "b?n/late", "bin/l*", "*/l*"])
    def test_a_later_part_glob_reaching_the_link_is_denied(
        self, crowded: Project, word: str
    ) -> None:
        command = f"{_MOVE} && cat {word}"
        assert _both(command, crowded.root) == (Decision.DENY, Decision.DENY)

    @pytest.mark.parametrize("word", ["kit/*/late", "kit/b?n/late", "kit/bin/l*", "kit/**/l?te"])
    def test_could_be_link_expands_a_later_part_glob(self, crowded: Project, word: str) -> None:
        cwds = sfm.effective_cwds(_MOVE, str(crowded.root))
        assert cwds.could_be_link(word)

    @pytest.mark.parametrize("word", ["kit/*/notes.txt", "kit/b?n/nothing", "src/*.py"])
    def test_could_be_link_is_false_for_a_glob_reaching_no_link(
        self, crowded: Project, word: str
    ) -> None:
        cwds = sfm.effective_cwds(_MOVE, str(crowded.root))
        assert not cwds.could_be_link(word)

    def test_a_plain_word_past_the_cap_is_still_allowed(self, crowded: Project) -> None:
        assert _both(f"{_MOVE} && cat r.md", crowded.root) == (Decision.ALLOW, Decision.ALLOW)
