"""Tests for narrowing the git listing to paths a protected glob can select (N355 part 3).

The index build used to list every ignored file git knows (554,332 paths on this
repository) and filter in Python. Handing git the protected globs as ``:(glob)``
pathspecs lists only the candidates. The narrowing is sound only if it is a
SUPERSET of what the Python matcher selects, so these tests compare the two
against real git on a fixture tree.

Protected names are assembled at run time: spelling one in a source file would
make the secret guard deny authoring this very file.
"""

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import git_file_states
from claude_code_hooks_daemon.utils.git_file_states import scan_git_file_states
from claude_code_hooks_daemon.utils.protected_pathspecs import (
    PATHSPEC_MAGIC,
    git_pathspecs,
)
from claude_code_hooks_daemon.utils.secret_file_matching import (
    DEFAULT_PROTECTED_PATTERNS,
    protected_among,
)
from claude_code_hooks_daemon.utils.vendor_paths import VENDOR_DIRS_TOKEN

EXT = "p" + "em"
ENV = "." + "env"
SSH_KEY = "id_" + "rsa"
HIDDEN = "sec" + "ret"
BASENAME_GLOB = "*." + EXT
DIRECTORY_GLOB = "certs/*." + EXT
NESTED_GLOB = "**/vault/*/" + SSH_KEY
DEFAULT_BASENAME_GLOB = DEFAULT_PROTECTED_PATTERNS[0]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _git_lines(repo: Path, *args: str) -> list[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    ).stdout.splitlines()


