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
from claude_code_hooks_daemon.utils import path_exclusion, protected_file_index
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
    # One level down, for a `cd` the command makes before naming a link.
    inner = worktree / "inner"
    inner.mkdir()
    (inner / "ilink").symlink_to(os.path.relpath(primary / _PROTECTED, inner))
    (inner / "idlink").symlink_to(os.path.relpath(primary / "sub", inner))

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
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
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


def _reason(cwd: Path, tool: str, tool_input: dict[str, Any]) -> str:
    """The deny reason of a call that must be denied."""
    hook_input: dict[str, Any] = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    handler = SecretFileGuardHandler()
    assert handler.matches(hook_input)
    result = handler.handle(hook_input)
    assert result.decision is Decision.DENY
    return str(result.reason)


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


class TestDirectoryChangeTheCommandMakes:
    """Review F1: a ``cd`` anywhere bash runs it moves where a relative word is read."""

    @pytest.mark.parametrize(
        "command",
        [
            "(cd inner && cat ilink)",
            "( cd inner ; cat ilink )",
            "{ cd inner; cat ilink; }",
            "if cd inner; then cat ilink; fi",
            'x=$(cd inner && cat ilink); echo "$x"',
            'x="$(cd inner && cat ilink)"',
            "x=`cd inner && cat ilink`",
            "bash -c 'cd inner && cat ilink'",
            'sh -c "cd inner; cat ilink"',
            "env -C inner cat ilink",
            "env --chdir=inner cat ilink",
            "env -u HOME -C inner cat ilink",
            "git -C inner diff --no-index ilink /dev/null",
            "git -c core.pager=cat -C inner diff --no-index ilink /dev/null",
            "while cd inner; do cat ilink; break; done",
            "(cd inner && cat idlink/*)",
            "(cd inner && grep -r . idlink)",
            "(cd inner && cat ../link1.txt)",
            "{ cd inner; grep -r x idlink; }",
            'x="$(cd inner && grep -r x idlink)"',
            "bash -c 'cd inner && grep -r x idlink'",
            "env -C inner grep -r x idlink",
            # A group's cd ADDS a directory: the later top-level cd is still placed
            # from the hook cwd, so it must not be read from inside the group's.
            "(cd clean && true); cd inner && cat ilink",
            "cd clean && (cd x); cd ../inner && cat ilink",
            "(cd clean && true); grep -r x inner/idlink",
        ],
    )
    def test_link_read_after_a_wrapped_cd_denied(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "(cd clean && cat plain.txt)",
            "env -C clean cat plain.txt",
            "{ cd clean; cat plain.txt; }",
            "bash -c 'cd clean && cat plain.txt'",
            # A plain top-level cd REPLACES the directory a search is read from.
            "cd clean && grep -r hello .",
            "(cd clean && grep -r hello .)",
        ],
    )
    def test_ordinary_wrapped_cd_allowed(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.ALLOW

    def test_top_level_cd_replaces_the_search_directory(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        """``cd clean && grep -r x .`` reads clean only, never the hook cwd as well."""
        reads = sfm_reads("cd clean && grep -r hello .", checkouts.worktree)
        assert reads == [str(checkouts.worktree / "clean")]

    def test_indeterminate_cd_reads_from_the_project_root(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        if project == checkouts.primary:
            pytest.skip("the links sit in the worktree, not under the primary's root")
        clean = checkouts.worktree / "clean"
        assert _verdict(clean, "Bash", {"command": "cat inner/ilink"}) is Decision.ALLOW
        command = 'cd "$D" && cat inner/ilink'
        assert _verdict(clean, "Bash", {"command": command}) is Decision.DENY
        command = 'cd "$D" && grep -r x dlink'
        assert _verdict(clean, "Bash", {"command": command}) is Decision.DENY


def sfm_reads(command: str, cwd: Path) -> list[str]:
    """The roots ``recursive_search`` places for ``command`` run from ``cwd``."""
    from claude_code_hooks_daemon.utils import recursive_search

    return [read.root for read in recursive_search.search_reads(command, str(cwd))]


class TestGlobWildcardOnTheLinkComponent:
    """Review F2: a wildcard in the component that matches a directory link."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat dl*/*",
            "cat d*/*",
            "cat dlin?/*",
            "cat dlink*/*",
            "cat pl*/*",
            "cat pl*/sub/*",
            "grep -r x dl*",
            "grep -r x pl*/sub",
            "(cd inner && cat idl*/*)",
        ],
    )
    def test_wildcard_link_component_denied(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.DENY

    @pytest.mark.parametrize("command", ["cat */*", "cat cle*/*", "ls cle*/*.txt"])
    def test_wildcard_over_clean_or_nameless_allowed(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        assert _bash(checkouts, command) is Decision.ALLOW


class TestLinkOutDenyExplainsTheLink:
    """Review F4: a deny caused by a link out of the project says so."""

    @pytest.fixture(autouse=True)
    def _worktree_only(self, checkouts: Checkouts, project: Path) -> None:
        if project == checkouts.primary:
            pytest.skip("outlink sits outside the primary, which judges it by name")

    @staticmethod
    def _assert_explains(reason: str, link: str) -> None:
        assert f"`{link}`" in reason
        assert "link to a directory outside the project" in reason
        assert "run the command from the checkout that holds" in reason
        assert "real path" not in reason

    @pytest.mark.parametrize(
        "command",
        ["cat outlink/*", "grep -r hello outlink", "cat out*/*", f"grep -r {_PROTECTED} outlink"],
    )
    def test_bash_deny_names_the_link(
        self, checkouts: Checkouts, project: Path, command: str
    ) -> None:
        reason = _reason(checkouts.worktree, "Bash", {"command": command})
        self._assert_explains(reason, "outlink")
        # The target is never offered: a path outside the project is judged by name only.
        assert str(checkouts.outside) not in reason

    def test_grep_tool_deny_names_the_link(self, checkouts: Checkouts, project: Path) -> None:
        path = str(checkouts.worktree / "outlink")
        reason = _reason(checkouts.worktree, "Grep", {"pattern": "x", "path": path})
        self._assert_explains(reason, path)

    def test_a_protected_name_deny_does_not_blame_a_link(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        reason = _reason(checkouts.worktree, "Bash", {"command": f"cat {_PROTECTED}"})
        assert "link to a directory outside the project" not in reason


class TestBoundedCostOfManyDirectoryChanges:
    """Review F5: many ``cd`` targets must not multiply the per-word filesystem calls."""

    _WORDS = 3000
    _CDS = 200

    def _command(self, targets: list[str]) -> str:
        cds = " && ".join(f"cd {target}" for target in targets)
        words = " ".join(f"word{n}.txt" for n in range(self._WORDS))
        return f"{cds} && echo {words}"

    def test_many_absent_directories_cost_about_one_call_per_word(
        self, checkouts: Checkouts, project: Path
    ) -> None:
        """The calls a word costs do not grow with the number of ``cd`` targets that do not exist."""
        with patch.object(sfm.os.path, "lexists", wraps=os.path.lexists) as spy:
            assert _bash(checkouts, self._command(["/nonexistent-614/d0"])) is Decision.ALLOW
        baseline = spy.call_count
        targets = [f"/nonexistent-614/d{n}" for n in range(self._CDS)]
        relative = [f"r{n}" for n in range(self._CDS)]
        for chosen in (targets, relative):
            command = self._command(chosen)
            with patch.object(sfm.os.path, "lexists", wraps=os.path.lexists) as spy:
                assert _bash(checkouts, command) is Decision.ALLOW
            # A scan that outlives its deadline is followed by one strict re-scan, so
            # the bound is a few scans' worth -- not one call per word per cd (main: 201).
            assert spy.call_count <= 3 * baseline

    def test_many_real_directories_fail_closed_on_a_link_word(
        self, checkouts: Checkouts, project: Path, tmp_path: Path
    ) -> None:
        """Past the cap a relative word that could be a link is a finding, not a skipped check."""
        many = tmp_path / "many"
        targets = []
        for n in range(self._CDS):
            directory = many / f"d{n}"
            directory.mkdir(parents=True)
            targets.append(str(directory))
        targets.append(str(checkouts.worktree / "inner"))
        cds = " && ".join(f"cd {target}" for target in targets[1:]) + f" && cd {targets[0]}"
        with patch.object(sfm.os.path, "lexists", wraps=os.path.lexists) as spy:
            assert _bash(checkouts, f"{cds} && cat ilink") is Decision.DENY
            assert _bash(checkouts, f"{cds} && echo {'w ' * self._WORDS}") is Decision.ALLOW
        assert spy.call_count <= 40 * self._WORDS
