"""Tests for GitBranchHandler.

Mocking note (Plan 00238 Task 2.1b): the handler makes ONE
``git status --porcelain=v2 --branch`` call per render-cache miss and reads
the branch name out of its ``# branch.head`` line, rather than spending a
second fork on ``git branch --show-current``. The ordered ``side_effect``
lists below therefore run:

    rev-parse --show-toplevel  (first render for a cwd only — memoised after)
    status --porcelain=v2 --branch
    symbolic-ref               (default-branch resolution, cached per repo)
    stash list

``_porcelain()`` builds the status payload; pass the branch name you want the
handler to render.
"""

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.status_line import GitBranchHandler

#: Porcelain v2 prints this instead of a name when HEAD is detached, which the
#: handler maps to "no branch" exactly as ``branch --show-current`` did.
_DETACHED_HEAD = "(detached)"


def _porcelain(branch: str, entries: str = "") -> str:
    """Build ``git status --porcelain=v2 --branch`` stdout for ``branch``.

    ``entries`` appends raw porcelain entry lines (``1 XY ...``, ``? path``,
    ...) for tests that assert on the status icons.

    Text, not bytes: the status call goes through ``run_git``, which runs git in
    text mode so no caller has to remember to decode (Plan 00246).
    """
    head = branch if branch else _DETACHED_HEAD
    return f"# branch.oid abc123\n# branch.head {head}\n# branch.ab +0 -0\n{entries}"


def _status_mock(branch: str, entries: str = "") -> MagicMock:
    """A ``run_git`` result for the status call."""
    mock = MagicMock()
    mock.returncode = 0
    mock.stdout = _porcelain(branch, entries)
    return mock


