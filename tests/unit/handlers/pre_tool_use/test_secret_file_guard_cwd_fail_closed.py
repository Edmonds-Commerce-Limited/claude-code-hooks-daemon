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
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project
from tests.load_scaling import scaled_seconds

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_PROTECTED = "id_" + "rsa"
_ENV_FILE = ".e" + "nv"
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
    (primary / _ENV_FILE).write_bytes(_DUMMY)
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
        # The decision is not asserted: a glob that matches nothing is a computed move,
        # and this fixture's directory links lead out of the project (review 614c N1).
        with patch.object(sfm.os, "scandir", wraps=os.scandir) as spy:
            _decision(tree, f"cd {target} && cat clean/plain.txt")
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
        # Not the deadline or the advisory. The tree is past the link scan's cap, so
        # the wide cd's computed move is a placement that could not finish (review D2).
        assert "could NOT fully judge" not in text
        assert "stopped before" not in text

    def test_the_walk_keeps_no_match_of_a_wide_cd(self, wide: Tree) -> None:
        cwds = sfm.effective_cwds("cd t/*/*/*; ls", str(wide.worktree))
        assert len(cwds) <= 2 * sfm.LINK_DIRECTORY_CAP
        assert not any("/t/" in directory for directory in cwds)

    def test_the_search_walk_keeps_no_match_of_a_wide_cd(
        self, wide: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.utils import recursive_search

        # A cap the whole tree fits under, so the computed move's scan completes.
        monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", 20_000)
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
        assert not sfm.expand_directory_glob(str(tree.worktree), "t/*").complete
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
    """Review 614c X1b, revised by independent review D2.

    The wide cd is judged as a computed move, and this tree is past the link
    scan's cap: what the scan never reached may hold a link, so a word read
    after it is denied. The move to git's top level is placed at the ancestors
    but still judged as computed: the command can move the top level in ways
    the guard cannot read (Plan 00623 review F3), so past the cap it denies too
    until the link index is built.
    """

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

    @staticmethod
    def _decide(plain: Path, command: str) -> Decision:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(plain),
        }
        handler = SecretFileGuardHandler()
        if not handler.matches(hook_input):
            return Decision.ALLOW
        return handler.handle(hook_input).decision

    @pytest.mark.parametrize("command", ["cd t/*/*/*; ls", "cd t && cd */*/*; ls"])
    def test_a_wide_cd_past_the_scan_cap_denied(self, plain: Path, command: str) -> None:
        assert self._decide(plain, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$(git rev-parse --show-toplevel)" && ls t',
            "cd $(git rev-parse --show-toplevel) && make test",
            "cd `git rev-parse --show-toplevel` && ls",
            'cd t/d00 && cd "$(git rev-parse --show-toplevel)" && grep -r x t/d01',
        ],
    )
    def test_a_move_to_the_top_level_past_the_scan_cap_denies(
        self, plain: Path, command: str
    ) -> None:
        with patch.object(link_index, "link_scan_for", return_value=None):
            assert self._decide(plain, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$(git rev-parse --show-toplevel)" && ls t',
            "cd $(git rev-parse --show-toplevel) && make test",
            "cd `git rev-parse --show-toplevel` && ls",
            'cd t/d00 && cd "$(git rev-parse --show-toplevel)" && grep -r x t/d01',
        ],
    )
    def test_a_move_to_the_top_level_is_allowed_once_the_index_is_built(
        self, plain: Path, command: str
    ) -> None:
        link_index.reset_link_indexes()
        link_index.prewarm(str(plain))
        link_index.wait_for_link_index(60.0)
        # Listed long ago, so this freshly grown tree is not re-listed as racy (past the re-list cap).
        link_index._indexes[str(plain)].age_for_tests(seconds=3600)
        try:
            assert self._decide(plain, command) is Decision.ALLOW
        finally:
            link_index.reset_link_indexes()

    def test_a_relocated_top_level_is_a_computed_move(self, plain: Path) -> None:
        command = 'GIT_WORK_TREE=t; cd "$(git rev-parse --show-toplevel)" && ls'
        assert self._decide(plain, command) is Decision.DENY


