"""Tests for the protected-file index (Plan 00483 A2).

The guards used to answer "does this search or glob reach a protected file?" by
walking the filesystem on every call, with caps and deadlines whose verdicts
depended on tree size and host load. The index answers the same question from a
list of the protected files that exist, built once and looked up in memory.

Protected names are assembled at run time: spelling one, or a glob that could
expand to one, in a source file would make the secret guard deny authoring this
very file.
"""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.utils import protected_file_index as pfi
from claude_code_hooks_daemon.utils.protected_file_index import (
    IndexedFile,
    ProtectedFileIndex,
    TreeView,
    build_index,
    index_for,
    remember,
    reset_index_cache,
)

KEY = "id_" + "rsa"
VAULT = "vault_" + "passwords.yml"
VAULT_GLOB = "*" + VAULT[:10] + "*"
PATTERNS = (KEY, VAULT_GLOB)

#: Globs that reach a protected file of the fixture repository.
HITS = (
    "keys/*",
    "keys/" + KEY[:3] + "*",
    "k*/" + KEY,
    "*/" + KEY,
    "ke?s/*",
    "keys/[" + KEY[0] + "]" + KEY[1:],
    "**/" + KEY,
    "ignored/**/*",
    "ignored/*/*",
    ".hidden/*",
    ".h*/*",
    "group_vars/*" + VAULT[:5] + "*",
)

#: Globs that do not, or that name no place at all.
MISSES = ("src/*", "keys/*.py", "*/" + KEY + "x", "key/*", "*/.*", "*", "*/*/*", "**/*", "?/*/?")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _touch(root: Path, relpath: str) -> None:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A repository with a tracked, an ignored and a hidden protected file."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    (root / ".gitignore").write_text(f"ignored/\n{VAULT}\n")
    _touch(root, "src/app.py")
    _touch(root, f"keys/{KEY}")
    _touch(root, f"ignored/deep/{KEY}")
    _touch(root, f"group_vars/{VAULT}")
    _touch(root, f".hidden/{KEY}")
    _git(root, "add", "-A")
    return root


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    reset_index_cache()


@pytest.fixture()
def index(repo: Path) -> ProtectedFileIndex:
    built = build_index(repo, PATTERNS)
    assert built is not None
    return built


def _only_hidden(index: ProtectedFileIndex) -> ProtectedFileIndex:
    return ProtectedFileIndex(
        project_root=index.project_root,
        patterns=index.patterns,
        files=tuple(entry for entry in index.files if entry.relpath.startswith(".hidden")),
    )


class TestBuildIndex:
    def test_lists_every_protected_file_with_its_git_state(self, repo: Path) -> None:
        index = build_index(repo, PATTERNS)

        assert index is not None
        by_path = {entry.relpath: entry for entry in index.files}
        assert set(by_path) == {
            f"keys/{KEY}",
            f"ignored/deep/{KEY}",
            f"group_vars/{VAULT}",
            f".hidden/{KEY}",
        }
        assert by_path[f"keys/{KEY}"].tracked is True
        assert by_path[f"keys/{KEY}"].ignored is False
        assert by_path[f"ignored/deep/{KEY}"].tracked is False
        assert by_path[f"ignored/deep/{KEY}"].ignored is True
        assert by_path[f"group_vars/{VAULT}"].pattern == VAULT_GLOB

    def test_a_directory_that_is_not_a_repository_has_no_index(self, tmp_path: Path) -> None:
        _touch(tmp_path, f"plain/{KEY}")

        assert build_index(tmp_path / "plain", PATTERNS) is None

    def test_no_patterns_means_nothing_is_protected(self, repo: Path) -> None:
        index = build_index(repo, ())

        assert index is not None
        assert index.files == ()


