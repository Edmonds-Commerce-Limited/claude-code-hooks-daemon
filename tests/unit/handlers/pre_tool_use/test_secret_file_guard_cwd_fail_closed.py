"""Working out where a command runs never ends in an allow (Plan 00614, review 614b).

Review 614b found that a ``cd`` to a name the filesystem refuses to stat (one
component over NAME_MAX) made ``Path.is_dir()`` raise inside the directory walk,
and the raise ended in the guard's allow-with-advisory route: every protected
read in the same command went unjudged. The same raise was reachable through a
glob whose literal parent is over-long. A failure while placing a command's
words is now a finding, never an allow.

Every fixture is synthetic: a throwaway primary checkout holding untracked dummy
files named like a protected one, a registered ``git worktree`` of it with
directory links only (no file link at its root, so a glob read from the root
matches nothing by accident), and one in-project dummy. The process cwd is ``/``
throughout, as in the daemon.
"""

import os
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
from claude_code_hooks_daemon.utils import path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_PROTECTED = "id_" + "rsa"
_DUMMY = b"DUMMY\n"
#: One path component longer than NAME_MAX (255 bytes on Linux).
_LONG = "A" * 300
#: A path longer than PATH_MAX (4096 bytes), every component within NAME_MAX.
_LONGER_THAN_PATH_MAX = "/".join(["B" * 200] * 30)


@dataclass(frozen=True)
class Tree:
    """The primary checkout and its worktree, the project the daemon serves."""

    primary: Path
    worktree: Path


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Tree]:
    """A worktree whose links lead to directories of the primary that hold dummies."""
    base = tmp_path.resolve()
    primary = base / "primary"
    primary.mkdir()
    _git("init", "-q", "-b", "main", cwd=primary)
    _git("config", "user.email", "test@example.invalid", cwd=primary)
    _git("config", "user.name", "test", cwd=primary)
    (primary / "readme.txt").write_bytes(b"hello\n")
    _git("add", "-A", cwd=primary)
    _git("commit", "-qm", "init", cwd=primary)
    (primary / _PROTECTED).write_bytes(_DUMMY)
    (primary / "sub").mkdir()
    (primary / "sub" / _PROTECTED).write_bytes(_DUMMY)

    worktree = base / "wt"
    _git("worktree", "add", "-q", "-b", "feat", str(worktree), cwd=primary)
    (worktree / "dlink").symlink_to(os.path.relpath(primary / "sub", worktree))
    (worktree / "plink").symlink_to(os.path.relpath(primary, worktree))
    inner = worktree / "inner"
    inner.mkdir()
    (inner / "ilink").symlink_to(os.path.relpath(primary / _PROTECTED, inner))
    (inner / "plain.txt").write_bytes(b"hello\n")
    deep = worktree / "deep"
    deep.mkdir()
    (deep / "idlink").symlink_to(os.path.relpath(primary / "sub", deep))
    (worktree / "clean").mkdir()
    (worktree / "clean" / "plain.txt").write_bytes(b"hello\n")
    # An in-project dummy, indexed: a read of it is a finding without any link.
    (worktree / "own").mkdir()
    (worktree / "own" / _PROTECTED).write_bytes(_DUMMY)

    monkeypatch.chdir("/")
    protected_file_index.reset_index_cache()
    root = str(worktree)
    with (
        patch.object(guard_module, "resolve_project_root", return_value=root),
        patch.object(sfm, "resolve_project_root", return_value=root),
        patch.object(path_exclusion, "resolve_project_root", return_value=root),
    ):
        index_project(worktree, SecretFileGuardHandler()._patterns())
        yield Tree(primary=primary, worktree=worktree)
    protected_file_index.reset_index_cache()


def _result(tree: Tree, command: str) -> tuple[Decision, str]:
    """The decision on ``command`` run from the worktree, and its deny reason or advisory."""
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(tree.worktree),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW, ""
    result = handler.handle(hook_input)
    return result.decision, str(result.reason or "") + " ".join(result.context or [])


def _decision(tree: Tree, command: str) -> Decision:
    return _result(tree, command)[0]