class TestComputedDirectoryChangeIntoALink:
    """Review 614c N1: a computed cd may land IN a directory link, not only beside one."""

    @pytest.mark.parametrize("read", ["cat .e*", "cat i*", "cat *"])
    @pytest.mark.parametrize(
        "move",
        [
            "cd $(echo plink)",
            "cd `echo plink`",
            "cd ${X:-plink}",
            "X=plink; cd ${X%%z}",
            "X=pl Y=ink; cd $X$Y",
            "read X <<< plink; cd $X",
            "cd $'plink'",
            "cd $'\\x70link'",
            "HOME=plink; cd",
            "HOME=plink; cd ~",
            "OLDPWD=plink; cd -",
            "cd ~+/plink",
        ],
    )
    def test_a_slashless_glob_after_a_computed_cd_into_a_link_denied(
        self, tree: Tree, move: str, read: str
    ) -> None:
        assert _decision(tree, f"{move} && {read}") is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "for d in plink; do cd $d; cat .e*; done",
            "cd $(echo dlink) && cat *",
            "cd $(echo deep/idlink) && cat i*",
            "cd $(echo plink) && grep -r DUMMY .",
        ],
    )
    def test_other_computed_moves_into_a_link_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize("command", ["cd plink && cat .e*", "X=plink; cd ${X} && cat .e*"])
    def test_the_literal_forms_stay_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    def test_the_walk_adds_the_directory_links(self, tree: Tree) -> None:
        cwds = sfm.effective_cwds("cd $(echo x) && ls", str(tree.worktree))
        assert str(tree.worktree / "plink") in cwds
        assert str(tree.worktree / "deep" / "idlink") in cwds
        # A link to a file is no place a cd can land.
        assert str(tree.worktree / "inner" / "ilink") not in cwds


#: Brace expansions past the enumeration cap: the full scan gives up on them.
_OVER_THE_CAP = ["echo {a..z}{a..z}{a..z}", "echo {1..300000}"]


class TestAScanThatGivesUpBesideASearchOrGlob:
    """Review 614c P2: a cap or deadline hit never lets a search or a glob read through.

    The literal fallback judges names only. A recursive search or a glob in the
    same command reads what only the full scan could judge, so it is denied.
    """

    _GAVE_UP = "stopped before"

    @pytest.mark.parametrize("prefix", _OVER_THE_CAP)
    @pytest.mark.parametrize("read", ["grep -r DUMMY own", "rg DUMMY own", "grep -R DUMMY ."])
    def test_a_cap_hit_denies_a_search(self, tree: Tree, prefix: str, read: str) -> None:
        decision, text = _result(tree, f"{prefix}; {read}")
        assert decision is Decision.DENY, text
        assert self._GAVE_UP in text

    @pytest.mark.parametrize("prefix", _OVER_THE_CAP)
    @pytest.mark.parametrize("read", ["cat o*/*", "head -n1 own/*"])
    def test_a_cap_hit_denies_a_glob(self, tree: Tree, prefix: str, read: str) -> None:
        # The literal fallback matches these globs against the index itself, so
        # the deny names the protected pattern rather than the gave-up cause.
        decision, text = _result(tree, f"{prefix}; {read}")
        assert decision is Decision.DENY, text

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


#: A word the brace reader cannot resolve: the full scan gives up on it as unparseable.
_UNPARSEABLE = 'echo .p-{"$(case a in a) echo;; esac)",q}'