class TestFindUnder:
    def test_a_root_above_a_protected_file_reads_it(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / "keys")) == KEY

    def test_a_root_beside_it_does_not(self, index: ProtectedFileIndex, repo: Path) -> None:
        assert index.find_under(str(repo / "src")) is None

    def test_the_project_root_reads_all_of_them(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo)) is not None

    def test_a_root_outside_the_project_is_not_covered(
        self, index: ProtectedFileIndex, tmp_path: Path
    ) -> None:
        assert index.find_under(str(tmp_path / "elsewhere")) is None

    def test_a_sibling_whose_name_starts_the_same_is_not_under_the_root(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / "key")) is None

    def test_a_tracked_view_reads_only_tracked_files(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / "ignored"), view=TreeView.TRACKED) is None
        assert index.find_under(str(repo / "keys"), view=TreeView.TRACKED) == KEY

    def test_an_unignored_view_skips_an_ignored_file_below_an_unignored_root(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / "group_vars"), view=TreeView.UNIGNORED) is None

    def test_an_unignored_view_reads_what_an_ignored_root_names_outright(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / "ignored"), view=TreeView.UNIGNORED) == KEY

    def test_an_unignored_view_reads_a_hidden_root_named_outright(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        assert index.find_under(str(repo / ".hidden"), view=TreeView.UNIGNORED) == KEY

    def test_a_skip_hook_drops_a_hidden_directory(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        def skip(path: str, is_dir: bool) -> bool:
            return Path(path).name.startswith(".")

        hidden_only = _only_hidden(index)

        assert hidden_only.find_under(str(repo), skip=skip) is None
        assert hidden_only.find_under(str(repo)) == KEY

    def test_an_exempt_file_is_not_a_hit(self, index: ProtectedFileIndex, repo: Path) -> None:
        assert index.find_under(str(repo / "keys"), is_exempt=lambda path: True) is None

    def test_a_file_named_as_the_root_is_found_whatever_the_tool_skips(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        named = str(repo / "ignored" / "deep" / KEY)

        assert index.find_under(named, view=TreeView.UNIGNORED, skip=lambda p, d: True) == KEY


class TestGlobMatches:
    @pytest.mark.parametrize("glob", HITS)
    def test_a_glob_that_matches_an_indexed_file_is_a_hit(
        self, index: ProtectedFileIndex, repo: Path, glob: str
    ) -> None:
        assert index.glob_matches(str(repo / glob)) is not None

    @pytest.mark.parametrize("glob", MISSES)
    def test_a_glob_that_matches_nothing_protected_is_not(
        self, index: ProtectedFileIndex, repo: Path, glob: str
    ) -> None:
        assert index.glob_matches(str(repo / glob)) is None

    @pytest.mark.parametrize("glob", HITS)
    def test_a_relative_glob_is_read_from_each_base(
        self, index: ProtectedFileIndex, repo: Path, glob: str
    ) -> None:
        assert index.glob_matches(glob, (str(repo / "src"), str(repo))) is not None

    @pytest.mark.parametrize("glob", ("*/*", "*/*/*", "**/*", "?/?", "*/keys/*"))
    def test_a_glob_that_starts_wildcard_and_has_another_names_no_place_so_is_not_judged(
        self, index: ProtectedFileIndex, repo: Path, glob: str
    ) -> None:
        assert index.glob_matches(glob, (str(repo), str(repo / "keys"))) is None
        assert index.glob_matches(str(repo / glob)) is None

    @pytest.mark.parametrize("glob", ("*", "?" + KEY[1:]))
    def test_one_trailing_wildcard_names_a_directory_and_is_judged(
        self, index: ProtectedFileIndex, repo: Path, glob: str
    ) -> None:
        assert index.glob_matches(glob, (str(repo / "keys"),)) == KEY
        assert index.glob_matches(glob, (str(repo / "src"),)) is None

    def test_a_star_never_matches_a_hidden_name(
        self, index: ProtectedFileIndex, repo: Path
    ) -> None:
        hidden_only = _only_hidden(index)

        assert hidden_only.glob_matches(str(repo / "*" / KEY)) is None
        assert hidden_only.glob_matches(str(repo / ".*" / KEY)) is not None

    def test_a_glob_outside_the_project_matches_nothing(
        self, index: ProtectedFileIndex, tmp_path: Path
    ) -> None:
        assert index.glob_matches(str(tmp_path / "other" / "*")) is None

    def test_a_relative_glob_with_no_base_matches_nothing(self, index: ProtectedFileIndex) -> None:
        assert index.glob_matches("keys/*") is None

    def test_a_nul_byte_matches_nothing(self, index: ProtectedFileIndex, repo: Path) -> None:
        assert index.glob_matches(str(repo / "keys\0/*")) is None


class TestTheCache:
    def test_a_remembered_index_is_served_without_building(self, repo: Path) -> None:
        index = ProtectedFileIndex(
            project_root=str(repo),
            patterns=PATTERNS,
            files=(IndexedFile(relpath=f"keys/{KEY}", pattern=KEY, tracked=True, ignored=False),),
        )
        remember(index)

        assert index_for(repo, PATTERNS) is index

    def test_a_miss_is_none_and_starts_a_background_build(self, repo: Path) -> None:
        assert index_for(repo, PATTERNS) is None

        pfi.wait_for_builds(timeout=30)

        served = index_for(repo, PATTERNS)
        assert served is not None
        assert f"keys/{KEY}" in {entry.relpath for entry in served.files}

    def test_a_miss_starts_one_build_however_often_it_is_asked(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[Path] = []
        release = threading.Event()
        real = pfi.build_index

        def slow(root: Path, patterns: tuple[str, ...]) -> ProtectedFileIndex | None:
            calls.append(root)
            release.wait(timeout=10)
            return real(root, patterns)

        monkeypatch.setattr(pfi, "build_index", slow)

        assert index_for(repo, PATTERNS) is None
        assert index_for(repo, PATTERNS) is None
        assert index_for(repo, PATTERNS) is None
        release.set()
        pfi.wait_for_builds(timeout=30)

        assert len(calls) == 1

    def test_a_stale_index_is_served_while_a_fresh_one_builds(self, repo: Path) -> None:
        stale = ProtectedFileIndex(
            project_root=str(repo),
            patterns=PATTERNS,
            files=(),
            built_at=time.monotonic() - pfi.REFRESH_AFTER_SECONDS - 1,
        )
        remember(stale)

        assert index_for(repo, PATTERNS) is stale

        pfi.wait_for_builds(timeout=30)
        refreshed = index_for(repo, PATTERNS)
        assert refreshed is not None
        assert refreshed is not stale
        assert refreshed.files

    def test_a_failed_build_is_not_cached_and_is_not_retried_at_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        plain = tmp_path / "plain"
        _touch(tmp_path, f"plain/{KEY}")
        calls: list[Path] = []

        def failing(root: Path, patterns: tuple[str, ...]) -> ProtectedFileIndex | None:
            calls.append(root)
            return None

        monkeypatch.setattr(pfi, "build_index", failing)

        assert index_for(plain, PATTERNS) is None
        pfi.wait_for_builds(timeout=30)
        assert index_for(plain, PATTERNS) is None
        assert index_for(plain, PATTERNS) is None
        pfi.wait_for_builds(timeout=30)

        assert len(calls) == 1
        assert pfi.cached_index(plain, PATTERNS) is None

    def test_different_pattern_sets_are_indexed_separately(self, repo: Path) -> None:
        remember(ProtectedFileIndex(project_root=str(repo), patterns=PATTERNS, files=()))

        assert index_for(repo, PATTERNS) is not None
        assert index_for(repo, ("other",)) is None
        pfi.wait_for_builds(timeout=30)

    def test_the_cache_is_bounded(self, tmp_path: Path) -> None:
        total = pfi.MAX_CACHED_INDEXES + 3
        for number in range(total):
            remember(
                ProtectedFileIndex(
                    project_root=str(tmp_path / f"p{number}"), patterns=PATTERNS, files=()
                )
            )

        held = sum(
            pfi.cached_index(tmp_path / f"p{number}", PATTERNS) is not None
            for number in range(total)
        )

        assert held == pfi.MAX_CACHED_INDEXES