class TestOverLongDirectoryChange:
    """R1: a move to a name the filesystem cannot stat leaves every read judged."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cd {_LONG}; cat ../primary/{_PROTECTED}",
            f"cat ../primary/{_PROTECTED}; cd {_LONG}",
            f"git -C {_LONG} status; cat ../primary/{_PROTECTED}",
            f"cd {_LONG}; cat own/{_PROTECTED}",
            f"pushd {_LONG}; head own/{_PROTECTED}",
            f"cd /{_LONG} || cat own/{_PROTECTED}",
            f"env -C {_LONG} cat own/{_PROTECTED}",
            f"cd {_LONG}; cat inner/ilink",
            f"cd {_LONG}/x; cat inner/ilink",
        ],
    )
    def test_read_after_an_over_long_cd_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    def test_an_over_long_cd_alone_is_not_a_finding(self, tree: Tree) -> None:
        """Failing closed on the READS, not on the move itself."""
        assert _decision(tree, f"cd {_LONG}; cat clean/plain.txt") is Decision.ALLOW

    def test_the_directory_walk_never_raises_on_an_over_long_name(self, tree: Tree) -> None:
        cwds = sfm.effective_cwds(f"cd {_LONG} && cd x", str(tree.worktree))
        assert str(tree.worktree) in cwds


class TestOverLongGlobParent:
    """R2: a glob whose literal parent cannot be stat-ed leaves the next glob judged."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cat {_LONG}/d*/*; cat o*/*",
            f"cat /{_LONG}/d*/*; cat o*/*",
            f"cat {_LONG}/*/x; cat o*/*",
            f"grep -r x {_LONG}/d*; cat o*/*",
        ],
    )
    def test_glob_after_an_over_long_glob_parent_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    def test_the_index_never_raises_on_an_over_long_glob_parent(self, tree: Tree) -> None:
        index = protected_file_index.cached_index(
            str(tree.worktree), SecretFileGuardHandler()._patterns()
        )
        assert index is not None
        bases = [str(tree.worktree)]
        assert index.glob_matches(f"{_LONG}/d*/*", bases) is None
        assert index.link_out_of(f"{_LONG}/d*/*", bases) is None
        assert index.link_out_of(f"{_LONG}/x", bases) is None
        assert index.directories_matching(f"{_LONG}/d*/", bases) == ()


class TestUnreadableDirectoryChange:
    """EACCES, simulated (the suite may run as root, which never sees it)."""

    _MARKER = "eacces-marker"

    @pytest.fixture()
    def unreadable(self, tree: Tree) -> Iterator[None]:
        real_stat = os.stat

        def stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            spelled = "" if isinstance(path, int) else os.fsdecode(os.fspath(path))
            if self._MARKER in spelled:
                raise PermissionError(13, "Permission denied", path)
            return real_stat(path, *args, **kwargs)

        with patch.object(os, "stat", stat):
            yield

    @pytest.mark.parametrize(
        "command",
        [
            f"cd {_MARKER}/x; cat own/{_PROTECTED}",
            f"cd {_MARKER}/x; cat inner/ilink",
            f"cat {_MARKER}/d*/*; cat o*/*",
        ],
    )
    def test_read_after_an_unreadable_cd_denied(
        self, tree: Tree, unreadable: None, command: str
    ) -> None:
        assert _decision(tree, command) is Decision.DENY


