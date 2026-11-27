"""Undashed and argument-fed `git checkout` path restores are judged (Plan 00474, N764, N765).

N764: `git checkout <commit> <path>` restores the path from the commit exactly as the dashed
form does, and `git checkout <path>` restores it from the index, yet R-GIT-CHECKOUT-DISCARD
keyed on the `--` separator, so neither was seen. Git reads the undashed form by resolving
the first operand: a revision that is not also a file makes the rest paths; a revision that
is also a file is ambiguous and git refuses; anything else makes every operand a path from
the index. The undashed form now gets the SAME allowance as the dashed one when the first
operand is a commit git cannot read as a path, and is denied otherwise. A real branch switch
(one operand that is a commit, or one that is neither a commit nor a path) stays allowed.

N765: `... | xargs git checkout <commit> --` gets its paths from stdin, so no path was
there to judge. A checkout or restore run by a command that can append arguments (xargs,
parallel, find -exec, or any runner this reading does not know) is denied, as is one fed
by a pipe or an input redirect.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import destructive_git
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.utils.git_repo import run_git

_GIT_IDENTITY = (
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.invalid",
    "-c",
    "commit.gpgsign=false",
)
_OLD = "HEAD~1"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *_GIT_IDENTITY, *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """HEAD~1 holds `old.txt` and `olddir/f.txt`; HEAD deleted them.

    `a.txt` and `sub/c.txt` are tracked and clean in both commits; branch `side` and tag
    `v1` point at HEAD~1.
    """
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "sub").mkdir()
    (repo / "olddir").mkdir()
    for name in ("a.txt", "sub/c.txt", "old.txt", "olddir/f.txt"):
        (repo / name).write_text(f"content of {name}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "side")
    _git(repo, "tag", "v1")
    _git(repo, "rm", "-q", "-r", "old.txt", "olddir")
    _git(repo, "commit", "-q", "-m", "drop")
    return repo


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _hook_input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _verdict(handler: DestructiveGitHandler, command: str, cwd: Path) -> tuple[Decision, str]:
    """The decision the daemon would reach: no match is an allow."""
    hook_input = _hook_input(command, cwd)
    if not handler.matches(hook_input):
        return Decision.ALLOW, ""
    result = handler.handle(hook_input)
    return result.decision, result.rule or ""


def _denied(handler: DestructiveGitHandler, command: str, cwd: Path, rule: str) -> None:
    hook_input = _hook_input(command, cwd)
    assert handler.matches(hook_input) is True
    result = handler.handle(hook_input)
    assert (result.decision, result.rule) == (Decision.DENY, rule)


def _allowed(handler: DestructiveGitHandler, command: str, cwd: Path) -> None:
    assert _verdict(handler, command, cwd)[0] == Decision.ALLOW


class TestTheUndashedPathFormIsJudgedLikeTheDashedOne:
    """N764: `git checkout <commit> <paths>` reads exactly as `<commit> -- <paths>`."""

    def test_an_unstaged_edit_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {_OLD} a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_staged_edit_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").write_text("my staged edit\n")
        _git(repo, "add", "a.txt")
        _denied(handler, f"git checkout {_OLD} a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_an_untracked_file_at_the_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "old.txt").write_text("new local work\n")
        _denied(handler, f"git checkout {_OLD} old.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_one_clean_and_one_edited_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "sub" / "c.txt").write_text("my unsaved edit\n")
        _denied(
            handler, f"git checkout {_OLD} old.txt sub/c.txt", repo, RuleID.GIT_CHECKOUT_DISCARD
        )

    @pytest.mark.parametrize("revision", [_OLD, "side", "v1", "main~1"])
    def test_an_absent_path_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, revision: str
    ) -> None:
        _allowed(handler, f"git checkout {revision} old.txt", repo)

    def test_a_commit_hash_is_allowed(self, handler: DestructiveGitHandler, repo: Path) -> None:
        commit = _git(repo, "rev-parse", "--short", _OLD)
        _allowed(handler, f"git checkout {commit} old.txt olddir/f.txt", repo)

    def test_clean_tracked_files_are_allowed(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _allowed(handler, f"git checkout {_OLD} a.txt sub/c.txt", repo)

    def test_a_dash_c_directory_is_judged_there(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        _allowed(handler, f"git -C {repo} checkout {_OLD} old.txt", tmp_path)
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(
            handler,
            f"git -C {repo} checkout {_OLD} a.txt",
            tmp_path,
            RuleID.GIT_CHECKOUT_DISCARD,
        )

    def test_the_allowed_command_really_restores_the_file(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _allowed(handler, f"git checkout {_OLD} old.txt", repo)
        _git(repo, "checkout", _OLD, "old.txt")
        assert (repo / "old.txt").read_text() == "content of old.txt\n"

    @pytest.mark.parametrize(
        "command",
        [
            f'git check""out {_OLD} a.txt',
            f"git check\\out {_OLD} a.txt",
            f'git "checkout" {_OLD} a.txt',
            f"git checkout '{_OLD}' 'a.txt'",
            f'env -S "git checkout {_OLD} a.txt"',
            f"bash -c 'git checkout {_OLD} a.txt'",
            f"eval 'git checkout {_OLD} a.txt'",
        ],
    )
    def test_a_quoted_or_inlined_spelling_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_the_denial_names_the_path(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        result = handler.handle(_hook_input(f"git checkout {_OLD} a.txt", repo))
        assert "`a.txt`" in (result.reason or "")


class TestARevisionGitCannotTellFromAPathIsDenied:
    def test_a_revision_that_is_also_a_file_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """Git refuses it as ambiguous; the guard does not guess which reading wins."""
        (repo / "side").write_text("a file named like the branch\n")
        _denied(handler, "git checkout side old.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_revision_that_is_also_an_index_entry_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "side").write_text("tracked\n")
        _git(repo, "add", "side")
        _git(repo, "commit", "-q", "-m", "file side")
        (repo / "side").unlink()
        _denied(handler, "git checkout side old.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "first", ["nosuchref", "-", f"{_OLD}...HEAD", "'$REV'", "'*.txt'", ":/a.txt"]
    )
    def test_a_first_operand_that_is_not_one_literal_resolved_commit_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, first: str
    ) -> None:
        """An unresolved first operand makes git restore every operand from the index."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {first} a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_tree_that_is_not_a_commit_is_still_judged(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        tree = _git(repo, "rev-parse", f"{_OLD}^{{tree}}")
        _allowed(handler, f"git checkout {tree} old.txt", repo)
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"git checkout {tree} a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)


