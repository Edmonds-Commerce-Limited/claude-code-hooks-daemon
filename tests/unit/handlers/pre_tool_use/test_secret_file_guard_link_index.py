"""Ordinary commands in a large project are judged from the link index (Plan 00623 phase 2).

The second independent review of Plan 00614 found that past the per-call
scan's 512-directory cap, a computed ``cd`` followed by a relative word was
denied as "could not be worked out", in a project with no link at all. With
the link index built, those commands are judged on what the project holds:
allowed where no link reaches a protected path, denied where one does.

Synthetic fixtures only: the protected file is a dummy outside the project,
its name assembled so this file never spells one. Process cwd is ``/``.
"""

from __future__ import annotations

import subprocess
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
#: Past the per-call scan's cap, so only the index can finish.
_DIRECTORIES = sfm.LINK_SCAN_DIRECTORY_CAP + 88
#: More link-holding directories than the walkers resolve word by word.
_HARMLESS_LINK_DIRECTORIES = sfm.LINK_DIRECTORY_CAP + 4

#: Review 261118-independent-review-2, Usability finding, and its cap513 list.
USABILITY = [
    'cd "$D" && grep -r x .',
    "cd - && cat r.md",
    "cd && cat r.md",
    "cd $(echo x) && ls",
    "cd ~/vault",
    "cd ~- && echo hi",
    "bash -c 'cd clean && cat plain.txt'",
    'cd "$TMPDIR" && python3 x.py',
    'for d in w00*/; do (cd "$d" && make); done',
    'cd "$(dirname "$0")" && ./run.sh',
    'cd "$OLDPWD" && git status',
    'cd "$(mktemp -d)" && ls',
]

#: The same moves, then a read of the link that leads to the protected dummy.
REACHING = [
    'cd "$D" && cat late',
    "cd - && cat late",
    "cd && cat late",
    "cd $(echo x) && cat late",
    "cd ~- && cat late",
    "bash -c 'cd w300 && cat late'",
    'cd "$OLDPWD" && head late',
    'cd "$D" && cat dl/' + _PROTECTED,
]


@dataclass(frozen=True)
class Project:
    root: Path
    outside: Path


def _build(tmp_path: Path, *, harmless_links: bool) -> Project:
    base = tmp_path.resolve()
    outside = base / "outside"
    outside.mkdir()
    (outside / _PROTECTED).write_bytes(b"DUMMY\n")
    root = base / "proj"
    root.mkdir()
    for number in range(_DIRECTORIES):
        (root / f"w{number:03d}").mkdir()
    (root / "clean").mkdir()
    (root / "clean" / "plain.txt").write_bytes(b"hello\n")
    (root / "r.md").write_bytes(b"hello\n")
    if harmless_links:
        # Like node_modules/.bin: links that stay inside the project.
        for number in range(_HARMLESS_LINK_DIRECTORIES):
            holder = root / f"w{number:03d}" / ".bin"
            holder.mkdir()
            (holder / "tool").symlink_to(root / "r.md")
    return Project(root=root, outside=outside)


@pytest.fixture(params=[False, True], ids=["no-links", "harmless-links"])
def big(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Project]:
    project = _build(tmp_path, harmless_links=request.param)
    monkeypatch.chdir("/")
    monkeypatch.setenv("TMPDIR", str(project.outside))
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(project.root)),
        patch.object(sfm, "resolve_project_root", return_value=str(project.root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(project.root)),
    ):
        index_project(project.root, SecretFileGuardHandler()._patterns())
        yield project
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


def _built(project: Project) -> None:
    link_index.prewarm(str(project.root))
    link_index.wait_for_link_index(60.0)
    assert link_index.link_scan_for(str(project.root)) is not None


def _decision(project: Project, command: str) -> Decision:
    handler = SecretFileGuardHandler()
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(project.root),
    }
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


@pytest.mark.parametrize("command", USABILITY)
def test_an_ordinary_command_is_allowed_once_the_index_is_built(big: Project, command: str) -> None:
    _built(big)
    assert _decision(big, command) is Decision.ALLOW


@pytest.mark.parametrize("command", REACHING)
def test_a_move_then_a_read_of_a_link_out_is_denied(big: Project, command: str) -> None:
    (big.root / "w300" / "late").symlink_to(big.outside / _PROTECTED)
    (big.root / "w301" / "dl").symlink_to(big.outside)
    _built(big)
    assert _decision(big, command) is Decision.DENY