class TestGitBranchHandler:
    """Tests for GitBranchHandler."""

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        """Create handler instance with auto-fetch disabled.

        These tests mock ``subprocess.run`` with ``side_effect`` lists; a
        background fetch thread consuming from the same shared mock would
        race the main thread and make results nondeterministic.
        """
        handler = GitBranchHandler()
        handler._auto_fetch = False
        return handler

    def test_handler_properties(self, handler: GitBranchHandler) -> None:
        """Test handler has correct properties."""
        assert handler.name == "status-git-branch"
        assert handler.priority == 20
        assert handler.terminal is False
        assert "status" in handler.tags
        assert "git" in handler.tags

    def test_matches_always_returns_true(self, handler: GitBranchHandler) -> None:
        """Handler should always match for status events."""
        assert handler.matches({}) is True
        assert handler.matches({"workspace": {"current_dir": "/tmp"}}) is True

    def test_handle_with_git_branch(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test formatting with valid git branch."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_symbolic_ref = MagicMock()
        mock_result_symbolic_ref.returncode = 0
        mock_result_symbolic_ref.stdout = "refs/remotes/origin/main\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                _status_mock("main"),
                mock_result_symbolic_ref,
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ " in result.context[0]
        assert "main" in result.context[0]

    def test_handle_not_a_git_repo(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test returns empty context when not in git repo."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_no_workspace_data(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when workspace data missing."""
        result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_invalid_path(self, handler: GitBranchHandler) -> None:
        """Test returns empty context when path doesn't exist."""
        hook_input = {"workspace": {"current_dir": "/nonexistent/path"}}

        result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_git_error_silent_fail(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test silent failure on git errors."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        with patch("subprocess.run", side_effect=Exception("Git error")):
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_handle_detached_head_renders_nothing(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """No branch name, no segment.

        Porcelain v2 reports a detached HEAD as ``# branch.head (detached)``,
        which the handler maps to the empty string — the same "no branch"
        result ``git branch --show-current`` produced by returning nothing.
        """
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [mock_result_toplevel, _status_mock("")]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_uses_project_dir_fallback(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Test uses project_dir when current_dir not available."""
        hook_input = {"workspace": {"project_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        mock_result_symbolic_ref = MagicMock()
        mock_result_symbolic_ref.returncode = 0
        mock_result_symbolic_ref.stdout = "refs/remotes/origin/main\n"

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                _status_mock("develop"),
                mock_result_symbolic_ref,
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 1
        assert "| ⎇ " in result.context[0]
        assert "develop" in result.context[0]


class TestGitBranchColorCoding:
    """Tests for branch color-coding based on default branch detection."""

    _GREEN = "\033[32m"
    _ORANGE = "\033[38;5;208m"
    _RESET = "\033[0m"

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        handler = GitBranchHandler()
        handler._auto_fetch = False  # side_effect mocks must not race a fetch thread
        return handler

    def _make_run_side_effects(
        self,
        branch: str,
        symbolic_ref_returncode: int = 0,
        symbolic_ref_stdout: str = "refs/remotes/origin/main\n",
    ) -> list[MagicMock]:
        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_symbolic_ref = MagicMock()
        mock_symbolic_ref.returncode = symbolic_ref_returncode
        mock_symbolic_ref.stdout = symbolic_ref_stdout

        return [mock_toplevel, _status_mock(branch), mock_symbolic_ref]

    def test_default_branch_is_green(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Branch matching origin/HEAD should be colored green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        side_effects = self._make_run_side_effects("main")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]
        assert self._RESET in result.context[0]
        assert self._ORANGE not in result.context[0]

    def test_non_default_branch_is_orange(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Branch not matching origin/HEAD should be colored orange."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        side_effects = self._make_run_side_effects("feature/my-feature")

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._ORANGE in result.context[0]
        assert self._RESET in result.context[0]
        assert self._GREEN not in result.context[0]

    def test_default_branch_from_symbolic_ref(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Correctly extracts default branch name from symbolic ref output."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        # Remote uses 'develop' as default branch
        side_effects = self._make_run_side_effects(
            "develop",
            symbolic_ref_stdout="refs/remotes/origin/develop\n",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = side_effects
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_fallback_to_main_when_no_symbolic_ref(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Falls back to checking 'main'/'master' when no remote HEAD."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128  # no remote HEAD

        mock_show_ref_main = MagicMock()
        mock_show_ref_main.returncode = 0  # 'main' exists locally

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                _status_mock("main"),
                mock_symbolic_ref_fail,
                mock_show_ref_main,
            ]
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_fallback_master_when_no_main(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Falls back to 'master' when 'main' doesn't exist locally."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128

        mock_show_ref_main_fail = MagicMock()
        mock_show_ref_main_fail.returncode = 1  # 'main' doesn't exist

        mock_show_ref_master = MagicMock()
        mock_show_ref_master.returncode = 0  # 'master' exists

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                _status_mock("master"),
                mock_symbolic_ref_fail,
                mock_show_ref_main_fail,
                mock_show_ref_master,
            ]
            result = handler.handle(hook_input)

        assert self._GREEN in result.context[0]

    def test_no_default_branch_found_is_grey(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """When default branch can't be determined, branch is shown in grey."""
        _GREY = "\033[37m"
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock()
        mock_toplevel.returncode = 0

        mock_symbolic_ref_fail = MagicMock()
        mock_symbolic_ref_fail.returncode = 128

        mock_show_ref_main_fail = MagicMock()
        mock_show_ref_main_fail.returncode = 1

        mock_show_ref_master_fail = MagicMock()
        mock_show_ref_master_fail.returncode = 1

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                _status_mock("feature/xyz"),
                mock_symbolic_ref_fail,
                mock_show_ref_main_fail,
                mock_show_ref_master_fail,
            ]
            result = handler.handle(hook_input)

        assert _GREY in result.context[0]
        assert self._GREEN not in result.context[0]
        assert self._ORANGE not in result.context[0]

    def test_handle_git_called_process_error_silent_fail(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Test silent failure on CalledProcessError (e.g. git branch --show-current fails)."""
        import subprocess

        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_result_toplevel = MagicMock()
        mock_result_toplevel.returncode = 0

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_result_toplevel,
                subprocess.CalledProcessError(1, "git"),
            ]
            result = handler.handle(hook_input)

        assert result.decision == "allow"
        assert len(result.context) == 0

    def test_get_default_branch_timeout_returns_none(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """_get_default_branch returns None when subprocess times out."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 5)):
            result = handler._get_default_branch(str(tmp_path))

        assert result is None

    def test_default_branch_detection_cached(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Default branch detection runs only once per repo across multiple handle() calls.

        Call sequence per handle(): [rev-parse on the first call only - the
        repo root is memoised per cwd], git status --porcelain=v2 --branch,
        [symbolic-ref on the first call only - the default branch is memoised
        per repo], git stash list.
        """
        # Isolate default-branch caching from the render TTL cache (Plan 00155
        # T4): disable the render cache so the second handle() re-forks and this
        # test observes the per-repo default-branch memoisation on its own.
        handler._render_ttl_seconds = 0
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        toplevel_stdout = str(tmp_path) + "\n"

        def make_mocks(
            branch_name: str, include_symbolic_ref: bool, include_toplevel: bool = True
        ) -> list[MagicMock]:
            mocks: list[MagicMock] = []
            if include_toplevel:
                mock_toplevel = MagicMock()
                mock_toplevel.returncode = 0
                mock_toplevel.stdout = toplevel_stdout
                mocks.append(mock_toplevel)
            mocks.append(_status_mock(branch_name))
            if include_symbolic_ref:
                mock_symbolic_ref = MagicMock()
                mock_symbolic_ref.returncode = 0
                mock_symbolic_ref.stdout = "refs/remotes/origin/main\n"
                mocks.append(mock_symbolic_ref)
            mock_stash = MagicMock()
            mock_stash.returncode = 0
            mock_stash.stdout = ""
            mocks.append(mock_stash)
            return mocks

        # First call: 4 invocations (toplevel + status + symbolic-ref + stash).
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks("main", include_symbolic_ref=True)
            handler.handle(hook_input)
            first_call_count = mock_run.call_count
        assert first_call_count == 4

        # Second call, same cwd: 2 invocations (status + stash). Both the repo
        # root and the default branch are memoised, and the branch name now
        # comes out of the status output rather than its own fork.
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks(
                "feature/x", include_symbolic_ref=False, include_toplevel=False
            )
            handler.handle(hook_input)
            second_call_count = mock_run.call_count
        assert second_call_count == 2

    def test_default_branch_cached_per_repo(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Each repo gets its own default-branch detection, keyed by repo toplevel.

        Repo A's default is 'master'; repo B's default is 'main'. After detecting
        repo A, switching to repo B must re-detect (not reuse A's 'master'), so a
        'main' checkout in repo B is coloured green (default), not orange.
        """
        repo_a = tmp_path / "repo_a"
        repo_b = tmp_path / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()

        def make_mocks(
            *, toplevel: Path, branch: str, symbolic_ref_default: str
        ) -> list[MagicMock]:
            mock_toplevel = MagicMock(returncode=0, stdout=str(toplevel) + "\n")
            mock_symbolic_ref = MagicMock(
                returncode=0,
                stdout=f"refs/remotes/origin/{symbolic_ref_default}\n",
            )
            mock_stash = MagicMock(returncode=0, stdout="")
            return [mock_toplevel, _status_mock(branch), mock_symbolic_ref, mock_stash]

        # Repo A: default master, currently on master -> green
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks(
                toplevel=repo_a, branch="master", symbolic_ref_default="master"
            )
            result_a = handler.handle({"workspace": {"current_dir": str(repo_a)}})
        assert self._GREEN in result_a.context[0]

        # Repo B: default main, currently on main -> must be green (re-detected),
        # NOT orange from reusing repo A's 'master' default.
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = make_mocks(
                toplevel=repo_b, branch="main", symbolic_ref_default="main"
            )
            result_b = handler.handle({"workspace": {"current_dir": str(repo_b)}})
        assert self._GREEN in result_b.context[0]
        assert self._ORANGE not in result_b.context[0]


class TestGitStatusIcons:
    """Tests for magicmonty-style status icons after branch name."""

    _GREEN = "\033[32m"
    _RED = "\033[31m"
    _YELLOW = "\033[33m"
    _CYAN = "\033[36m"
    _GREY = "\033[37m"
    _RESET = "\033[0m"

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        handler = GitBranchHandler()
        handler._auto_fetch = False  # side_effect mocks must not race a fetch thread
        return handler

    def _make_mocks(
        self,
        *,
        branch: str = "main",
        status_stdout: bytes = b"",
        stash_stdout: str = "",
    ) -> list[MagicMock]:
        """Build the standard 4-call mock chain.

        toplevel, git status --porcelain=v2 --branch, symbolic-ref
        (origin/main), git stash list. The status output supplies the branch
        name as well as the icon state, so pass ``status_stdout`` when the test
        cares about icons and ``branch`` when it only cares about the name.

        ``status_stdout`` stays a bytes literal because that is what git really
        emits; the status call goes through ``run_git``, which runs in text mode,
        so the decode that ``run_git`` performs is reproduced here (Plan 00246).
        Every call now goes through ``run_git`` (Plan 00246 sweep), which runs
        git in text mode, so ``stash_stdout`` (and every other mocked
        ``.stdout``) is plain ``str``.
        """
        mock_toplevel = MagicMock(returncode=0)
        mock_status = MagicMock(
            returncode=0, stdout=status_stdout.decode() if status_stdout else _porcelain(branch)
        )
        mock_symbolic_ref = MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
        mock_stash = MagicMock(returncode=0, stdout=stash_stdout)
        return [mock_toplevel, mock_status, mock_symbolic_ref, mock_stash]

    def test_ahead_shows_up_arrow(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`# branch.ab +2 -0` should render ↑2 in green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.oid abc\n"
            b"# branch.head main\n"
            b"# branch.upstream origin/main\n"
            b"# branch.ab +2 -0\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREEN}↑2{self._RESET}" in rendered
        assert "↓" not in rendered

    def test_behind_shows_down_arrow(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`# branch.ab +0 -3` should render ↓3 in red."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +0 -3\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._RED}↓3{self._RESET}" in rendered
        assert "↑" not in rendered

    def test_ahead_and_behind_both_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Diverged branch shows both arrows."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +2 -1\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "↑2" in rendered
        assert "↓1" in rendered

    def test_staged_change_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`1 M. ...` (staged modification) renders ●1 in green."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 M. N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREEN}●1{self._RESET}" in rendered

    def test_unstaged_change_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`1 .M ...` (unstaged modification) renders ✚1 in yellow."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 .M N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._YELLOW}✚1{self._RESET}" in rendered

    def test_file_counted_in_both_staged_and_unstaged(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """`1 MM ...` (staged AND unstaged on same file) counts in both."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"1 MM N... 100644 100644 100644 abc abc src/foo.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "●1" in rendered
        assert "✚1" in rendered

    def test_untracked_file_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`? path` renders …1 in grey."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = b"# branch.head main\n? new_file.py\n"
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._GREY}…1{self._RESET}" in rendered

    def test_conflicts_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`u UU ...` (unmerged) renders ✖1 in red."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"u UU N... 100644 100644 100644 100644 a b c d conflict.py\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._RED}✖1{self._RESET}" in rendered

    def test_stashed_shown(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """`git stash list` with 2 lines renders ⚑2 in cyan."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        stash_stdout = "stash@{0}: WIP on main: abc Fix\n" "stash@{1}: WIP on main: def Other\n"
        mocks = self._make_mocks(stash_stdout=stash_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert f"{self._CYAN}⚑2{self._RESET}" in rendered

    def test_clean_repo_shows_only_branch(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Clean repo with synced upstream and no changes shows only branch."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n" b"# branch.upstream origin/main\n" b"# branch.ab +0 -0\n"
        )
        mocks = self._make_mocks(status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        for icon in ("↑", "↓", "●", "✚", "…", "⚑", "✖"):
            assert icon not in rendered, f"icon {icon!r} should not appear in clean repo"

    def test_no_upstream_omits_ahead_behind(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Branch with no upstream tracking has no `# branch.ab` line, so no arrows."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = b"# branch.head feature/x\n"
        mocks = self._make_mocks(branch="feature/x", status_stdout=status_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert "↑" not in rendered
        assert "↓" not in rendered

    def test_status_silent_fail_keeps_branch(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """If `git status` raises, branch is still shown without icons.

        The branch name normally comes OUT of the status output, so a failed
        status would take the whole segment with it. The handler falls back to
        `git branch --show-current` for exactly this case, which keeps the
        degraded display identical to what it was when the two were always
        separate calls.
        """
        import subprocess

        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        mock_toplevel = MagicMock(returncode=0)
        mock_branch = MagicMock(returncode=0, stdout="main\n")
        mock_symbolic_ref = MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                mock_toplevel,
                subprocess.TimeoutExpired("git", 5),
                mock_branch,  # fallback branch query
                mock_symbolic_ref,
                # stash should not be called since there is no status to render
            ]
            result = handler.handle(hook_input)
        assert "main" in result.context[0]
        for icon in ("↑", "↓", "●", "✚", "…", "⚑", "✖"):
            assert icon not in result.context[0]

    def test_combined_state_renders_in_documented_order(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Combined state: ahead, staged, changed, untracked, stashed."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        status_stdout = (
            b"# branch.head main\n"
            b"# branch.upstream origin/main\n"
            b"# branch.ab +1 -0\n"
            b"1 M. N... 100644 100644 100644 a b src/foo.py\n"
            b"1 .M N... 100644 100644 100644 c d src/bar.py\n"
            b"? new.py\n"
        )
        stash_stdout = "stash@{0}: WIP\n"
        mocks = self._make_mocks(status_stdout=status_stdout, stash_stdout=stash_stdout)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = mocks
            result = handler.handle(hook_input)
        rendered = result.context[0]
        # Order: ahead, behind, staged, changed, conflicts, untracked, stashed
        positions = {
            "↑1": rendered.index("↑1"),
            "●1": rendered.index("●1"),
            "✚1": rendered.index("✚1"),
            "…1": rendered.index("…1"),
            "⚑1": rendered.index("⚑1"),
        }
        assert (
            positions["↑1"] < positions["●1"] < positions["✚1"] < positions["…1"] < positions["⚑1"]
        )


class TestBackgroundFetch:
    """TTL-gated background fetch keeps remote-tracking refs fresh.

    Regression: the ahead/behind icons parse ``git status --porcelain=v2
    --branch``, which compares against the LOCAL remote-tracking ref — only
    as fresh as the last ``git fetch``. Nothing in the daemon ever fetched,
    so ``behind`` stayed 0 forever and the status line claimed "in sync"
    while the remote had newer commits.
    """

    _TOPLEVEL = "/repo/toplevel"
    _CWD = "/repo/toplevel/subdir"

    def test_auto_fetch_enabled_by_default(self) -> None:
        """Fresh handler has auto-fetch on with a 5-minute interval."""
        handler = GitBranchHandler()
        assert handler._auto_fetch is True
        assert handler._fetch_interval_seconds == 300

    def test_first_render_starts_fetch(self) -> None:
        """First render for a repo starts a background fetch thread."""
        handler = GitBranchHandler()
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            started = handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD)
        assert started is True
        mock_start.assert_called_once_with(self._TOPLEVEL, self._CWD)

    def test_within_ttl_does_not_refetch(self) -> None:
        """A second render inside the TTL window must not fetch again."""
        handler = GitBranchHandler()
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is True
            # Simulate the first fetch having completed
            handler._fetch_inflight.discard(self._TOPLEVEL)
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is False
        assert mock_start.call_count == 1

    def test_after_ttl_refetches(self) -> None:
        """Once the TTL has elapsed (and no fetch is in flight), fetch again."""
        handler = GitBranchHandler()
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is True
            handler._fetch_inflight.discard(self._TOPLEVEL)
            # Backdate the last fetch beyond the TTL
            handler._last_fetch_started[self._TOPLEVEL] -= handler._fetch_interval_seconds + 1
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is True
        assert mock_start.call_count == 2

    def test_inflight_guard_blocks_second_fetch(self) -> None:
        """No second fetch starts while one is still running, even past TTL."""
        handler = GitBranchHandler()
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is True
            # Fetch still in flight; TTL expired
            handler._last_fetch_started[self._TOPLEVEL] -= handler._fetch_interval_seconds + 1
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is False
        assert mock_start.call_count == 1

    def test_disabled_never_fetches(self) -> None:
        """auto_fetch=False (config option) disables fetching entirely."""
        handler = GitBranchHandler()
        handler._auto_fetch = False
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            assert handler._maybe_start_background_fetch(self._TOPLEVEL, self._CWD) is False
        mock_start.assert_not_called()

    def test_separate_repos_fetch_independently(self) -> None:
        """TTL/in-flight state is keyed per repo toplevel."""
        handler = GitBranchHandler()
        with patch.object(handler, "_start_fetch_thread") as mock_start:
            assert handler._maybe_start_background_fetch("/repo/a", "/repo/a") is True
            assert handler._maybe_start_background_fetch("/repo/b", "/repo/b") is True
        assert mock_start.call_count == 2

    def test_handle_triggers_fetch_for_repo(self, tmp_path: Path) -> None:
        """handle() wires the fetch trigger with the resolved repo toplevel."""
        handler = GitBranchHandler()
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}

        mock_toplevel = MagicMock(returncode=0, stdout="/repo/toplevel\n")
        mock_symbolic_ref = MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
        mock_stash = MagicMock(returncode=0, stdout="")

        with (
            patch.object(handler, "_maybe_start_background_fetch") as mock_fetch,
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = [
                mock_toplevel,
                _status_mock("main"),
                mock_symbolic_ref,
                mock_stash,
            ]
            handler.handle(hook_input)

        mock_fetch.assert_called_once_with("/repo/toplevel", str(tmp_path))

    def test_run_background_fetch_invokes_git_fetch(self) -> None:
        """The worker runs a quiet, bounded, non-interactive git fetch."""
        from claude_code_hooks_daemon.constants import Timeout

        handler = GitBranchHandler()
        handler._fetch_inflight.add(self._TOPLEVEL)

        with patch("subprocess.run") as mock_run:
            handler._run_background_fetch(self._TOPLEVEL, self._CWD)

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == ["git", "-C", self._CWD, "fetch", "--quiet"]
        assert kwargs["timeout"] == Timeout.GIT_FETCH_BACKGROUND
        assert kwargs["check"] is False
        env = kwargs["env"]
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
        # In-flight marker cleared so the next TTL expiry can fetch again
        assert self._TOPLEVEL not in handler._fetch_inflight

    def test_run_background_fetch_preserves_existing_ssh_command(self) -> None:
        """A user-configured GIT_SSH_COMMAND must not be overridden."""
        import os

        handler = GitBranchHandler()
        custom_ssh = "ssh -i /custom/key"

        with (
            patch.dict(os.environ, {"GIT_SSH_COMMAND": custom_ssh}),
            patch("subprocess.run") as mock_run,
        ):
            handler._run_background_fetch(self._TOPLEVEL, self._CWD)

        env = mock_run.call_args.kwargs["env"]
        assert env["GIT_SSH_COMMAND"] == custom_ssh

    def test_run_background_fetch_timeout_clears_inflight(self) -> None:
        """A hung fetch times out, does not raise, and clears in-flight state."""
        import subprocess

        handler = GitBranchHandler()
        handler._fetch_inflight.add(self._TOPLEVEL)

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            handler._run_background_fetch(self._TOPLEVEL, self._CWD)

        assert self._TOPLEVEL not in handler._fetch_inflight

    def test_run_background_fetch_missing_git_clears_inflight(self) -> None:
        """Missing git binary is tolerated silently (status line must survive)."""
        handler = GitBranchHandler()
        handler._fetch_inflight.add(self._TOPLEVEL)

        with patch("subprocess.run", side_effect=FileNotFoundError("git")):
            handler._run_background_fetch(self._TOPLEVEL, self._CWD)

        assert self._TOPLEVEL not in handler._fetch_inflight

    def test_start_fetch_thread_is_daemon_and_started(self) -> None:
        """The fetch thread is a started daemon thread (never blocks shutdown)."""
        handler = GitBranchHandler()

        with patch(
            "claude_code_hooks_daemon.handlers.status_line.git_branch.threading.Thread"
        ) as mock_thread_cls:
            handler._start_fetch_thread(self._TOPLEVEL, self._CWD)

        _, kwargs = mock_thread_cls.call_args
        assert kwargs["daemon"] is True
        assert kwargs["target"] == handler._run_background_fetch
        assert kwargs["args"] == (self._TOPLEVEL, self._CWD)
        mock_thread_cls.return_value.start.assert_called_once()


class TestGitBranchRenderCache:
    """Tests for the short-TTL render cache (Plan 00155 T4).

    Status renders arrive every ~300 ms under output streaming; each render
    forks ~4 git processes. A short TTL cache keyed by cwd serves most renders
    from cache with at most TTL-bounded staleness — a CPU/battery win, as the
    render is asynchronous and not on any latency path.
    """

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        """Handler with auto-fetch off so the mocked side_effect list is stable."""
        handler = GitBranchHandler()
        handler._auto_fetch = False
        return handler

    @staticmethod
    def _clean_render_mocks() -> list[MagicMock]:
        """Four mocks for one full clean render.

        Order: rev-parse --show-toplevel, status --porcelain=v2 --branch,
        symbolic-ref (default-branch detection), stash list.
        """
        toplevel = MagicMock(returncode=0, stdout="/repo\n")
        symbolic_ref = MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
        stash = MagicMock(returncode=0, stdout="")
        return [toplevel, _status_mock("main"), symbolic_ref, stash]

    def test_second_render_within_ttl_served_from_cache(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """A second render for the same cwd within the TTL forks no git processes."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            # Two renders' worth of mocks; a working cache consumes only the first.
            mock_run.side_effect = self._clean_render_mocks() + self._clean_render_mocks()
            first = handler.handle(hook_input)
            forks_after_first = mock_run.call_count
            second = handler.handle(hook_input)
            forks_after_second = mock_run.call_count

        assert first.context == second.context
        assert forks_after_first == 4  # full render: toplevel, status, symbolic-ref, stash
        assert forks_after_second == forks_after_first  # second render added zero git forks

    def test_distinct_cwd_each_render(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Cache is keyed by cwd: a different directory is not served from another's entry."""
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._clean_render_mocks() + self._clean_render_mocks()
            handler.handle({"workspace": {"current_dir": str(repo_a)}})
            forks_after_a = mock_run.call_count
            handler.handle({"workspace": {"current_dir": str(repo_b)}})
            forks_after_b = mock_run.call_count

        # Two distinct cache entries, and repo_b forked rather than reusing repo_a's render.
        assert set(handler._render_cache) == {str(repo_a), str(repo_b)}
        assert forks_after_b > forks_after_a

    def test_ttl_zero_disables_cache(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Setting the render TTL to 0 disables caching (every render re-runs, nothing stored)."""
        handler._render_ttl_seconds = 0
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._clean_render_mocks() + self._clean_render_mocks()
            handler.handle(hook_input)
            forks_after_first = mock_run.call_count
            handler.handle(hook_input)
            forks_after_second = mock_run.call_count

        assert forks_after_second > forks_after_first  # second render executed (not cached)
        assert handler._render_cache == {}  # disabled cache stores nothing

    def test_expired_ttl_re_renders(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """Once the TTL elapses, the next render re-forks and refreshes the cache."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._clean_render_mocks() + self._clean_render_mocks()
            handler.handle(hook_input)
            forks_after_first = mock_run.call_count
            # Age the cache entry past the TTL without sleeping.
            cached_at, context = handler._render_cache[str(tmp_path)]
            handler._render_cache[str(tmp_path)] = (
                cached_at - (handler._render_ttl_seconds + 1.0),
                context,
            )
            handler.handle(hook_input)
            forks_after_second = mock_run.call_count

        assert forks_after_second > forks_after_first  # expiry forced a re-render


class TestWorktreeIndicator:
    """Tests for the linked-worktree tree icon in the git status segment.

    A git *linked* worktree (``git worktree add``) has a top-level ``.git``
    FILE pointing at ``<main>/.git/worktrees/<name>``; the main worktree has a
    ``.git`` DIRECTORY, and a submodule's ``.git`` file points at
    ``.../modules/<name>``. Detection is filesystem-only so it adds no
    subprocess call to the render hot path (the render still forks exactly 5
    git processes).
    """

    _TREE = "🌳"
    _PINK = "\033[38;5;205m"
    _GREEN = "\033[32m"

    @pytest.fixture
    def handler(self) -> GitBranchHandler:
        handler = GitBranchHandler()
        handler._auto_fetch = False  # side_effect mocks must not race a fetch thread
        return handler

    @staticmethod
    def _render_mocks(toplevel: Path) -> list[MagicMock]:
        """Standard 4-call render chain with a REAL toplevel path.

        The toplevel must be a real path so the filesystem worktree probe reads
        ``<toplevel>/.git``. Order: rev-parse --show-toplevel,
        status --porcelain=v2 --branch, symbolic-ref, stash list.
        """
        top = MagicMock(returncode=0, stdout=str(toplevel) + "\n")
        symbolic_ref = MagicMock(returncode=0, stdout="refs/remotes/origin/main\n")
        stash = MagicMock(returncode=0, stdout="")
        return [top, _status_mock("main"), symbolic_ref, stash]

    def test_linked_worktree_shows_tree_icon(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """A linked worktree (``.git`` file -> worktrees/) renders the tree icon."""
        (tmp_path / ".git").write_text("gitdir: /main/.git/worktrees/feature\n", encoding="utf-8")
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        assert self._TREE in result.context[0]

    def test_linked_worktree_tree_icon_precedes_branch(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """The tree icon renders *before* the branch name, not appended after it."""
        (tmp_path / ".git").write_text("gitdir: /main/.git/worktrees/feature\n", encoding="utf-8")
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        segment = result.context[0]
        assert segment.index(self._TREE) < segment.index("main")

    def test_main_worktree_omits_tree_icon(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """The main worktree (``.git`` directory) renders no tree icon."""
        (tmp_path / ".git").mkdir()
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        assert self._TREE not in result.context[0]

    def test_submodule_omits_tree_icon(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """A submodule (``.git`` file -> modules/) is not a worktree; no icon."""
        (tmp_path / ".git").write_text("gitdir: /main/.git/modules/libfoo\n", encoding="utf-8")
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        assert self._TREE not in result.context[0]

    def test_no_git_entry_omits_tree_icon(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """No ``.git`` entry at all -> no tree icon (render still succeeds)."""
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        assert self._TREE not in result.context[0]

    def test_worktree_detection_adds_no_subprocess_call(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        """Detection is filesystem-only: the render forks exactly 4 git processes.

        Four, not five, since Plan 00238 Task 2.1b: the branch name comes out
        of the status output instead of its own ``branch --show-current`` fork.
        """
        (tmp_path / ".git").write_text("gitdir: /main/.git/worktrees/feature\n", encoding="utf-8")
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            handler.handle(hook_input)
        assert mock_run.call_count == 4

    def test_is_linked_worktree_true_for_worktree_file(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").write_text("gitdir: /m/.git/worktrees/x\n", encoding="utf-8")
        assert handler._is_linked_worktree(str(tmp_path)) is True

    def test_is_linked_worktree_false_for_git_dir(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").mkdir()
        assert handler._is_linked_worktree(str(tmp_path)) is False

    def test_is_linked_worktree_false_for_submodule(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".git").write_text("gitdir: /m/.git/modules/x\n", encoding="utf-8")
        assert handler._is_linked_worktree(str(tmp_path)) is False

    def test_is_linked_worktree_false_when_missing(
        self, handler: GitBranchHandler, tmp_path: Path
    ) -> None:
        assert handler._is_linked_worktree(str(tmp_path)) is False

    def test_is_linked_worktree_false_on_non_string(self, handler: GitBranchHandler) -> None:
        """A non-str toplevel (e.g. a bare mock under other tests) fails safe to False."""
        assert handler._is_linked_worktree(MagicMock()) is False

    def test_worktree_branch_is_pink(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """In a worktree the branch name is pink, overriding the default-branch green.

        ``_render_mocks`` puts the checkout on ``main`` with ``origin/HEAD`` ->
        ``main``, which would normally colour the branch green. Inside a
        worktree the pink worktree colour must win instead.
        """
        (tmp_path / ".git").write_text("gitdir: /main/.git/worktrees/feature\n", encoding="utf-8")
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert self._PINK in rendered
        assert self._GREEN not in rendered

    def test_main_worktree_branch_not_pink(self, handler: GitBranchHandler, tmp_path: Path) -> None:
        """The main worktree keeps its normal colour (green here), never pink."""
        (tmp_path / ".git").mkdir()
        hook_input = {"workspace": {"current_dir": str(tmp_path)}}
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = self._render_mocks(tmp_path)
            result = handler.handle(hook_input)
        rendered = result.context[0]
        assert self._PINK not in rendered
        assert self._GREEN in rendered


class TestTheStatusRefreshTakesNoIndexLock:
    """Plan 00246: this is the MOST frequent lock-taker of the three.

    `_run_status` fires on every status-line render, in the agent's own working
    tree. `git status` refreshes the index and writes it back — taking
    `.git/index.lock` — so drawing the status line was contending with whatever
    git command the agent happened to be running.
    """

    def test_reading_the_status_does_not_rewrite_the_index(
        self, tmp_git_repo: Path, git_index_watch: Any
    ) -> None:
        handler = GitBranchHandler()

        with git_index_watch.expect_none(tmp_git_repo, "the status-line git status"):
            output = handler._run_status(str(tmp_git_repo))

        assert output is not None, "the status must still be read, not skipped"
        assert "branch.head" in output, output

    def test_the_control_shows_bare_git_status_rewrites_it(
        self, tmp_git_repo: Path, git_index_watch: Any
    ) -> None:
        """Without this, the assertion above could pass vacuously."""
        with git_index_watch.expect_one(tmp_git_repo, "bare git status --porcelain=v2"):
            subprocess.run(
                ["git", "status", "--porcelain=v2", "--branch"],
                cwd=tmp_git_repo,
                capture_output=True,
                check=True,
            )
