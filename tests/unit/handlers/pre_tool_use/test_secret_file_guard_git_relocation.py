"""``git -C <dir> grep`` is judged where it reads, through the handler (Plan 00618 S-1).

The Step 10 re-run found ``git -C deep grep --no-index -e .`` ALLOWED while the
equivalent ``cd deep && git grep --no-index -e .`` was DENIED, and git really
printed the ignored protected file. Synthetic files only.
"""

import subprocess
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


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _build(root: Path, *, git: bool) -> None:
    root.mkdir()
    if git:
        _git(root, "init", "-q")
        (root / ".gitignore").write_text(f"*.{_SUFFIX}\n")
    (root / _PROTECTED).write_bytes(b"not-a-real-value\n")
    (root / "sub").mkdir()
    (root / "sub" / "plain.txt").write_bytes(b"hello\n")
    (root / "deep").mkdir()
    (root / "deep" / f"key.{_SUFFIX}").write_bytes(b"not-a-real-value\n")
    if git:
        _git(root, "add", ".gitignore", "sub")


def _project(tmp_path: Path, *, git: bool) -> Iterator[Path]:
    root = tmp_path / "project"
    _build(root, git=git)
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """The reviewer's probe layout: not a git repository."""
    yield from _project(tmp_path, git=False)


@pytest.fixture()
def repo(tmp_path: Path) -> Iterator[Path]:
    """The same layout as a git repository with every protected file ignored."""
    yield from _project(tmp_path, git=True)


def _verdict(root: Path, command: str, cwd: Path | None = None) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


_REVIEWED_ALLOW_SHAPES = [
    "git -C deep grep --no-index -e .",
    "git --no-pager -C deep grep --no-index -e .",
    "git -C deep grep --no-index -e . .",
]

_DENIED_RELOCATIONS = [
    *_REVIEWED_ALLOW_SHAPES,
    "git -C deep grep --untracked -e .",
    "git -C sub -C ../deep grep --no-index -e .",
    "git -C sub grep --no-index -e . ../deep",
    "bash -c 'git -C deep grep --no-index -e .'",
    "git --work-tree=deep grep --untracked -e .",
    "git --git-dir=.git grep --untracked -e .",
    "git --attr-source HEAD grep --no-index -e .",
    "git -C $D grep --no-index -e .",
    'cd sub && git -C "$X" grep --no-index -e .',
    "GIT_WORK_TREE=deep git grep --untracked -e .",
]

_CONTROLS = [
    "cd deep && git grep --no-index -e .",
    "git grep --no-index -e . deep",
]


class TestReviewedShapesDeny:
    @pytest.mark.parametrize("command", _DENIED_RELOCATIONS)
    def test_denied_outside_a_repository(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize("command", _DENIED_RELOCATIONS)
    def test_denied_in_a_repository(self, repo: Path, command: str) -> None:
        assert _verdict(repo, command) is Decision.DENY

    @pytest.mark.parametrize("command", _CONTROLS)
    def test_the_controls_stay_denied(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    def test_from_a_subdirectory_a_parent_dash_c_reaches_the_root_file(self, repo: Path) -> None:
        assert _verdict(repo, "git -C .. grep --no-index -e .", cwd=repo / "sub") is Decision.DENY


class TestEquivalentToTheCdForm:
    @pytest.mark.parametrize(
        ("relocated", "changed_directory"),
        [
            ("git -C deep grep --no-index -e .", "cd deep && git grep --no-index -e ."),
            ("git -C sub grep --no-index -e .", "cd sub && git grep --no-index -e ."),
            ("git -C sub grep -e x", "cd sub && git grep -e x"),
            ("git -C deep grep -e x", "cd deep && git grep -e x"),
        ],
    )
    def test_same_verdict(self, repo: Path, relocated: str, changed_directory: str) -> None:
        assert _verdict(repo, relocated) is _verdict(repo, changed_directory)


class TestOrdinaryRelocatedSearchesStayAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            "git -C sub grep --no-index -e .",
            "git -C sub grep -n hello",
            "git -C deep grep -n hello",
            "git --no-pager -C sub grep -n hello",
            "git -C sub log --oneline -1",
        ],
    )
    def test_allowed(self, repo: Path, command: str) -> None:
        assert _verdict(repo, command) is Decision.ALLOW