@pytest.mark.parametrize("command", REACHING)
def test_a_link_made_after_the_build_is_seen(big: Project, command: str) -> None:
    _built(big)
    (big.root / "w300" / "late").symlink_to(big.outside / _PROTECTED)
    (big.root / "w301" / "dl").symlink_to(big.outside)
    assert _decision(big, command) is Decision.DENY


@pytest.mark.parametrize("command", ['cd "$D" && cat r.md', "cd - && cat plain.txt"])
def test_before_the_index_is_built_the_bounded_scan_still_denies(
    big: Project, command: str
) -> None:
    with patch.object(link_index, "link_scan_for", return_value=None):
        assert _decision(big, command) is Decision.DENY


@pytest.mark.parametrize("command", ['cd "$D" && cat r.md', "cd - && cat plain.txt"])
def test_an_overflowed_index_denies(
    big: Project, command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(link_index, "BUILD_DIRECTORY_CAP", 64)
    link_index.prewarm(str(big.root))
    link_index.wait_for_link_index(60.0)
    assert _decision(big, command) is Decision.DENY


def test_the_index_is_not_read_from_any_project_file(big: Project) -> None:
    """Nothing the agent can write is consulted: the index is in daemon memory only."""
    _built(big)
    before = set(big.root.rglob("*"))
    _decision(big, 'cd "$D" && cat r.md')
    assert set(big.root.rglob("*")) == before


_COLD = "cold index (the bounded scan stops at its cap)"
_TOPLEVEL = 'cd "$(git rev-parse --show-toplevel)"'


@pytest.fixture()
def cold(big: Project) -> Iterator[Project]:
    """The link index is not built: only placement can keep a move from denying."""
    with patch.object(link_index, "link_scan_for", return_value=None):
        yield big


@pytest.fixture()
def home(cold: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path.resolve() / "home"
    (directory / "vault").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(directory))
    return directory


class TestMovesOutsideTheProjectArePlaced:
    @pytest.mark.parametrize(
        "command",
        [
            "cd ~/vault && cat r.md",
            "cd ~ && ls",
            'cd "$HOME/vault" && cat r.md',
            'cd "$TMPDIR" && python3 x.py',
        ],
    )
    def test_a_move_outside_the_project_is_allowed_once_the_index_is_built(
        self, home: Path, cold: Project, command: str
    ) -> None:
        """Placement never excuses a stopped scan (see the class below), so a cold
        index past the cap still denies a reader; the built index allows these."""
        with patch.object(link_index, "link_scan_for", wraps=_real_link_scan_for):
            _built(cold)
            assert _decision(cold, command) is Decision.ALLOW

    @pytest.mark.parametrize("command", ["cd ~/vault && cat r.md", 'cd "$HOME/vault" && cat r.md'])
    def test_a_move_outside_the_project_then_a_read_denies_with_a_cold_index(
        self, home: Path, cold: Project, command: str
    ) -> None:
        assert _decision(cold, command) is Decision.DENY, _COLD

    @pytest.mark.parametrize(
        "command",
        [
            "HOME=/elsewhere; cd ~ && cat r.md",
            'export TMPDIR=x; cd "$TMPDIR" && cat r.md',
            'cd "$HOME" && cd "$HOME/vault" && cat r.md',
        ],
    )
    def test_a_command_that_may_reassign_the_variable_is_not_placed(
        self, home: Path, cold: Project, command: str
    ) -> None:
        assert _decision(cold, command) is Decision.DENY

    def test_a_link_in_the_placed_directory_is_still_judged(
        self, home: Path, cold: Project
    ) -> None:
        (home / "vault" / "late").symlink_to(cold.outside / _PROTECTED)
        assert _decision(cold, "cd ~/vault && cat late") is Decision.DENY

    def test_a_home_inside_the_project_is_not_placed(
        self, cold: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(cold.root / "w001"))
        assert _decision(cold, "cd ~ && cat r.md") is Decision.DENY

    def test_a_relative_word_into_the_project_from_home_is_resolved(
        self, cold: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (cold.root / "w300" / "late").symlink_to(cold.outside / _PROTECTED)
        monkeypatch.setenv("HOME", str(cold.root.parent))
        assert _decision(cold, "cd ~ && cat proj/w300/late") is Decision.DENY


class TestPlacementIsRefusedWhereTheShellMayLandElsewhere:
    """The daemon's value is used only where bash expands the variable and keeps it."""

    @pytest.mark.parametrize(
        ("target", "command"),
        [
            # Quoted: bash moves to a literal directory, not to the variable's value.
            ("~", 'cd "~" && cat late'),
            ("~/vault", "cd '~/vault' && cat late"),
            ("~", "cd \\~ && cat late"),
            ("$HOME", "cd '$HOME' && cat late"),
            ("$HOME/vault", "cd '$HOME/vault' && cat late"),
            ("$TMPDIR", "cd \\$TMPDIR && cat late"),
            # A command that can set the variable without naming it.
            ("~", ". ./env.sh && cd ~ && cat late"),
            ("~", "source env.sh; cd ~ && cat late"),
            ("$TMPDIR", 'eval "$V"; cd "$TMPDIR" && cat late'),
            ("$HOME", 'declare "$N=x"; cd "$HOME" && cat late'),
            ("$HOME", 'read -r "$N"; cd "$HOME" && cat late'),
            ("$HOME", 'printf -v "$N" x; cd "$HOME" && cat late'),
        ],
    )
    def test_it_is_not_placed(self, home: Path, cold: Project, target: str, command: str) -> None:
        assert sfm.place_outside_project(target, command) == ()

    def test_a_physical_move_through_a_link_into_the_project_is_not_placed(
        self, home: Path, cold: Project
    ) -> None:
        (cold.root / "w300" / "deep").mkdir()
        (cold.outside / "x").symlink_to(cold.root / "w300" / "deep")
        command = 'cd -P "$TMPDIR/x/.." && cat late'
        assert sfm.place_outside_project("$TMPDIR/x/..", command) == ()

    @pytest.mark.parametrize(
        ("target", "command"),
        [
            ("~/vault", "cd ~/vault && grep 'x' r.md"),
            ("$HOME/vault", 'cd "$HOME/vault" && cat r.md'),
            ("$TMPDIR", 'cd "$TMPDIR" && printf "%s" x'),
        ],
    )
    def test_an_ordinary_move_is_still_placed(
        self, home: Path, cold: Project, target: str, command: str
    ) -> None:
        assert sfm.place_outside_project(target, command) != ()


#: Each read the protected dummy in real bash; the guard must deny however the scan ended.
#: The links sit under the LAST top-level directory, past where the per-call scan stops.
_REACHING_AFTER_PLACEMENT = (
    "cd w599; v=HO; getopts i ${v}ME -i; cd ~; cat late",
    "cd w599; v=HO; let ${v}ME=7; cd ~; cat late",
    "cd w599; v=HO; ((${v}ME=7)); cd ~; cat late",
    "cd w599; v=HO; : $((${v}ME=7)); cd ~; cat late",
    "cd w599; v=HO; x[${v}ME=7]=1; cd ~; cat late",
    "cd w599; v=TMP; let ${v}DIR=7; cd $TMPDIR; cat late",
    'ln -s "$PWD/w599/zz" ~/new && cd ~/new && cat late',
    'cd -P "$TMPDIR/up/.." && cat proj/w599/zz/late',
    # A recursive search: judged by recursive_search, not the directory walk.
    "cd w599; v=HO; let ${v}ME=7; cd ~; grep -r x dl",
    # git's top level, moved by config or environment the guard cannot read.
    "printf '[co''re]\\n\\twork''tree = %s\\n' \"$PWD/w599/zz\" >> .g''it/conf''ig; "
    'cd "$(git rev-parse --show-toplevel)" && cat late',
    "trap 'export G\"\"IT_WORK_TREE=$PWD/w599/zz' DEBUG; "
    'cd "$(git rev-parse --show-toplevel)" && cat late',
    "trap 'export G\"\"IT_WORK_TREE=$PWD/w599/zz' DEBUG; "
    'cd "$(git rev-parse --show-toplevel)" && grep -r x dl',
)


class TestAStoppedScanIsNotOverriddenByPlacement:
    """Plan 00623 adversarial review: placing ~, $HOME or $TMPDIR never excuses a scan
    that stopped. The placement trusts the daemon's value, and the shell's can differ:
    a builtin the placement does not list sets it (getopts, let, arithmetic), or a
    link is made at the placed path by the same command. Each of these read the
    protected dummy in real bash while the guard allowed it with the scan stopped."""

    @pytest.fixture()
    def reach(self, home: Path, cold: Project) -> Project:
        last = cold.root / f"w{_DIRECTORIES - 1:03d}"
        assert last.name == "w599"
        for name in ("7", "i", "zz"):
            (last / name).mkdir()
            (last / name / "late").symlink_to(cold.outside / _PROTECTED)
            (last / name / "dl").symlink_to(cold.outside)
        (cold.outside / "up").symlink_to(cold.root)
        subprocess.run(["git", "init", "-q", str(cold.root)], check=True)
        return cold

    @pytest.mark.parametrize("name", ["gl", "sub/.git/gl"])
    def test_a_link_inside_a_git_directory_is_indexed(self, reach: Project, name: str) -> None:
        """Bash can move into `.git` like any directory; a built index that skipped it
        reported complete while a link there led to the protected dummy."""
        holder = reach.root / ".git" if name == "gl" else reach.root / "sub" / ".git"
        holder.mkdir(parents=True, exist_ok=True)
        (holder / "gl").symlink_to(reach.outside / _PROTECTED)
        moved = ".git" if name == "gl" else "sub/.git"
        with patch.object(link_index, "link_scan_for", wraps=_real_link_scan_for):
            _built(reach)
            assert _decision(reach, f"cd $(printf {moved}) && cat gl") is Decision.DENY

    @pytest.mark.parametrize("command", _REACHING_AFTER_PLACEMENT)
    def test_a_cold_index_denies(self, reach: Project, command: str) -> None:
        assert _decision(reach, command) is Decision.DENY

    @pytest.mark.parametrize("command", _REACHING_AFTER_PLACEMENT)
    def test_an_overflowed_index_denies(self, reach: Project, command: str) -> None:
        overflowed = link_index.LinkIndex(str(reach.root), {}, overflowed=True)
        # A context patch, not monkeypatch: it must unwind before `cold` restores the original.
        with patch.object(link_index, "link_scan_for", lambda root: overflowed.verify()):
            assert _decision(reach, command) is Decision.DENY

    @pytest.mark.parametrize("command", _REACHING_AFTER_PLACEMENT)
    def test_a_built_index_denies(self, reach: Project, command: str) -> None:
        with patch.object(link_index, "link_scan_for", wraps=_real_link_scan_for):
            _built(reach)
            assert _decision(reach, command) is Decision.DENY

    def test_an_unlistable_directory_stops_the_per_call_scan(
        self, cold: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A searchable but unreadable directory: bash moves through it, the scan cannot list it."""
        small = tmp_path.resolve() / "small"
        (small / "a" / "b").mkdir(parents=True)
        (small / "a" / "b" / "late").symlink_to(cold.outside / _PROTECTED)
        assert sfm.scan_project_links(str(small)).complete
        real_scandir = sfm.os.scandir

        def refuse(path: Any) -> Any:
            if str(path) == str(small / "a"):
                raise PermissionError(13, "refused", str(path))
            return real_scandir(path)

        monkeypatch.setattr(sfm.os, "scandir", refuse)
        assert not sfm.scan_project_links(str(small)).complete


_real_link_scan_for = link_index.link_scan_for


class TestPersistedWorktreeConfig:
    """N667: the top-level idiom is not placed at an ancestor when git config may move it."""

    @pytest.fixture()
    def repo(self, cold: Project) -> Project:
        subprocess.run(["git", "init", "-q", str(cold.root)], check=True)
        return cold

    def test_without_it_the_top_level_is_not_relocated(self, repo: Project) -> None:
        """The predicate only: since review F3 a stopped scan denies the idiom anyway."""
        assert not sfm.toplevel_relocated([str(repo.root)])

    @pytest.mark.parametrize("command", [f"{_TOPLEVEL} && cat r.md", f"{_TOPLEVEL} && grep -r x ."])
    def test_a_persisted_core_worktree_denies_with_a_cold_index(
        self, repo: Project, command: str
    ) -> None:
        subprocess.run(
            ["git", "-C", str(repo.root), "config", "core.worktree", str(repo.root / "w000")],
            check=True,
        )
        assert _decision(repo, command) is Decision.DENY

    def test_a_value_that_merely_mentions_worktree_does_not_relocate(self, repo: Project) -> None:
        subprocess.run(
            ["git", "-C", str(repo.root), "config", "branch.main.route", "worktree_create"],
            check=True,
        )
        assert not sfm.toplevel_relocated([str(repo.root)])

    def test_a_git_work_tree_in_the_environment_denies(
        self, repo: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GIT_WORK_TREE", str(repo.root / "w000"))
        assert _decision(repo, f"{_TOPLEVEL} && cat r.md") is Decision.DENY
