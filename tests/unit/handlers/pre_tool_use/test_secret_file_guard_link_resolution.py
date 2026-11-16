"""A protected file reached through a link is judged on the file it reaches (Plan 00614).

Plan 00613's probe found three ways a worktree's links reach a protected file of
another checkout past the guard:

1. a RELATIVE Bash token naming a link, resolved against the daemon process cwd
   (the daemon runs from ``/``) instead of the hook payload's ``cwd``;
2. a recursive search (Grep tool, ``grep -r``) rooted at a directory link that
   leads out of the indexed project;
3. a glob under a directory link (``cat dlink/*``), never realpath-resolved.

Every fixture is synthetic: a throwaway primary checkout holding an untracked
dummy file named like a protected one, a registered ``git worktree`` of it, and
links inside the worktree. The process cwd is ``/`` throughout, as in the daemon.
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
from tests.vault_payloads import vault_file_bytes

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells a protected name itself.
_PROTECTED = "id_" + "rsa"
_DUMMY = b"DUMMY\n"


@dataclass(frozen=True)
class Checkouts:
    """The primary checkout, its worktree and a plain directory outside both."""

    primary: Path
    worktree: Path
    outside: Path


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def checkouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Checkouts]:
    """A primary with untracked dummy protected files, a worktree of it, and links."""
    base = tmp_path.resolve()
    primary = base / "primary"
    primary.mkdir()
    _git("init", "-q", "-b", "main", cwd=primary)
    _git("config", "user.email", "test@example.invalid", cwd=primary)
    _git("config", "user.name", "test", cwd=primary)
    (primary / "readme.txt").write_bytes(b"hello\n")
    (primary / "clean").mkdir()
    (primary / "clean" / "plain.txt").write_bytes(b"hello\n")
    _git("add", "-A", cwd=primary)
    _git("commit", "-qm", "init", cwd=primary)
    # Untracked, as a real secret is: the worktree checks out none of them.
    (primary / _PROTECTED).write_bytes(_DUMMY)
    (primary / "sub").mkdir()
    (primary / "sub" / _PROTECTED).write_bytes(_DUMMY)

    worktree = base / "wt"
    _git("worktree", "add", "-q", "-b", "feat", str(worktree), cwd=primary)
    (worktree / "link1.txt").symlink_to(os.path.relpath(primary / _PROTECTED, worktree))
    (worktree / "dlink").symlink_to(os.path.relpath(primary / "sub", worktree))
    (worktree / "link2.txt").symlink_to(f"dlink/{_PROTECTED}")
    (worktree / "plink").symlink_to(os.path.relpath(primary, worktree))
    (worktree / "link4.txt").symlink_to("link1.txt")
    (worktree / "cleanlink").symlink_to("clean")

    outside = base / "outside"
    outside.mkdir()
    (outside / "plain.txt").write_bytes(b"hello\n")
    (worktree / "outlink").symlink_to(os.path.relpath(outside, worktree))

    monkeypatch.chdir("/")
    protected_file_index.reset_index_cache()
    yield Checkouts(primary=primary, worktree=worktree, outside=outside)
    protected_file_index.reset_index_cache()


@pytest.fixture(params=["worktree", "primary"])
def project(request: pytest.FixtureRequest, checkouts: Checkouts) -> Iterator[Path]:
    """The project root the daemon serves: the worktree, or the primary checkout."""
    root: Path = getattr(checkouts, request.param)
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root


def _verdict(cwd: Path, tool: str, tool_input: dict[str, Any]) -> Decision:
    hook_input: dict[str, Any] = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _bash(checkouts: Checkouts, command: str) -> Decision:
    return _verdict(checkouts.worktree, "Bash", {"command": command})


class TestRelativeLinkTokenResolvedAgainstHookCwd:
    """Gap 1: a relative token is resolved from the hook's cwd, not the process cwd."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat link1.txt",
            "cat < link1.txt",
            "head -n 1 link2.txt",
            "cat link4.txt",
            "python3 -c \"print(open('link1.txt').read())\"",
            f"grep {_PROTECTED} link1.txt",
            "cd clean && cat ../link1.txt",
        ],
    )
    def test_relative_link_to_protected_file_denied(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.DENY

    def test_relative_read_path_denied(self, checkouts: Checkouts, project: Path) -> None:
        assert _verdict(checkouts.worktree, "Read", {"file_path": "link1.txt"}) is Decision.DENY

    def test_absolute_link_still_denied(self, checkouts: Checkouts, project: Path) -> None:
        assert _bash(checkouts, f"cat {checkouts.worktree / 'link1.txt'}") is Decision.DENY
        path = str(checkouts.worktree / "link1.txt")
        assert _verdict(checkouts.worktree, "Read", {"file_path": path}) is Decision.DENY

    def test_literal_protected_path_still_denied(self, checkouts: Checkouts, project: Path) -> None:
        assert _bash(checkouts, f"cat {checkouts.primary / _PROTECTED}") is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "cat readme.txt",
            "cat no-such-file.txt",
            "ls dlink",
            "cat outlink/plain.txt",
            "cat cleanlink/plain.txt",
            "echo " + "a" * 5000,
            "grep -c hello readme.txt",
        ],
    )
    def test_ordinary_relative_tokens_allowed(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.ALLOW


def test_strict_variant_resolves_a_relative_link_from_the_hook_cwd(
    checkouts: Checkouts, project: Path
) -> None:
    """``find_protected_mention_strict`` places a relative link under ``cwd``, index or not."""
    patterns = SecretFileGuardHandler()._patterns()
    cwd = str(checkouts.worktree)
    assert sfm.find_protected_mention_strict("cat link1.txt", patterns, cwd=cwd) is not None
    assert sfm.find_protected_mention_strict("cat readme.txt", patterns, cwd=cwd) is None


class TestExemptionsJudgeRelativeLinksFromHookCwd:
    """An exemption that clears a command must not clear a relative link beside it."""

    # Assembled, like _PROTECTED, so this file never spells a protected name.
    _VAULT_REL = "group_vars/all/" + "vault_" + "passwords.yml"
    _PASSWORD_FILE = "." + "vault-" + "pass"

    @pytest.fixture()
    def encrypted(self, checkouts: Checkouts) -> Path:
        target = checkouts.worktree / self._VAULT_REL
        target.parent.mkdir(parents=True)
        target.write_bytes(vault_file_bytes())
        return target

    def test_encrypted_target_exemption_does_not_clear_a_relative_link(
        self, checkouts: Checkouts, project: Path, encrypted: Path
    ) -> None:
        if project == checkouts.primary:
            pytest.skip("an encrypted file outside the project root is never exempt")
        assert _bash(checkouts, f"git add {self._VAULT_REL}") is Decision.ALLOW
        assert _bash(checkouts, f"cat {self._VAULT_REL} link1.txt") is Decision.DENY

    def test_consumer_exemption_does_not_clear_a_relative_link(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        flags = f"ansible-playbook --vault-password-file {self._PASSWORD_FILE}"
        assert _bash(checkouts, f"{flags} site.yml") is Decision.ALLOW
        assert _bash(checkouts, f"{flags} link1.txt") is Decision.DENY


class TestSearchRootedAtLinkLeadingOutOfProject:
    """Gap 2: a search rooted at a directory link out of the project is not vouched for."""

    @pytest.mark.parametrize("name", ["dlink", "plink"])
    def test_grep_tool_on_directory_link_denied(
        self, checkouts: Checkouts, project: Path, name: str
    ) -> None:
        path = str(checkouts.worktree / name)
        decision = _verdict(checkouts.worktree, "Grep", {"pattern": "x", "path": path})
        assert decision is Decision.DENY

    def test_grep_tool_relative_directory_link_denied(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        decision = _verdict(checkouts.worktree, "Grep", {"pattern": "x", "path": "dlink"})
        assert decision is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r x dlink",
            "grep -r x plink/",
            "rg x dlink",
            "grep -rl x plink",
            "grep -r x plink/*/",
            "grep -r x plink/s*",
        ],
    )
    def test_recursive_bash_search_on_directory_link_denied(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.DENY

    @pytest.mark.parametrize("command", ["grep -r x clean", "grep -r x cleanlink"])
    def test_search_of_clean_in_project_directory_allowed(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        if project == checkouts.primary:
            pytest.skip("the primary holds no clean link of its own")
        assert _bash(checkouts, command) is Decision.ALLOW

    def test_plain_root_outside_project_unchanged(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        """A root outside the project that no link leads to is judged as before."""
        assert _bash(checkouts, f"grep -r x {checkouts.outside}") is Decision.ALLOW


class TestGlobUnderDirectoryLink:
    """Gap 3: a glob whose literal directory is a link is judged where the link leads."""

    @pytest.mark.parametrize("command", ["cat dlink/*", "head plink/*/*", "cat plink/sub/*"])
    def test_glob_through_directory_link_denied(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.DENY

    def test_absolute_glob_through_directory_link_denied(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        assert _bash(checkouts, f"cat {checkouts.worktree / 'dlink'}/*") is Decision.DENY

    @pytest.mark.parametrize("command", ["cat clean/*", "cat cleanlink/*", "ls clean/*.txt"])
    def test_glob_over_clean_directory_allowed(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.ALLOW

    def test_glob_through_link_to_clean_outside_directory_is_not_vouched_for(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        """The index lists only the project; a link out of it is not judged clean."""
        if project == checkouts.primary:
            pytest.skip("the link sits outside the primary, which judges it as before")
        assert _bash(checkouts, "cat outlink/*") is Decision.DENY