class TestAPathAnchoredProtectedPath:
    """A configured path with a directory part is reached through ``git -C`` too."""

    @pytest.fixture()
    def anchored(self, tmp_path: Path) -> Iterator[tuple[Path, SecretFileGuardHandler]]:
        root = tmp_path / "project"
        root.mkdir()
        _git(root, "init", "-q")
        (root / "vault").mkdir()
        (root / "vault" / "creds.json").write_bytes(b"{}\n")
        (root / "other").mkdir()
        (root / "other" / "creds.json").write_bytes(b"{}\n")
        handler = SecretFileGuardHandler()
        handler._protected_paths = ["vault/creds.json"]
        protected_file_index.reset_index_cache()
        with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
            index_project(root, handler._patterns())
            yield root, handler
        protected_file_index.reset_index_cache()

    @staticmethod
    def _decide(handler: SecretFileGuardHandler, root: Path, command: str) -> Decision:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(root),
        }
        if not handler.matches(hook_input):
            return Decision.ALLOW
        return handler.handle(hook_input).decision

    @pytest.mark.parametrize(
        "command",
        [
            "cd vault && git show HEAD:creds.json",
            "git -C vault show HEAD:creds.json",
            "git -C vault grep --no-index -e . creds.json",
        ],
    )
    def test_denied(self, anchored: tuple[Path, SecretFileGuardHandler], command: str) -> None:
        root, handler = anchored
        assert self._decide(handler, root, command) is Decision.DENY

    def test_the_same_name_elsewhere_is_allowed(
        self, anchored: tuple[Path, SecretFileGuardHandler]
    ) -> None:
        root, handler = anchored
        assert self._decide(handler, root, "git -C other show HEAD:creds.json") is Decision.ALLOW


# The S-1 review's listed test gaps: every one of these git moves fails closed.
_WORK_TREE_MOVES = [
    "git -c core.worktree=deep grep -e x",
    "git -C sub -c core.worktree=.. grep -e x",
    "git -c core.worktree=.. -C sub grep -e x",
    "git --config-env=core.worktree=WT grep -e x",
    "git --config-env core.worktree=WT -C sub grep -e x",
    "GIT_DIR=.git git grep -e x",
    "GIT_WORK_TREE=deep git grep -e x",
    "env GIT_WORK_TREE=deep git grep -e x",
    "env GIT_DIR=.git git -C sub grep -e x",
]

_UNPLACEABLE_DASH_C_VALUES = [
    "git -C de* grep --no-index -e .",
    "git -C dee? grep --no-index -e .",
    "git -C {deep,sub} grep --no-index -e .",
    "git -C sub -C $X grep -e hello",
    "git -C $(pwd)/deep grep --no-index -e .",
]

_WRAPPED = [
    "sudo git -C deep grep --no-index -e .",
    "sudo -u git git -C deep grep --no-index -e .",
    "env git -C deep grep --no-index -e .",
    "env -u git git -C deep grep --no-index -e .",
    "timeout 5 git -C deep grep --no-index -e .",
    "nice git -C deep grep --no-index -e .",
    "/usr/bin/git -C deep grep --no-index -e .",
    "bash -c 'git -C deep grep --no-index -e .'",
    "xargs git -C deep grep --no-index -e . < /dev/null",
    "echo x | xargs git -C deep grep --no-index -e .",
]

# Deliberate fail-closed over-blocks: the named tree holds no protected file,
# but a moved work tree or git dir is not narrowed. Pinned so a later
# narrowing is a decision, not an accident.
_DELIBERATE_DENIALS = [
    "git --work-tree=sub grep -e hello",
    "git --git-dir=.git grep -e hello",
    "git -c core.worktree=sub grep -e hello",
    "GIT_WORK_TREE=sub git grep -e hello",
]


class TestTheReviewedGapsFailClosed:
    @pytest.mark.parametrize(
        "command", [*_WORK_TREE_MOVES, *_UNPLACEABLE_DASH_C_VALUES, *_WRAPPED]
    )
    def test_denied_in_a_repository(self, repo: Path, command: str) -> None:
        assert _verdict(repo, command) is Decision.DENY, command

    @pytest.mark.parametrize("command", _DELIBERATE_DENIALS)
    def test_a_moved_tree_is_denied_even_when_it_is_clean(self, repo: Path, command: str) -> None:
        assert _verdict(repo, command) is Decision.DENY, command

    @pytest.mark.parametrize(
        "command",
        [
            "git -C sub grep -e hello",
            "git -C sub log --oneline",
            "git -C sub show HEAD",
            "git -C sub diff",
            "git -C deep log --oneline",
            "git -c core.pager=cat -C sub grep -e hello",
        ],
    )
    def test_ordinary_dash_c_use_stays_allowed(self, repo: Path, command: str) -> None:
        assert _verdict(repo, command) is Decision.ALLOW, command


class TestATildeDashCValue:
    """``~`` is placed at ``$HOME``: judged like ``grep -r x ~``."""

    def test_home_above_the_project_denies(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(repo.parent))
        assert _verdict(repo, "git -C ~ grep --no-index -e .") is Decision.DENY

    def test_home_elsewhere_allows(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setenv("HOME", str(elsewhere))
        assert _verdict(repo, "git -C ~ grep --no-index -e .") is Decision.ALLOW