class TestARestoreFromTheIndexWithoutTheDashIsDenied:
    """`git checkout <path>` restores from the index, as `git checkout -- <path>` does."""

    def test_an_edited_path_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, "git checkout a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_clean_path_is_denied_as_the_dashed_form_is(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _denied(handler, "git checkout a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_deleted_tracked_path_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").unlink()
        _denied(handler, "git checkout a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_directory_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "sub" / "c.txt").write_text("my unsaved edit\n")
        _denied(handler, "git checkout sub", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_directory_deleted_from_the_worktree_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "sub" / "c.txt").unlink()
        (repo / "sub").rmdir()
        _denied(handler, "git checkout sub", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_two_paths_are_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        _denied(handler, "git checkout a.txt sub/c.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "operand", ["'*.txt'", "'a.tx?'", "':(top)a.txt'", ":/a.txt", '"$F"', "$F", "."]
    )
    def test_an_operand_that_is_not_one_literal_name_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, operand: str
    ) -> None:
        _denied(handler, f"git checkout {operand}", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_dangling_symlink_is_denied(self, handler: DestructiveGitHandler, repo: Path) -> None:
        (repo / "link").symlink_to("nowhere")
        _denied(handler, "git checkout link", repo, RuleID.GIT_CHECKOUT_DISCARD)


class TestOptionsThatMakeAPathCheckoutAreDenied:
    @pytest.mark.parametrize(
        "command",
        [
            "git checkout -m a.txt",
            "git checkout --merge a.txt",
            f"git checkout --no-overlay {_OLD} a.txt",
            "git checkout --ours a.txt",
            "git checkout --theirs a.txt",
            "git checkout -p",
            f"git checkout -p {_OLD}",
            "git checkout --patch",
            "git checkout --pathspec-from-file=list.txt",
            f"git checkout --pathspec-from-file=list.txt {_OLD}",
            f"git checkout --pathspec-from-file list.txt {_OLD}",
            "git checkout --conflict=diff3 a.txt",
            "git checkout --ignore-skip-worktree-bits a.txt",
            f"git checkout -q {_OLD} a.txt",
            f"git checkout --detach {_OLD} a.txt",
        ],
    )
    def test_the_command_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        assert _verdict(handler, command, repo)[0] == Decision.DENY


class TestARealBranchSwitchStaysAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            "git checkout main",
            "git checkout side",
            "git checkout v1",
            f"git checkout {_OLD}",
            "git checkout -",
            "git checkout -q side",
            "git checkout --quiet side",
            "git checkout -b feature",
            "git checkout -b feature side",
            "git checkout -bnew side",
            "git checkout -qb feature side",
            "git checkout -B feature side",
            "git checkout --orphan fresh",
            "git checkout --orphan=fresh",
            f"git checkout --detach {_OLD}",
            "git checkout -t side",
            "git checkout --track side",
            "git checkout --no-track -b feature side",
            "git checkout -m side",
            "git checkout --recurse-submodules side",
            "git checkout --no-guess side",
            f"git checkout {_OLD} --",
            "git checkout",
            "git checkout not-a-ref-and-not-a-path",
            "git checkout main && git log --oneline -1",
            "git checkout -b feature && git status",
            "cd sub && git checkout side",
            "echo git checkout HEAD a.txt",
            "grep 'git checkout HEAD a.txt' notes.md",
            "git commit -q --allow-empty -m 'git checkout HEAD a.txt'",
        ],
    )
    def test_the_switch_is_allowed_with_local_edits_present(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """A switch never overwrites local changes (git refuses), so `a.txt`'s edit is safe."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, command, repo)

    def test_a_branch_named_like_an_existing_file_still_switches(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """Git switches when the one operand is a commit, even if a file has that name."""
        (repo / "side").write_text("a file named like the branch\n")
        _allowed(handler, "git checkout side", repo)

    def test_an_unreadable_single_operand_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If git cannot say the operand is a commit, the operand may be a path: deny."""

        def failing(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")

        monkeypatch.setattr(destructive_git, "run_git", failing)
        _denied(handler, "git checkout a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_failed_index_listing_of_a_single_operand_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def listing_fails(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "ls-files" in args:
                return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", listing_fails)
        _denied(handler, "git checkout not-a-ref", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_dash_c_target_that_is_not_a_directory_denies(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        _denied(handler, "git -C a.txt checkout side", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_mention_beside_a_real_switch_is_not_judged(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """The echoed run is not in command position; the switch after it is a commit."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, f"echo git checkout {_OLD} a.txt && git checkout side", repo)

    def test_a_refused_lookup_of_a_single_operand_denies(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`not-a-ref` would be a switch, but a lookup that fails is not an absence."""
        real_lstat = Path.lstat

        def refusing(self: Path) -> Any:
            if self.name == "not-a-ref":
                raise PermissionError("lstat refused")
            return real_lstat(self)

        monkeypatch.setattr(Path, "lstat", refusing)
        _denied(handler, "git checkout not-a-ref", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_an_exhausted_deadline_denies_a_path_operand(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(destructive_git, "_CHECKOUT_PROOF_BUDGET", 0.0)
        _denied(handler, "git checkout a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "GIT_DIR=elsewhere git checkout main",
            "git --git-dir=elsewhere checkout main",
            "git --work-tree=elsewhere checkout main",
            'cd "$WHERE" && git checkout a.txt',
        ],
    )
    def test_a_single_operand_whose_repository_cannot_be_placed_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        assert _verdict(handler, command, repo)[0] == Decision.DENY

    def test_a_compound_path_checkout_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(
            handler,
            f"git checkout {_OLD} old.txt && git checkout {_OLD} a.txt",
            repo,
            RuleID.GIT_CHECKOUT_DISCARD,
        )
        _denied(
            handler, f"git status; git checkout {_OLD} a.txt", repo, RuleID.GIT_CHECKOUT_DISCARD
        )

    def test_a_path_checkout_through_a_wrapper_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        for command in (f"sudo git checkout {_OLD} old.txt", f"env git checkout {_OLD} old.txt"):
            _denied(handler, command, repo, RuleID.GIT_CHECKOUT_DISCARD)


class TestAForcedCheckoutIndexIsDenied:
    """`git checkout-index -f` overwrites worktree files from the index; `checkout\\s+` missed it."""

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout-index -f a.txt",
            "git checkout-index -af",
            "git checkout-index -a -f",
            "git checkout-index --force --all",
            "git checkout-index -f -- a.txt",
            "git -C . checkout-index -uf a.txt",
            "echo a.txt | git checkout-index -f --stdin",
        ],
    )
    def test_the_forced_form_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, RuleID.GIT_CHECKOUT_FORCE)

    @pytest.mark.parametrize(
        "command", ["git checkout-index a.txt", "git checkout-index -a", "git checkout-index -u -a"]
    )
    def test_the_unforced_form_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """Without `-f` git refuses to overwrite an existing file."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, command, repo)


class TestPathsFedByAnotherCommandAreDenied:
    """N765: a runner that appends arguments supplies paths no reading of the text can see."""

    @pytest.mark.parametrize(
        "command",
        [
            f"echo a.txt | xargs git checkout {_OLD} --",
            f"echo a.txt | xargs git checkout {_OLD}",
            "echo a.txt | xargs git checkout --",
            "echo a.txt | xargs git checkout",
            "git ls-files -m | xargs git checkout",
            f"xargs git checkout {_OLD} -- < list.txt",
            f"xargs -a list.txt git checkout {_OLD} --",
            f"echo a.txt | xargs -0 -n1 git checkout {_OLD} --",
            f"echo a.txt | xargs -I{{}} git checkout {_OLD} {{}}",
            "echo main | xargs git checkout",
            f"echo a.txt | parallel git checkout {_OLD} --",
            f"find . -name a.txt -exec git checkout {_OLD} {{}} +",
            f"find . -name a.txt -exec git checkout {_OLD} -- {{}} ';'",
            f"echo a.txt | xargs sh -c 'git checkout {_OLD} \"$@\"' _",
            "echo a.txt | xargs sh -c 'git checkout \"$@\"' _",
            f"echo a.txt | git checkout {_OLD} --pathspec-from-file=-",
            f"echo a.txt | git checkout --pathspec-from-file=- {_OLD} --",
            f"echo a.txt | sudo xargs git checkout {_OLD} --",
            f"echo a.txt | some-runner git checkout {_OLD} --",
        ],
    )
    def test_a_fed_checkout_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        (repo / "list.txt").write_text("a.txt\n")
        _denied(handler, command, repo, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "echo a.txt | xargs git restore",
            "echo a.txt | xargs git restore --",
            "echo a.txt | xargs git restore --worktree",
            "xargs git restore < list.txt",
            "find . -name a.txt -exec git restore {} +",
            "echo a.txt | parallel git restore",
        ],
    )
    def test_a_fed_restore_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        (repo / "list.txt").write_text("a.txt\n")
        _denied(handler, command, repo, RuleID.GIT_RESTORE)

    def test_an_unfed_checkout_after_a_pipe_elsewhere_is_judged_on_its_own(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        """The pipe belongs to `git log`, not to the switch after `&&`."""
        _allowed(handler, "git log --oneline | grep x && git checkout side", repo)

    def test_a_fed_restore_beside_a_clean_index_listing_is_still_denied(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No git call can see stdin, so no proof is attempted: the shape alone denies."""
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        _denied(
            handler,
            f"echo old.txt | xargs git checkout {_OLD} --",
            repo,
            RuleID.GIT_CHECKOUT_DISCARD,
        )
        assert not any("diff" in call for call in calls)

    @pytest.mark.parametrize(
        "command",
        [
            f"echo x | git checkout {_OLD} --",
            "git checkout side < /dev/null",
            "echo y | git checkout side",
        ],
    )
    def test_stdin_into_a_plain_switch_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """Review of N764, minor 3: git checkout reads stdin only for `--pathspec-from-file=-`
        and `-p`, and both are options a switch does not use, so they are judged anyway."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        (repo / "list.txt").write_text("a.txt\n")
        _allowed(handler, command, repo)

    @pytest.mark.parametrize(
        "command",
        [
            "echo a.txt | xargs git restore --staged",
            "echo a.txt | xargs git restore -S",
            "find . -name a.txt -exec git restore --staged {} +",
        ],
    )
    def test_a_fed_staged_only_restore_is_allowed_as_the_unfed_one_is(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        """Review of N764, minor 4: `--staged` alone touches only the index."""
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, command, repo)

    @pytest.mark.parametrize(
        "command",
        [
            "echo a.txt | xargs git restore --staged --worktree",
            "echo a.txt | xargs git restore --staged --wor",
            "echo a.txt | xargs git restore -SW",
            "echo a.txt | xargs git restore -S -W",
        ],
    )
    def test_a_fed_restore_of_the_worktree_too_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, RuleID.GIT_RESTORE)


_BT = chr(96)


class TestReviewBlockerBacktickSubstitution:
    """Review of N764, blocker 1: a run inside backticks is judged as one inside `$( )` is."""

    @pytest.mark.parametrize(
        "command",
        [
            f": {_BT}git checkout a.txt{_BT}",
            f"echo {_BT}git checkout a.txt{_BT}",
            f"ls {_BT}git checkout {_OLD} a.txt{_BT}",
            f"{_BT}git checkout a.txt{_BT}",
            f'echo "{_BT}git checkout {_OLD} a.txt{_BT}"',
            f"x={_BT}git checkout a.txt{_BT}",
            f": {_BT}git checkout a.txt",
            ": $(git checkout a.txt)",
        ],
    )
    def test_a_substituted_path_checkout_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_substituted_fed_restore_is_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f": {_BT}echo a.txt | xargs git restore{_BT}", repo, RuleID.GIT_RESTORE)

    @pytest.mark.parametrize(
        "command",
        [
            f"git commit -q --allow-empty -m 'run {_BT}git checkout a.txt{_BT} first'",
            f"cat > notes.md <<'EOF'\nrun {_BT}git checkout a.txt{_BT} first\nEOF",
        ],
    )
    def test_a_backtick_in_text_bash_never_runs_is_not_judged(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        _allowed(handler, command, repo)


class TestReviewBlockerADirectoryMovingWrapper:
    """Review of N764, blocker 2: `env -C sub` runs git in `sub`, which the reading never saw."""

    @pytest.fixture
    def edited_inner(self, repo: Path) -> Path:
        (repo / "sub" / "inner.txt").write_text("tracked\n")
        _git(repo, "add", "sub/inner.txt")
        _git(repo, "commit", "-q", "-m", "inner")
        (repo / "sub" / "inner.txt").write_text("my unsaved edit\n")
        return repo

    @pytest.mark.parametrize(
        "command",
        [
            "env -C sub git checkout inner.txt",
            "env --chdir=sub git checkout inner.txt",
            "env --chdir sub git checkout inner.txt",
            "env -i -C sub git checkout inner.txt",
            "sudo -D sub git checkout inner.txt",
            "sudo --chdir=sub git checkout inner.txt",
            "env -C sub git restore inner.txt",
        ],
    )
    def test_the_moved_checkout_is_denied(
        self, handler: DestructiveGitHandler, edited_inner: Path, command: str
    ) -> None:
        assert _verdict(handler, command, edited_inner)[0] == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        ["env git checkout side", "env X=1 git checkout side", "nice -n 5 git checkout side"],
    )
    def test_a_wrapper_with_no_directory_option_still_switches(
        self, handler: DestructiveGitHandler, edited_inner: Path, command: str
    ) -> None:
        _allowed(handler, command, edited_inner)


class TestReviewMinorHarmlessSwitchesStayAllowed:
    """Review of N764, minor 3: switches main allowed must not be denied."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git -c advice.detachedHead=false checkout {_OLD}",
            "git -c color.ui=never checkout side",
            "GIT_LFS_SKIP_SMUDGE=1 git checkout side",
            "X=1 git checkout side",
            "LANG=C git checkout side",
            "git --no-pager checkout side",
            "git -P checkout side",
            "git --no-optional-locks checkout side",
            "git checkout --conflict=diff3 main",
            "git checkout --conflict diff3 main",
        ],
    )
    def test_the_switch_is_allowed(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, command, repo)

    @pytest.mark.parametrize(
        "command",
        [
            "git -c core.worktree=elsewhere checkout main",
            "git -c core.ignorecase=true checkout A.TXT",
            "git --icase-pathspecs checkout A.TXT",
            "GIT_ICASE_PATHSPECS=1 git checkout A.TXT",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.worktree GIT_CONFIG_VALUE_0=x git checkout main",
            "GIT_INDEX_FILE=other git checkout main",
            "HOME=elsewhere git checkout main",
            "git --conflict=diff3 checkout a.txt",
            "git checkout --conflict=diff3 a.txt",
        ],
    )
    def test_a_setting_that_can_change_the_reading_is_still_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        assert _verdict(handler, command, repo)[0] == Decision.DENY

    def test_a_switch_after_cd_into_the_repository_is_read_there(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "plain"
        outside.mkdir()
        _allowed(handler, f"cd {repo} && git checkout side", outside)
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, f"cd {repo} && git checkout a.txt", outside, RuleID.GIT_CHECKOUT_DISCARD)


class TestReviewMinorAbbreviatedLongOptions:
    """Review of N764, minor 5: git takes any unique prefix of a long option."""

    @pytest.mark.parametrize(
        ("command", "rule"),
        [
            ("git checkout-index -a --forc", RuleID.GIT_CHECKOUT_FORCE),
            ("git checkout-index -a --fo", RuleID.GIT_CHECKOUT_FORCE),
            ("git checkout-index -a --f", RuleID.GIT_CHECKOUT_FORCE),
            ("git checkout --forc side", RuleID.GIT_CHECKOUT_FORCE),
            ("git checkout --fo main", RuleID.GIT_CHECKOUT_FORCE),
            ("git restore --staged --wor a.txt", RuleID.GIT_RESTORE),
            ("git restore --staged --w a.txt", RuleID.GIT_RESTORE),
            ("git reset --har", RuleID.GIT_RESET_HARD),
            ("git reset --ha", RuleID.GIT_RESET_HARD),
            ("git clean --forc", RuleID.GIT_CLEAN_FORCE),
            ("git clean --fo -d", RuleID.GIT_CLEAN_FORCE),
            ("git switch --discard side", RuleID.GIT_SWITCH_FORCE),
            ("git switch --di side", RuleID.GIT_SWITCH_FORCE),
        ],
    )
    def test_the_abbreviation_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str, rule: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, rule)

    @pytest.mark.parametrize(
        "command",
        [
            "git reset --soft HEAD",
            "git clean -n",
            "git switch --detach side",
            "git restore --staged a.txt",
            "git checkout --quiet side",
        ],
    )
    def test_a_neighbouring_option_is_not_read_as_one(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _allowed(handler, command, repo)


class TestReviewMinorQuotingAndAliases:
    """Review of N764, minor 7: the cheap main gaps."""

    @pytest.mark.parametrize(
        ("command", "rule"),
        [
            ("git $'checkout' -- a.txt", RuleID.GIT_CHECKOUT_DISCARD),
            ("git $'checkout' a.txt", RuleID.GIT_CHECKOUT_DISCARD),
            ("git $'\\x63heckout' a.txt", RuleID.GIT_CHECKOUT_DISCARD),
            ("git $'reset' --hard", RuleID.GIT_RESET_HARD),
            ("git -c alias.co=checkout co a.txt", RuleID.GIT_DESTRUCTIVE_UNREADABLE),
            ("git -c 'alias.co=!git checkout' co a.txt", RuleID.GIT_DESTRUCTIVE_UNREADABLE),
            ("git -calias.co=checkout co a.txt", RuleID.GIT_DESTRUCTIVE_UNREADABLE),
            ("git --config-env=alias.co=CO co a.txt", RuleID.GIT_DESTRUCTIVE_UNREADABLE),
            (
                "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.co GIT_CONFIG_VALUE_0=checkout git co a",
                RuleID.GIT_DESTRUCTIVE_UNREADABLE,
            ),
        ],
    )
    def test_the_spelling_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str, rule: str
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        _denied(handler, command, repo, rule)

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -q --allow-empty -m $'two\\nlines'",
            "git log --oneline -1 --format=$'%h\\t%s'",
            "git config --get alias.co",
        ],
    )
    def test_ordinary_ansi_c_quoting_and_alias_reads_are_allowed(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        _allowed(handler, command, repo)


class TestReviewMinorASwitchOverIgnoredFiles:
    """Review of N764, minor 7: git overwrites an IGNORED file the target branch tracks."""

    @pytest.fixture
    def feat(self, repo: Path) -> Path:
        _git(repo, "checkout", "-q", "-b", "feat")
        (repo / "ign.txt").write_text("tracked on feat\n")
        (repo / "deep").mkdir()
        (repo / "deep" / "x.txt").write_text("tracked on feat\n")
        _git(repo, "add", "ign.txt", "deep/x.txt")
        _git(repo, "commit", "-q", "-m", "feat files")
        _git(repo, "checkout", "-q", "main")
        (repo / ".git" / "info" / "exclude").write_text("ign.txt\ndeep\n")
        return repo

    @pytest.mark.parametrize(
        "command", ["git checkout feat", "git checkout -m feat", "git checkout -b mine feat"]
    )
    def test_a_switch_that_would_overwrite_an_ignored_file_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        (feat / "ign.txt").write_text("ignored local work\n")
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_an_ignored_file_where_the_branch_has_a_directory_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        (feat / "deep").write_text("ignored local work\n")
        _denied(handler, "git checkout feat", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_the_previous_branch_is_read_the_same_way(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "checkout", "-q", "feat")
        _git(feat, "checkout", "-q", "main")
        (feat / "ign.txt").write_text("ignored local work\n")
        _denied(handler, "git checkout -", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_switch_with_nothing_local_in_the_way_is_allowed(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _allowed(handler, "git checkout feat", feat)
        _allowed(handler, "git checkout -", feat)

    def test_a_failed_comparison_denies(
        self, handler: DestructiveGitHandler, feat: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def diff_fails(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "diff" in args:
                return subprocess.CompletedProcess(["git", *args], 128, "", "fatal: broken")
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", diff_fails)
        _denied(handler, "git checkout feat", feat, RuleID.GIT_CHECKOUT_DISCARD)


class TestReviewMinorTheReadingIsBounded:
    """Review of N764, minor 6: repeated runs share one reading and one set of git calls."""

    def test_identical_switches_ask_git_once(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        _allowed(handler, "git checkout side", repo)
        one_switch = len(calls)
        calls.clear()
        _allowed(handler, " && ".join(["git checkout side"] * 50), repo)
        assert len(calls) == one_switch

    def test_matches_and_handle_share_one_reading(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        hook_input = _hook_input("git checkout v1 && echo a.txt | xargs git checkout side", repo)
        assert handler.matches(hook_input) is True
        reading = len(calls)
        assert reading > 0
        assert handler.handle(hook_input).decision == Decision.DENY
        assert len(calls) == reading

    def test_many_distinct_switches_are_judged_without_asking_git_for_each(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Past a small number of distinct operands the chain is judged (and denied)."""
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        command = " && ".join(f"git checkout b{index}" for index in range(400))
        _denied(handler, command, repo, RuleID.GIT_CHECKOUT_DISCARD)
        assert len(calls) <= 2 * destructive_git._MAX_SWITCH_READINGS