class TestEveryGaveUpRouteBesideASearch:
    """Review 614c P2, the other routes: a parse failure or an internal error is a gave-up scan too."""

    @pytest.mark.parametrize("read", ["grep -r DUMMY own", "rg DUMMY own"])
    def test_an_unparseable_word_beside_a_search_denies(self, tree: Tree, read: str) -> None:
        decision, text = _result(tree, f"{_UNPARSEABLE}; {read}")
        assert decision is Decision.DENY, text

    def test_an_unparseable_word_alone_stays_an_advisory(self, tree: Tree) -> None:
        decision, text = _result(tree, f"{_UNPARSEABLE}; ls clean")
        assert decision is Decision.ALLOW, text

    def test_an_internal_error_beside_a_search_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic evaluation failure")

        monkeypatch.setattr(SecretFileGuardHandler, "_evaluate", boom)
        decision, text = _result(tree, "grep -r DUMMY own")
        assert decision is Decision.DENY, text

    def test_an_internal_error_with_no_search_stays_an_advisory(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic evaluation failure")

        monkeypatch.setattr(SecretFileGuardHandler, "_evaluate", boom)
        decision, _text = _result(tree, "cat clean/plain.txt")
        assert decision is Decision.ALLOW

    def test_a_deadline_hit_on_the_grep_tool_denies(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def late(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("synthetic deadline")

        monkeypatch.setattr(SecretFileGuardHandler, "_evaluate", late)
        hook_input: dict[str, Any] = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "DUMMY", "path": str(tree.worktree / "own")},
            "cwd": str(tree.worktree),
        }
        handler = SecretFileGuardHandler()
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision is Decision.DENY


class TestManyFailedDirectoryChangesBesideASearch:
    """A failed cd keeps its base beside its target, so the search's directories can double per cd."""

    _CDS = 18

    def test_the_search_is_judged_quickly_and_denied(self, tree: Tree) -> None:
        moves = " && ".join(f"cd r{number}" for number in range(self._CDS))
        start = time.monotonic()
        decision = _decision(tree, f"{moves} && grep -r DUMMY own")
        assert time.monotonic() - start < scaled_seconds(3.0)
        assert decision is Decision.DENY

    def test_a_search_past_the_cap_still_sees_a_link_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past the cap every indexed file is read, and so is every link a move could reach.

        The project holds no protected file, so only the links out can make the deny.
        """
        base = tmp_path.resolve()
        outside = base / "outside"
        outside.mkdir()
        (outside / _PROTECTED).write_bytes(_DUMMY)
        project = base / "project"
        project.mkdir()
        _git("init", "-q", "-b", "main", cwd=project)
        for number in range(300):
            holder = project / f"h{number:03d}"
            holder.mkdir()
            (holder / "out").symlink_to(os.path.relpath(outside, holder))
        monkeypatch.chdir("/")
        protected_file_index.reset_index_cache()
        root = str(project)
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "cd $(echo x) && grep -r DUMMY ."},
            "cwd": root,
        }
        with (
            patch.object(guard_module, "resolve_project_root", return_value=root),
            patch.object(sfm, "resolve_project_root", return_value=root),
            patch.object(path_exclusion, "resolve_project_root", return_value=root),
        ):
            index_project(project, SecretFileGuardHandler()._patterns())
            handler = SecretFileGuardHandler()
            assert handler.matches(hook_input)
            assert handler.handle(hook_input).decision is Decision.DENY
        protected_file_index.reset_index_cache()

    def test_many_moves_beside_no_reader_stay_allowed(self, tree: Tree) -> None:
        moves = " && ".join(f"cd r{number}" for number in range(self._CDS))
        assert _decision(tree, f"{moves} && echo done") is Decision.ALLOW


class TestComputedMoveIntoALinkPastTheDirectoryCap:
    """Review 614c N1 in a tree with more link-holding directories than LINK_DIRECTORY_CAP."""

    def test_a_computed_cd_into_a_link_still_denied(self, tree: Tree) -> None:
        for number in range(sfm.LINK_DIRECTORY_CAP + 4):
            holder = tree.worktree / f"h{number:02d}"
            holder.mkdir()
            (holder / "here").symlink_to("../clean")
        assert _decision(tree, "cd $(echo plink) && cat .e*") is Decision.DENY


class TestOtherWaysBashChangesDirectory:
    """Review 614c N3: CDPATH, extended globs, eval and a function placing a cd."""

    @pytest.mark.parametrize(
        "command",
        [
            "CDPATH=deep cd idlink && cat i*",
            "export CDPATH=deep; cd idlink && cat *",
            "shopt -s extglob\ncd @(plink) && cat .e*",
            "shopt -s extglob\ncd +(plink) && cat .e*",
            "cd deep && cd @(idlink) && cat *",
            "eval cd plink && cat .e*",
            'f() { cd "$1"; }; f plink && cat .e*',
            "CDPATH=deep cd idlink && grep -r DUMMY .",
            "shopt -s extglob\ncd @(plink) && grep -r DUMMY .",
        ],
    )
    def test_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize("command", ["CDPATH=deep cd clean && ls", "cd @(clean) && ls"])
    def test_a_harmless_move_stays_allowed(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.ALLOW


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

    @pytest.mark.parametrize(
        "command",
        [
            "/usr/bin/env -C inner cat ilink",
            "/usr/bin/env --chdir=inner cat ilink",
            "/usr/bin/sudo -D inner cat ilink",
            "/bin/tar -C inner -chf - ilink",
            "/usr/bin/git -C inner diff --no-index ilink /dev/null",
            "nice /usr/bin/env -C inner cat ilink",
            "/usr/bin/env -C inner grep -r DUMMY .",
        ],
    )
    def test_a_path_qualified_chdir_command_denied(self, tree: Tree, command: str) -> None:
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


class _SortedScandir:
    """``os.scandir`` with its entries in name order, so a test fixes which entry comes first."""

    def __init__(self, path: Any) -> None:
        with _REAL_SCANDIR(path) as entries:
            self._entries = sorted(entries, key=lambda entry: entry.name)

    def __enter__(self) -> list[os.DirEntry[str]]:
        return self._entries

    def __exit__(self, *_exc: object) -> None:
        return None

    def __iter__(self) -> Iterator[os.DirEntry[str]]:
        return iter(self._entries)


_REAL_SCANDIR = os.scandir


@pytest.fixture()
def sorted_scandir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sfm.os, "scandir", _SortedScandir)


class TestALinkLoopDoesNotEndTheComputedMoveScan:
    """Independent review D1: one entry the scan cannot stat never ends the scan open.

    ``DirEntry.is_dir`` follows a link and raises ELOOP on a loop. The raise ended
    the listing of that directory, so every sibling after the loop went unqueued
    and links below them were never judged from a computed cd.
    """

    @pytest.fixture()
    def looped(self, tree: Tree, sorted_scandir: None) -> Tree:
        # Named to sort first, so the loop is met before every sibling.
        (tree.worktree / "aaloop1").symlink_to("aaloop2")
        (tree.worktree / "aaloop2").symlink_to("aaloop1")
        (tree.worktree / "zlate").mkdir()
        (tree.worktree / "zlate" / "late").symlink_to(
            os.path.relpath(tree.primary / _PROTECTED, tree.worktree / "zlate")
        )
        (tree.worktree / "zlate" / "latedir").symlink_to(
            os.path.relpath(tree.primary / "sub", tree.worktree / "zlate")
        )
        sfm.reset_link_scans()
        return tree

    def test_the_scan_still_finds_every_sibling_of_the_loop(self, looped: Tree) -> None:
        scan = sfm.scan_project_links(str(looped.worktree))
        assert scan.complete
        assert str(looped.worktree / "zlate") in scan.value.directories
        assert str(looped.worktree / "zlate" / "latedir") in scan.value.directories

    @pytest.mark.parametrize(
        "command",
        [
            "cd $(printf zlate); cat late",
            "cd $(printf zlate); grep -r DUMMY latedir",
            "cd $(printf zlate) && head -n1 late",
        ],
    )
    def test_a_read_after_a_computed_cd_is_denied(self, looped: Tree, command: str) -> None:
        assert _decision(looped, command) is Decision.DENY

    def test_a_plain_read_after_a_computed_cd_stays_allowed(self, looped: Tree) -> None:
        assert _decision(looped, "cd $(printf clean); cat plain.txt") is Decision.ALLOW

    def test_a_glob_cd_beside_a_loop_still_matches(self, looped: Tree) -> None:
        assert sfm.expand_directory_glob(str(looped.worktree), "inn*").required() == [
            str(looped.worktree / "inner")
        ]

    def test_an_unstatable_link_marks_the_scan_incomplete(
        self, looped: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any error other than a loop leaves the link's kind unknown: the scan is incomplete."""
        real_is_dir = os.DirEntry.is_dir

        class _Refusing:
            def __init__(self, path: Any) -> None:
                self._inner = _SortedScandir(path)

            def __enter__(self) -> list[Any]:
                return [_RefusedEntry(entry) for entry in self._inner.__enter__()]

            def __exit__(self, *_exc: object) -> None:
                return None

        class _RefusedEntry:
            def __init__(self, entry: os.DirEntry[str]) -> None:
                self._entry = entry
                self.name = entry.name
                self.path = entry.path

            def is_symlink(self) -> bool:
                return self._entry.is_symlink()

            def is_dir(self, *, follow_symlinks: bool = True) -> bool:
                if follow_symlinks and self._entry.name == "latedir":
                    raise PermissionError(13, "synthetic refusal")
                return real_is_dir(self._entry, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(sfm.os, "scandir", _Refusing)
        sfm.reset_link_scans()
        assert not sfm.scan_project_links(str(looped.worktree)).complete


class TestALinkScanPastItsCapFailsClosed:
    """Independent review D2: a scan that stops at its cap denies; it never logs and allows."""

    @pytest.fixture()
    def wide(self, tree: Tree, sorted_scandir: None, monkeypatch: pytest.MonkeyPatch) -> Tree:
        monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", 8)
        top = tree.worktree / "w"
        top.mkdir()
        for number in range(12):
            (top / f"w{number:02d}").mkdir()
        last = top / "w11"
        (last / "wl").symlink_to(os.path.relpath(tree.primary / _PROTECTED, last))
        (last / "wdl").symlink_to(os.path.relpath(tree.primary / "sub", last))
        sfm.reset_link_scans()
        return tree

    def test_the_scan_reports_itself_incomplete(self, wide: Tree) -> None:
        assert not sfm.scan_project_links(str(wide.worktree)).complete

    @pytest.mark.parametrize(
        "command",
        [
            "cd $(printf w/w11); cat wl",
            "cd $(printf w/w11); grep -r DUMMY wdl",
            "cd $(printf w/w11); cat wdl/*",
            "cd w/w1? && cat wl",
        ],
    )
    def test_a_read_after_a_computed_cd_is_denied(self, wide: Tree, command: str) -> None:
        decision, text = _result(wide, command)
        assert decision is Decision.DENY, text

    def test_too_many_directory_links_mark_the_scan_incomplete(
        self, tree: Tree, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sfm, "LINK_SCAN_DIRECTORY_CAP", 64)
        for number in range(70):
            (tree.worktree / f"dl{number:02d}").symlink_to("clean")
        sfm.reset_link_scans()
        assert not sfm.scan_project_links(str(tree.worktree)).complete

    def test_a_complete_scan_keeps_the_ordinary_computed_cd_allowed(self, tree: Tree) -> None:
        sfm.reset_link_scans()
        assert sfm.scan_project_links(str(tree.worktree)).complete
        assert _decision(tree, 'cd "$(git rev-parse --show-toplevel)" && ls') is Decision.ALLOW


class TestChdirOptionSpellings:
    """Independent review D3: a clustered short option or an abbreviated long one still moves."""

    @pytest.mark.parametrize(
        "command",
        [
            "env -iC inner cat ilink",
            "env -iCinner cat ilink",
            "env -0C inner cat ilink",
            "env -vC inner cat ilink",
            "env -iC plink cat .e*",
            "env --chd=inner cat ilink",
            "env --ch inner cat ilink",
            "env --c=inner cat ilink",
            "sudo -nD inner cat ilink",
            "sudo -bD inner cat ilink",
            "sudo -nDinner cat ilink",
            "sudo -nD plink cat .e*",
            "sudo --chd=inner cat ilink",
            "/usr/bin/env -iC inner cat ilink",
            "nohup env -iC inner cat ilink",
        ],
    )
    def test_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command", ["env -iC plink grep -r DUMMY .", "sudo -nD plink grep -r DUMMY ."]
    )
    def test_a_search_from_a_clustered_move_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize("command", ["env -iC clean cat plain.txt", "env --chd=clean ls"])
    def test_a_harmless_move_stays_allowed(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.ALLOW


class TestExecBeforeAChdirCommand:
    """Independent review D4: ``exec`` runs the next word as the command, like ``command``."""

    @pytest.mark.parametrize(
        "command",
        [
            "exec env -C inner cat ilink",
            "exec env -C plink cat .e*",
            "exec sudo -D inner cat ilink",
            "exec -a name env -C inner cat ilink",
            "exec -c env -C inner cat ilink",
            "exec -cl env -C inner cat ilink",
        ],
    )
    def test_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command", ["exec env -C plink grep -r DUMMY .", "exec -a x env -C plink grep -r DUMMY ."]
    )
    def test_a_search_behind_exec_denied(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY


class TestALinkMadeBetweenTwoCallsIsSeen:
    """Independent review D5: the link scan is never reused across tool calls."""

    def test_the_next_call_sees_a_new_link(self, tree: Tree) -> None:
        command = "cd $(printf clean); cat late"
        assert _decision(tree, command) is Decision.ALLOW
        (tree.worktree / "clean" / "late").symlink_to(
            os.path.relpath(tree.primary / _PROTECTED, tree.worktree / "clean")
        )
        assert _decision(tree, command) is Decision.DENY


class TestGrepToolWithNoPathFromALinkedCwd:
    """Independent review D6: a Grep with no ``path`` searches the hook cwd, which may be a link out."""

    @staticmethod
    def _grep(cwd: Path) -> Decision:
        hook_input: dict[str, Any] = {
            "tool_name": "Grep",
            "tool_input": {"pattern": "DUMMY"},
            "cwd": str(cwd),
        }
        handler = SecretFileGuardHandler()
        if not handler.matches(hook_input):
            return Decision.ALLOW
        return handler.handle(hook_input).decision

    @pytest.mark.parametrize("cwd", ["plink", "dlink", "deep/idlink", "plink/sub"])
    def test_denied(self, tree: Tree, cwd: str) -> None:
        assert self._grep(tree.worktree / cwd) is Decision.DENY

    @pytest.mark.parametrize("cwd", ["clean", ".", "own"])
    def test_a_cwd_through_no_link_is_judged_as_before(self, tree: Tree, cwd: str) -> None:
        """Only a cwd that passes through a link is judged: a pathless Grep from the
        project root is not denied for the protected files under it (as on main)."""
        assert self._grep(tree.worktree / cwd) is Decision.ALLOW


class TestADeeperRelativeWordAfterAComputedMove:
    """Round 6 class sweep: a word of several components read after a computed cd.

    The scan finds each directory that holds a link, but a computed cd may land
    ABOVE it, and ``a/late`` read from there passes through the link. Allowed on
    main and on the round-start tip.
    """

    @pytest.fixture()
    def nested(self, tree: Tree) -> Tree:
        holder = tree.worktree / "q" / "sub" / "a"
        holder.mkdir(parents=True)
        (holder / "late").symlink_to(os.path.relpath(tree.primary / _PROTECTED, holder))
        (holder / "dl").symlink_to(os.path.relpath(tree.primary / "sub", holder))
        (holder / "plain.txt").write_bytes(b"hello\n")
        return tree

    @pytest.mark.parametrize(
        "command",
        [
            "cd $(printf q/sub); cat a/late",
            "cd $(printf q); cd sub; cat a/late",
            "cd $(printf q); cat sub/a/late",
            f"cd $(printf q/sub); cat a/dl/{_PROTECTED}",
            "cd $(printf q); grep -r DUMMY sub/a/dl",
            "cd $(printf q/sub) && grep -r DUMMY a",
        ],
    )
    def test_denied(self, nested: Tree, command: str) -> None:
        assert _decision(nested, command) is Decision.DENY

    def test_a_plain_deeper_word_stays_allowed(self, nested: Tree) -> None:
        assert _decision(nested, "cd $(printf q/sub); cat a/plain.txt") is Decision.ALLOW


class TestTheTopLevelMoveAddsToTheComputedJudgement:
    """Round 6 advisor review: placing ``cd "$(git rev-parse --show-toplevel)"`` must only add.

    Under the scan's cap it is judged as the computed move it is (round-start
    behaviour), the ancestors besides; a shadowed ``git`` makes it plain computed.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'cd "$(git rev-parse --show-toplevel)" && cat .e*',
            'git() { echo plink; }; cd "$(git rev-parse --show-toplevel)" && cat i*',
            'alias git="echo plink"; cd "$(git rev-parse --show-toplevel)" && cat i*',
            'PATH=/nowhere:$PATH; cd "$(git rev-parse --show-toplevel)" && cat i*',
            'git config core.worktree plink; cd "$(git rev-parse --show-toplevel)" && cat i*',
        ],
    )
    def test_denied_under_the_cap(self, tree: Tree, command: str) -> None:
        assert _decision(tree, command) is Decision.DENY