class TestAResolutionFailureIsAFinding:
    """A raise while placing a command's words denies; it never reaches the advisory."""

    def test_a_raise_in_the_directory_walk_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic walk failure")

        monkeypatch.setattr(sfm._DirectoryWalk, "change", boom)
        decision, text = _result(tree, "cd clean && cat plain.txt")
        assert decision is Decision.DENY
        assert "could NOT fully judge" not in text
        assert "could not be worked out" in text

    def test_a_raise_in_link_resolution_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic link failure")

        monkeypatch.setattr(sfm, "_realpath_if_resolvable", boom)
        assert _decision(tree, "cat clean/plain.txt") is Decision.DENY

    def test_a_raise_in_glob_resolution_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic glob failure")

        monkeypatch.setattr(protected_file_index.ProtectedFileIndex, "_wildcard_links", boom)
        assert _decision(tree, "cat cl*/*") is Decision.DENY

    def test_a_raise_in_the_search_cwd_tracker_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils import recursive_search

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic search placement failure")

        monkeypatch.setattr(recursive_search, "_place", boom)
        assert _decision(tree, "cd clean && grep -r hello .") is Decision.DENY

    def test_the_literal_fallback_judges_names_before_any_filesystem_call(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The second opinion must not share the first scan's filesystem failure."""

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic walk failure")

        monkeypatch.setattr(sfm._DirectoryWalk, "change", boom)
        patterns = SecretFileGuardHandler()._patterns()
        command = f"cd x; cat {_PROTECTED}"
        assert sfm.find_protected_mention_strict(command, patterns, str(tree.worktree))


#: ``{d}`` is a directory and ``{r}`` a read of a link in it: a file link, or a search of a directory link.
_CD_READS = [("inner", "cat ilink"), ("deep", "grep -r x idlink"), ("deep", "cat idlink/*")]


class TestDirectoryChangeSpellings:
    """R3: every spelling of a move the shell runs places the reads after it."""

    @pytest.mark.parametrize(
        "form",
        [
            "builtin cd {d} && {r}",
            "command cd {d} && {r}",
            "command -p cd {d} && {r}",
            "builtin pushd {d} && {r}",
            "cd >/dev/null {d} && {r}",
            "cd 2>/dev/null {d} && {r}",
            "cd 2> /dev/null {d} && {r}",
            ">/dev/null cd {d} && {r}",
            "2>/dev/null cd {d} && {r}",
            "cd {d} 2>/dev/null && {r}",
            "pushd {d} >/dev/null; {r}",
            "sudo -D {d} {r}",
            "sudo --chdir={d} {r}",
            "sudo --chdir {d} {r}",
            "sudo -u root -D {d} {r}",
        ],
    )
    @pytest.mark.parametrize(("directory", "read"), _CD_READS)
    def test_read_after_the_move_denied(
        self, tree: Tree, form: str, directory: str, read: str
    ) -> None:
        assert _decision(tree, form.format(d=directory, r=read)) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "tar -C inner -chf - ilink",
            "tar --directory=inner -chf - ilink",
            "tar --directory inner -chf - ilink",
            "tar -chf - -C inner ilink",
            "tar -Cinner -chf - ilink",
        ],
    )
    def test_a_tool_chdir_option_places_its_operands(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "builtin cd clean && cat plain.txt",
            "command cd clean && cat plain.txt",
            "cd 2>/dev/null clean && cat plain.txt",
            "sudo -D clean cat plain.txt",
            "tar -C clean -cf - plain.txt",
            "cd clean && grep -r hello .",
        ],
    )
    def test_an_ordinary_move_allowed(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.ALLOW


class TestGlobFromADirectoryThatIsALinkOut:
    """R5: after a move into a link out of the project, a glob with no slash reads there too."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd dlink && cat *",
            "cd dlink && cat i*",
            "cd dlink && head -n 5 *",
            "cd dlink && cat -- *",
            "pushd dlink >/dev/null; cat i*",
            "cd deep/idlink && cat *",
            "cd deep && cd idlink && cat i*",
            "cd plink && cat i*",
            "cd plink && cat s*/*",
            "cd plink && cat */*",
            "cd plink && cat ?d_*",
            "cd dlink && cat ./*",
        ],
    )
    def test_glob_read_from_a_link_out_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        ["cat *", "cat */*", "cd clean && cat *", "cd clean && cat */*", "cd inner && cat p*"],
    )
    def test_glob_read_from_the_project_allowed(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.ALLOW


class TestComputedDirectoryChange:
    """R4: a cd whose target is a glob or is computed is judged from where it can lead."""

    @pytest.mark.parametrize(
        "command",
        [
            "cd inn?r && cat ilink",
            "cd inne[r] && cat ilink",
            "cd i* && cat ilink",
            'D=inner; cd "$D" && cat ilink',
            "D=inner && cd $D && cat ilink",
            'export D=inner; cd "${D}" && cat ilink',
            'cd "$(echo inner)" && cat ilink',
            "cd `echo inner` && cat ilink",
            'cd "$UNSET_DIRECTORY_614" && cat ilink',
            "cd de?p && grep -r x idlink",
            'cd "$(echo deep)" && grep -r x idlink',
            'cd "$(echo deep)" && cat idlink/*',
        ],
    )
    def test_read_after_a_computed_cd_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$(git rev-parse --show-toplevel)" && ls',
            "cd cle?n && cat plain.txt",
            'D=clean; cd "$D" && cat plain.txt',
            'cd "$(echo clean)" && cat plain.txt',
        ],
    )
    def test_an_ordinary_computed_cd_allowed(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.ALLOW

    @pytest.mark.parametrize(
        "command",
        [
            'x="$(env -C inner cat ilink)"; echo "$x"',
            'x="$(git -C inner diff --no-index ilink /dev/null)"',
            'export x="$(env -C inner cat ilink)"',
        ],
    )
    def test_a_move_inside_an_assigned_value_is_walked(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "reassignment",
        [
            "export D=$(echo inner)",
            "declare -x D=inner",
            "read D <<< inner",
            "A=1 D=inner",
        ],
    )
    def test_a_reassignment_it_cannot_read_still_fails_closed(
        self, tree: Tree, reassignment: str
    ) -> None:
        command = f'D=clean; {reassignment}; cd "$D" && cat ilink'
        assert _decision(tree, command) is Decision.DENY

    def test_a_loop_variable_still_fails_closed(self, tree: Tree) -> None:
        command = 'D=clean; for D in inner; do cd "$D" && cat ilink; done'
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize("target", ["**/nope", "*/*/*/*/*/nope", "/*/*/*/nope"])
    def test_a_globbed_target_costs_a_bounded_walk(self, tree: Tree, target: str) -> None:
        """A glob that matches nothing is not followed through the whole tree (or filesystem)."""
        with patch.object(sfm.os, "scandir", wraps=os.scandir) as spy:
            assert _decision(tree, f"cd {target} && cat clean/plain.txt") is Decision.ALLOW
        assert spy.call_count <= 3 * sfm.LINK_SCAN_DIRECTORY_CAP


def _grow(top: Path, width: int, depth: int) -> None:
    """``depth`` levels of ``width`` empty directories each under ``top``."""
    level = [top]
    top.mkdir()
    for _ in range(depth):
        following: list[Path] = []
        for directory in level:
            for number in range(width):
                child = directory / f"d{number:02d}"
                child.mkdir()
                following.append(child)
        level = following


class TestAWideGlobbedDirectoryChange:
    """Review 614c X1: a globbed cd matching many directories is judged as a computed move.

    Bash refuses a cd with more than one match, so following every match only
    cost time: one command over a 22x22x22 tree took longer than the scan
    deadline, and a recursive search beside it was then allowed.
    """

    @pytest.fixture()
    def wide(self, tree: Tree) -> Tree:
        _grow(tree.worktree / "t", 22, 3)
        return tree

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r DUMMY own; cd t/*/*/*",
            "grep -r DUMMY own; (cd t/*/*/*)",
            "(cd t/*/*/*); grep -r DUMMY own",
            "echo $(cd t/*/*/*); grep -r DUMMY own",
            "bash -c 'cd t/*/*/*'; grep -r DUMMY own",
            "grep -r DUMMY own && echo 'cd t/*/*/*'",
        ],
    )
    def test_a_search_beside_a_wide_cd_is_denied_by_the_search_check(
        self, wide: Tree, command: str
    ) -> None:
        decision, text = _result(wide, command)
        assert decision is Decision.DENY, text
        # The search check itself, not a fallback after the scan gave up.
        assert "could NOT fully judge" not in text
        assert "could not be worked out" not in text
        assert "stopped before" not in text

    def test_the_walk_keeps_no_match_of_a_wide_cd(self, wide: Tree) -> None:
        cwds = sfm.effective_cwds("cd t/*/*/*; ls", str(wide.worktree))
        assert len(cwds) <= 2 * sfm.LINK_DIRECTORY_CAP
        assert not any("/t/" in directory for directory in cwds)

    def test_the_search_walk_keeps_no_match_of_a_wide_cd(self, wide: Tree) -> None:
        from claude_code_hooks_daemon.utils import recursive_search

        reads = recursive_search.search_reads("cd t/*/*/*; grep -r x .", str(wide.worktree))
        assert len(reads) <= 2 * sfm.LINK_DIRECTORY_CAP
        assert not any("/t/" in read.root for read in reads)

    def test_a_wide_cd_costs_a_bounded_walk(self, wide: Tree) -> None:
        """The work is counted, not timed: listings and cwds stay within the caps."""
        command = "cd t/*; cd */*/*; cd t/*/*/*; grep -r DUMMY own"
        with patch.object(sfm.os, "scandir", wraps=os.scandir) as spy:
            assert _decision(wide, command) is Decision.DENY
        assert spy.call_count <= 6 * sfm.LINK_SCAN_DIRECTORY_CAP
        assert len(sfm.effective_cwds(command, str(wide.worktree))) <= 2 * sfm.LINK_DIRECTORY_CAP

    def test_a_flat_directory_of_many_matches_is_capped(self, tree: Tree) -> None:
        _grow(tree.worktree / "t", 40, 1)
        cwds = sfm.effective_cwds("cd t/*; ls", str(tree.worktree))
        assert not any("/t/" in directory for directory in cwds)
        assert sfm.expand_directory_glob(str(tree.worktree), "t/*") is None
        from claude_code_hooks_daemon.utils import recursive_search

        reads = recursive_search.search_reads("cd t/*; grep -r x .", str(tree.worktree))
        assert not any("/t/" in read.root for read in reads)
        # Bash refuses the cd, so the search runs where the command already was.
        assert str(tree.worktree) in {read.root for read in reads}

    def test_a_narrow_globbed_cd_is_still_followed(self, tree: Tree) -> None:
        _grow(tree.worktree / "t", 3, 1)
        cwds = sfm.effective_cwds("cd t/d0[01]; ls", str(tree.worktree))
        assert str(tree.worktree / "t" / "d00") in cwds
        assert str(tree.worktree / "t" / "d01") in cwds


class TestAWideCdInAProjectWithNoLinkOut:
    """Review 614c X1b: a harmless wide cd is not denied for the number of directories."""

    @pytest.fixture()
    def plain(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
        project = tmp_path.resolve() / "project"
        project.mkdir()
        _git("init", "-q", "-b", "main", cwd=project)
        _grow(project / "t", 20, 3)
        monkeypatch.chdir("/")
        protected_file_index.reset_index_cache()
        root = str(project)
        with (
            patch.object(guard_module, "resolve_project_root", return_value=root),
            patch.object(sfm, "resolve_project_root", return_value=root),
            patch.object(path_exclusion, "resolve_project_root", return_value=root),
        ):
            index_project(project, SecretFileGuardHandler()._patterns())
            yield project
        protected_file_index.reset_index_cache()

    @pytest.mark.parametrize("command", ["cd t/*/*/*; ls", "cd t && cd */*/*; ls"])
    def test_a_wide_cd_then_ls_allowed(self, plain: Path, command: str) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(plain),
        }
        handler = SecretFileGuardHandler()
        assert not handler.matches(hook_input) or (
            handler.handle(hook_input).decision is Decision.ALLOW
        )


#: Brace expansions past the enumeration cap: the full scan gives up on them.
_OVER_THE_CAP = ["echo {a..z}{a..z}{a..z}", "echo {1..300000}"]


class TestAScanThatGivesUpBesideASearchOrGlob:
    """Review 614c P2: a cap or deadline hit never lets a search or a glob read through.

    The literal fallback judges names only. A recursive search or a glob in the
    same command reads what only the full scan could judge, so it is denied.
    """

    _GAVE_UP = "stopped before"

    @pytest.mark.parametrize("prefix", _OVER_THE_CAP)
    @pytest.mark.parametrize(
        "read",
        ["grep -r DUMMY own", "rg DUMMY own", "grep -R DUMMY .", "cat o*/*", "head -n1 own/*"],
    )
    def test_a_cap_hit_denies_a_search_or_glob(self, tree: Tree, prefix: str, read: str) -> None:
        decision, text = _result(tree, f"{prefix}; {read}")
        assert decision is Decision.DENY, text
        assert self._GAVE_UP in text

    @pytest.mark.parametrize(
        "command", ["grep -r DUMMY own", "cat o*/*", "cd clean && grep -r hello ."]
    )
    def test_a_deadline_hit_denies_a_search_or_glob(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        decision, text = _result(tree, command)
        assert decision is Decision.DENY, text
        assert self._GAVE_UP in text

    def test_a_deadline_hit_with_no_cwd_still_denies_a_search(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "grep -r DUMMY ."},
        }
        handler = SecretFileGuardHandler()
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision is Decision.DENY

    def test_a_raise_judging_the_search_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils import recursive_search

        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic search failure")

        monkeypatch.setattr(recursive_search, "search_reads", boom)
        decision, text = _result(tree, f"{_OVER_THE_CAP[0]}; ls")
        assert decision is Decision.DENY, text

    @pytest.mark.parametrize("prefix", _OVER_THE_CAP)
    def test_a_cap_hit_with_no_search_or_glob_stays_an_advisory(
        self, tree: Tree, prefix: str
    ) -> None:
        decision, text = _result(tree, f"{prefix}; ls clean")
        assert decision is Decision.ALLOW
        assert "could NOT fully judge" in text

    def test_a_deadline_hit_with_no_search_or_glob_stays_an_advisory(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        decision, text = _result(tree, "cat clean/plain.txt")
        assert decision is Decision.ALLOW
        assert "could NOT fully judge" in text

    def test_a_literal_protected_path_still_names_its_pattern(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "SCAN_DEADLINE_SECONDS", -1.0)
        decision, text = _result(tree, f"grep -r x own; cat own/{_PROTECTED}")
        assert decision is Decision.DENY
        assert self._GAVE_UP not in text


class TestWrappedChdirCommand:
    """A wrapper before a command with a chdir option does not hide the option."""

    @pytest.mark.parametrize(
        "command",
        [
            "sudo tar -C inner -chf - ilink",
            "nice git -C inner diff --no-index ilink /dev/null",
            "timeout 5 git -C inner diff --no-index ilink /dev/null",
            "nohup env -C inner cat ilink",
            "sudo -u root env -C inner cat ilink",
        ],
    )
    def test_wrapped_chdir_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY


#: Names a filesystem call may refuse, or that Python may refuse to encode.
_ODD_NAMES = [
    _LONG,
    f"/{_LONG}",
    f"{_LONG}/{_LONG}",
    _LONGER_THAN_PATH_MAX,
    f"/{_LONGER_THAN_PATH_MAX}",
    "~nosuchuser-614",
    "~nosuchuser-614/x",
    "~+",
    "~+/nowhere",
    "~-",
    "\ud800",
    f"x\ud800/{_LONG}",
]

#: Command shapes that move, or glob through, an odd name before a protected read.
_SHAPES = [
    "cd {name}; cat own/" + _PROTECTED,
    "cd {name} 2>/dev/null; grep -r DUMMY own",
    "pushd {name}; head own/" + _PROTECTED,
    "git -C {name} status; cat own/" + _PROTECTED,
    "env -C {name} cat own/" + _PROTECTED,
    "(cd {name}); cat inner/ilink",
    "cat {name}/d*/*; cat o*/*",
    "grep -r x {name}/d*; cat o*/*",
    "cd {name}; cd ..; cat o*/*",
]


@pytest.mark.parametrize("shape", _SHAPES)
@pytest.mark.parametrize("name", _ODD_NAMES, ids=lambda name: repr(name)[:24])
def test_no_odd_name_turns_a_protected_read_into_an_allow(
    tree: Tree, shape: str, name: str
) -> None:
    """Property: whatever the name, the read beside it is judged and denied."""
    decision, text = _result(tree, shape.format(name=name))
    assert decision is Decision.DENY, text