def _touch(root: Path, relpath: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")


class TestPathspecForms:
    def test_a_basename_glob_matches_at_any_depth(self) -> None:
        assert git_pathspecs((BASENAME_GLOB,), Path("/nowhere/proj")) == (
            f"{PATHSPEC_MAGIC}**/{BASENAME_GLOB}",
        )

    def test_a_pattern_with_a_directory_part_keeps_it(self) -> None:
        assert git_pathspecs((DIRECTORY_GLOB,), Path("/nowhere/proj")) == (
            f"{PATHSPEC_MAGIC}**/{DIRECTORY_GLOB}",
        )

    def test_a_leading_recursive_component_is_not_doubled(self) -> None:
        assert git_pathspecs((NESTED_GLOB,), Path("/nowhere/proj")) == (
            f"{PATHSPEC_MAGIC}{NESTED_GLOB}",
        )

    def test_an_anchored_pattern_is_relative_to_the_project(self) -> None:
        specs = git_pathspecs(("/keys/*",), Path("/nowhere/proj"))
        assert specs == (f"{PATHSPEC_MAGIC}keys/*",)

    def test_an_anchored_pattern_under_the_project_root_also_names_its_remainder(self) -> None:
        specs = git_pathspecs(("/nowhere/proj/keys/*",), Path("/nowhere/proj"))
        assert specs is not None
        assert f"{PATHSPEC_MAGIC}keys/*" in specs
        assert f"{PATHSPEC_MAGIC}nowhere/proj/keys/*" in specs

    def test_every_pattern_contributes_and_duplicates_collapse(self) -> None:
        specs = git_pathspecs((BASENAME_GLOB, ENV, BASENAME_GLOB), Path("/nowhere/proj"))
        assert specs == (f"{PATHSPEC_MAGIC}**/{BASENAME_GLOB}", f"{PATHSPEC_MAGIC}**/{ENV}")

    def test_empty_patterns_are_skipped(self) -> None:
        assert git_pathspecs(("", ENV), Path("/nowhere/proj")) == (f"{PATHSPEC_MAGIC}**/{ENV}",)

    def test_no_patterns_selects_nothing(self) -> None:
        assert git_pathspecs((), Path("/nowhere/proj")) == ()


class TestFallsBackToTheFullListing:
    """``None`` means no sound narrowing exists: the caller lists everything."""

    @pytest.mark.parametrize(
        "pattern",
        [
            "id_[" + "r]sa",
            "a\\b",
            ":(top)" + ENV,
            VENDOR_DIRS_TOKEN,
            "**",
            "a**b",
            "a/**b/c",
            "a//b",
            "/",
        ],
    )
    def test_a_pattern_git_would_read_differently(self, pattern: str) -> None:
        assert git_pathspecs((pattern,), Path("/nowhere/proj")) is None

    def test_one_unsound_pattern_spoils_the_whole_set(self) -> None:
        assert git_pathspecs((BASENAME_GLOB, "a**b"), Path("/nowhere/proj")) is None

    def test_a_multi_segment_pattern_that_an_ancestor_directory_of_the_root_can_start(
        self,
    ) -> None:
        """The matcher also tries the ABSOLUTE path, so ``certs/*`` can match through the root."""
        assert git_pathspecs((DIRECTORY_GLOB,), Path("/home/certs/proj")) is None

    def test_a_wildcard_first_segment_can_start_at_any_ancestor(self) -> None:
        assert git_pathspecs(("*/" + SSH_KEY,), Path("/nowhere/proj")) is None

    def test_the_realpath_of_the_root_is_an_ancestor_too(self, tmp_path: Path) -> None:
        real = tmp_path / "certs" / "proj"
        real.mkdir(parents=True)
        link = tmp_path / "link"
        link.symlink_to(real)
        assert git_pathspecs((DIRECTORY_GLOB,), link) is None


def _build_tree(root: Path) -> None:
    """A repository whose files exercise every pattern shape, tracked and ignored."""
    root.mkdir()
    _git(root, "init")
    (root / ".gitignore").write_text("ignored/\n*.log\nlocal_" + EXT + "s/\n")
    for relpath in (
        "src/app.py",
        f"top.{EXT}",
        f"deep/er/still/leaf.{EXT}",
        f"certs/site.{EXT}",
        f"certs/nested/site.{EXT}",
        f"other/certs/site.{EXT}",
        ENV,
        f"{ENV}.local",
        f"app/{ENV}.production",
        f"app/{ENV}rc",
        f".hidden/{SSH_KEY}",
        f"x/vault/one/{SSH_KEY}",
        f"x/vault/one/two/{SSH_KEY}",
        f"vault/zero/{SSH_KEY}",
        f"keys/{SSH_KEY}",
        f"app/config.{HIDDEN}.json",
        f"app/.{HIDDEN}",
        "notes.txt",
    ):
        _touch(root, relpath)
    _git(root, "add", "-A")
    for relpath in (
        f"ignored/{SSH_KEY}",
        f"ignored/deep/x.{EXT}",
        f"ignored/certs/site.{EXT}",
        f"ignored/{ENV}",
        f"ignored/vault/a/{SSH_KEY}",
        f"local_{EXT}s/inner.{EXT}",
        f"sub/{ENV}.d.log",
        f"sub/site.{EXT}.log",
    ):
        _touch(root, relpath)
    for index in range(40):
        _touch(root, f"ignored/bulk/dir{index % 4}/file{index}.txt")


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    _build_tree(root)
    return root


def _patterns(root: Path) -> tuple[str, ...]:
    return (
        *DEFAULT_PROTECTED_PATTERNS,
        BASENAME_GLOB,
        ENV,
        ENV + ".*",
        DIRECTORY_GLOB,
        NESTED_GLOB,
        "/keys/*",
        f"{root.as_posix()}/app/*",
        "app/" + ENV + "*",
    )


class TestTheNarrowListingIsASuperset:
    """A protected file git omits is a silent gap, so the narrowing may never be a subset."""

    def test_every_file_the_full_scan_protects_is_in_the_narrow_scan(self, tree: Path) -> None:
        patterns = _patterns(tree)
        specs = git_pathspecs(patterns, tree)
        assert specs is not None
        full = scan_git_file_states(tree)
        narrow = scan_git_file_states(tree, pathspecs=specs)
        assert full is not None
        assert narrow is not None
        wanted = full.protected_relpaths(tree, patterns)
        assert wanted, "the fixture must contain protected files"
        assert set(wanted) <= narrow.all_paths

    def test_the_verdict_on_the_narrow_scan_equals_the_verdict_on_the_full_scan(
        self, tree: Path
    ) -> None:
        patterns = _patterns(tree)
        specs = git_pathspecs(patterns, tree)
        assert specs is not None
        full = scan_git_file_states(tree)
        narrow = scan_git_file_states(tree, pathspecs=specs)
        assert full is not None
        assert narrow is not None
        assert narrow.protected_relpaths(tree, patterns) == full.protected_relpaths(tree, patterns)

    @pytest.mark.parametrize(
        "pattern",
        [
            BASENAME_GLOB,
            ENV,
            ENV + ".*",
            DIRECTORY_GLOB,
            NESTED_GLOB,
            "/keys/*",
            "app/" + ENV + "*",
            DEFAULT_BASENAME_GLOB,
            SSH_KEY,
        ],
    )
    def test_each_pattern_alone_is_a_superset(self, tree: Path, pattern: str) -> None:
        specs = git_pathspecs((pattern,), tree)
        assert specs is not None
        flags = ("ls-files", "--cached", "--others")
        listed = set(_git_lines(tree, *flags, "--", *specs))
        everything = _git_lines(tree, *flags)
        selected = {
            Path(path).relative_to(tree).as_posix()
            for path in protected_among([str(tree / relpath) for relpath in everything], (pattern,))
        }
        assert selected <= listed

    def test_an_ignored_untracked_protected_file_is_found(self, tree: Path) -> None:
        patterns = _patterns(tree)
        specs = git_pathspecs(patterns, tree)
        assert specs is not None
        narrow = scan_git_file_states(tree, pathspecs=specs)
        assert narrow is not None
        assert f"ignored/deep/x.{EXT}" in narrow.ignored_untracked
        assert f"ignored/vault/a/{SSH_KEY}" in narrow.ignored_untracked

    def test_a_huge_ignored_tree_is_not_listed(self, tree: Path) -> None:
        patterns = _patterns(tree)
        specs = git_pathspecs(patterns, tree)
        assert specs is not None
        narrow = scan_git_file_states(tree, pathspecs=specs)
        assert narrow is not None
        assert not any(path.startswith("ignored/bulk/") for path in narrow.ignored_untracked)
        full = scan_git_file_states(tree)
        assert full is not None
        assert any(path.startswith("ignored/bulk/") for path in full.ignored_untracked)

    def test_the_foreign_tree_rule_still_drops_a_virtualenv_and_node_modules(
        self, tree: Path
    ) -> None:
        _touch(tree, "untracked/venv/pyvenv.cfg")
        _touch(tree, f"untracked/venv/lib/site/cacert.{EXT}")
        _touch(tree, f"untracked/web/node_modules/pkg/cert.{EXT}")
        with (tree / ".gitignore").open("a") as handle:
            handle.write("untracked/\n")
        patterns = _patterns(tree)
        specs = git_pathspecs(patterns, tree)
        assert specs is not None
        full = scan_git_file_states(tree)
        narrow = scan_git_file_states(tree, pathspecs=specs)
        assert full is not None
        assert narrow is not None
        assert not any(path.startswith("untracked/") for path in full.ignored_untracked)
        assert not any(path.startswith("untracked/") for path in narrow.ignored_untracked)
        assert narrow.protected_relpaths(tree, patterns) == full.protected_relpaths(tree, patterns)


class TestScanCarriesThePathspecs:
    def _spy(self, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
        calls: list[tuple[str, ...]] = []
        real = git_file_states.run_git

        def spy(cwd: Path, *args: str, timeout: float) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return real(cwd, *args, timeout=timeout)

        monkeypatch.setattr(git_file_states, "run_git", spy)
        return calls

    def test_only_the_untracked_ignored_listing_is_narrowed(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._spy(monkeypatch)
        specs = (f"{PATHSPEC_MAGIC}**/{BASENAME_GLOB}",)
        assert scan_git_file_states(tree, pathspecs=specs) is not None
        narrowed = [args for args in calls if "--" in args]
        assert len(narrowed) == 1
        args = narrowed[0]
        assert "--others" in args
        assert "--ignored" in args
        after = args[args.index("--") + 1 :]
        assert after[: len(specs)] == specs
        assert f"{PATHSPEC_MAGIC}**/pyvenv.cfg" in after
        assert len(calls) == 4

    def test_without_pathspecs_no_listing_is_narrowed(
        self, tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._spy(monkeypatch)
        assert scan_git_file_states(tree) is not None
        assert all("--" not in args for args in calls)


def test_the_module_does_not_depend_on_the_working_directory(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(os.sep)
    assert git_pathspecs((BASENAME_GLOB,), tree) is not None
