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
            "git checkout --no-recurse-submodules side",
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
        # `here` touches nothing `main` holds, so a switch to it is a plain switch.
        _git(repo, "branch", "here")
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
        ["env git checkout here", "env X=1 git checkout here", "nice -n 5 git checkout here"],
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
            "git -c core.quotepath=off checkout side",
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
            ("git reset --merge HEAD~1", RuleID.GIT_RESET_HARD),
            ("git reset --mer HEAD~1", RuleID.GIT_RESET_HARD),
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
            # Owner ruling A6 (Plan 00483): `git reset --keep` is allowed.
            "git reset --keep HEAD~1",
            "git reset --kee HEAD~1",
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

    def test_a_tracked_parent_replaced_by_an_untracked_symlink_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, tmp_path: Path
    ) -> None:
        """Git removes the symlink to re-create `sub/c.txt` from a branch that modifies it."""
        _git(repo, "checkout", "-q", "-b", "edits")
        (repo / "sub" / "c.txt").write_text("edited on the branch\n")
        _git(repo, "commit", "-q", "-a", "-m", "edit c")
        _git(repo, "checkout", "-q", "main")
        (repo / "sub" / "c.txt").unlink()
        (repo / "sub").rmdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / "sub").symlink_to(elsewhere)
        _denied(handler, "git checkout edits", repo, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.fixture
    def reshaped(self, repo: Path) -> Path:
        """Branch `shape` turns the tracked file `a.txt` into a directory, and `sub` into a file."""
        _git(repo, "checkout", "-q", "-b", "shape")
        _git(repo, "rm", "-q", "-r", "a.txt", "sub")
        (repo / "a.txt").mkdir()
        (repo / "a.txt" / "x").write_text("now a directory\n")
        (repo / "sub").write_text("now a file\n")
        _git(repo, "add", "a.txt", "sub")
        _git(repo, "commit", "-q", "-m", "reshape")
        _git(repo, "checkout", "-q", "main")
        return repo

    def test_a_switch_that_reshapes_only_tracked_content_is_allowed(
        self, handler: DestructiveGitHandler, reshaped: Path
    ) -> None:
        """Git replaces the clean tracked `a.txt` and `sub/c.txt` itself; nothing local is lost."""
        _allowed(handler, "git checkout shape", reshaped)

    @pytest.mark.parametrize("kind", ["staged", "unstaged", "assume-unchanged", "staged-reverted"])
    def test_a_local_change_on_a_path_the_switch_removes_is_denied(
        self, handler: DestructiveGitHandler, reshaped: Path, kind: str
    ) -> None:
        """Review fuzz, seed 777 case 672: git dropped a staged edit the switch removed."""
        target = reshaped / "sub" / "c.txt"
        target.write_text("my local edit\n")
        if kind in ("staged", "staged-reverted"):
            _git(reshaped, "add", "sub/c.txt")
        if kind == "staged-reverted":
            target.write_text("content of sub/c.txt\n")
        if kind == "assume-unchanged":
            _git(reshaped, "update-index", "--assume-unchanged", "sub/c.txt")
        _denied(handler, "git checkout shape", reshaped, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_local_change_on_a_path_the_switch_leaves_alone_is_allowed(
        self, handler: DestructiveGitHandler, reshaped: Path
    ) -> None:
        """Git carries such a change across the switch; nothing is lost."""
        _git(reshaped, "checkout", "-q", "-b", "carry", "shape")
        _git(reshaped, "checkout", "-q", "main")
        (reshaped / "olddir").mkdir(exist_ok=True)
        (reshaped / "untouched.txt").write_text("tracked\n")
        _git(reshaped, "add", "untouched.txt")
        _git(reshaped, "commit", "-q", "-m", "untouched")
        _git(reshaped, "checkout", "-q", "-b", "next")
        (reshaped / "other.txt").write_text("on next\n")
        _git(reshaped, "add", "other.txt")
        _git(reshaped, "commit", "-q", "-m", "other")
        _git(reshaped, "checkout", "-q", "main")
        (reshaped / "untouched.txt").write_text("my local edit\n")
        _allowed(handler, "git checkout next", reshaped)

    def test_an_ignored_file_inside_a_tracked_directory_the_switch_replaces_is_denied(
        self, handler: DestructiveGitHandler, reshaped: Path
    ) -> None:
        (reshaped / ".git" / "info" / "exclude").write_text("sub/local.txt\n")
        (reshaped / "sub" / "local.txt").write_text("ignored local work\n")
        _denied(handler, "git checkout shape", reshaped, RuleID.GIT_CHECKOUT_DISCARD)

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


def _feat_tracks_an_ignored_file(repo: Path) -> Path:
    """`ign.txt` is tracked on `feat` AND on the merge base of `feat` and `main`; `main`
    stops tracking it, so on main it is an ignored local file. `origin` has the standard
    fetch refspec and a remote-tracking `remote-only` at `feat`."""
    (repo / "ign.txt").write_text("tracked on the base\n")
    _git(repo, "add", "ign.txt")
    _git(repo, "commit", "-q", "-m", "the base tracks ign.txt")
    _git(repo, "checkout", "-q", "-b", "feat")
    (repo / "feat-only.txt").write_text("on feat\n")
    _git(repo, "add", "feat-only.txt")
    _git(repo, "commit", "-q", "-m", "feat moves on")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "rm", "-q", "--cached", "ign.txt")
    (repo / "ign.txt").unlink()
    (repo / "main-only.txt").write_text("on main\n")
    _git(repo, "add", "main-only.txt")
    _git(repo, "commit", "-q", "-m", "main stops tracking ign.txt")
    (repo / ".git" / "info" / "exclude").write_text("ign.txt\n")
    _git(repo, "config", "remote.origin.url", "/nonexistent")
    _git(repo, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
    _git(repo, "update-ref", "refs/remotes/origin/remote-only", "feat")
    return repo


class TestSecondReviewTheSwitchTargetIsWhatCheckoutPicks:
    """Second review, blocker 1: the switch check must compare HEAD with the commit git
    actually switches to, not with whatever `rev-parse <operand>` picks."""

    @pytest.fixture
    def feat(self, repo: Path) -> Path:
        return _feat_tracks_an_ignored_file(repo)

    @staticmethod
    def _ignored_in_the_way(repo: Path) -> None:
        (repo / "ign.txt").write_text("ignored local work\n")

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout feat...main",
            "git checkout main...feat",
            "git checkout ...feat",
            "git checkout remote-only",
            "git checkout --guess remote-only",
        ],
    )
    def test_a_merge_base_or_remote_shortcut_switch_over_an_ignored_file_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        self._ignored_in_the_way(feat)
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command", ["git checkout amb", "git checkout -q amb", "git checkout -b nb amb"]
    )
    def test_a_branch_named_like_a_tag_is_the_target(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        """`rev-parse amb` picks the tag at HEAD; checkout switches to the branch at feat."""
        _git(feat, "tag", "amb", "HEAD")
        _git(feat, "branch", "amb", "feat")
        self._ignored_in_the_way(feat)
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize("command", ["git checkout feat...main", "git checkout remote-only"])
    def test_the_same_switches_with_nothing_in_the_way_are_allowed(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        _allowed(handler, command, feat)

    def test_a_name_both_a_branch_and_a_tag_is_denied_even_with_nothing_in_the_way(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        """Third review: an ambiguous name is denied outright (a deliberate over-deny, N771)."""
        _git(feat, "tag", "amb", "HEAD")
        _git(feat, "branch", "amb", "feat")
        _denied(handler, "git checkout amb", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_shortcut_name_two_remotes_hold_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "update-ref", "refs/remotes/upstream/remote-only", "main")
        _denied(handler, "git checkout remote-only", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_shortcut_name_that_is_also_a_path_is_a_restore_and_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        """Git takes the shortcut only when the operand names no path."""
        (feat / "remote-only").write_text("tracked file\n")
        _git(feat, "add", "remote-only")
        _git(feat, "commit", "-q", "-m", "a file named like the remote branch")
        (feat / "remote-only").write_text("my unsaved edit\n")
        _denied(handler, "git checkout remote-only", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_merge_base_with_no_single_answer_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "checkout", "-q", "--orphan", "lone")
        _git(feat, "commit", "-q", "--allow-empty", "-m", "unrelated root")
        _git(feat, "checkout", "-q", "main")
        _denied(handler, "git checkout lone...main", feat, RuleID.GIT_CHECKOUT_DISCARD)


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
        # Fourth review: a switch after another switch is judged against a HEAD the
        # first one moved, so the chain is denied, and still without asking git again.
        _denied(
            handler,
            " && ".join(["git checkout side"] * 50),
            repo,
            RuleID.GIT_CHECKOUT_DISCARD,
        )
        assert len(calls) <= one_switch

    def test_matches_and_handle_share_one_reading(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        # The first switch is read through git; the second is denied, as it runs after it.
        hook_input = _hook_input("git checkout v1 && git checkout side", repo)
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
        # A name that resolves to nothing costs four questions: which refs end in it, is
        # it a commit, is it an index path, what do the fetch refspecs map. The bound is
        # per reading, never per operand.
        assert len(calls) <= 4 * destructive_git._MAX_SWITCH_READINGS


class TestThirdReviewOnlyAPlainNameSwitches:
    """Third review: the allow-set is shrunk, not the check extended. A one-operand switch
    is allowed only for a plain ASCII ref spelling that resolves to one branch, tag or
    commit (or the one standard remote-tracking branch) and passes the switch check."""

    @pytest.fixture
    def feat(self, repo: Path) -> Path:
        return _feat_tracks_an_ignored_file(repo)

    @staticmethod
    def _ignored_in_the_way(repo: Path) -> None:
        (repo / "ign.txt").write_text("ignored local work\n")

    @pytest.mark.parametrize("name", ["fé", "a,b", "a=b", "a%b", "a#b"])
    @pytest.mark.parametrize("in_the_way", [True, False])
    def test_a_branch_with_a_name_outside_the_plain_spelling_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, name: str, in_the_way: bool
    ) -> None:
        """Blocker 1: such a name was never judged and lost `ign.txt`; now it is denied
        whatever the worktree holds (a deliberate over-deny, N771)."""
        _git(feat, "branch", name, "feat")
        if in_the_way:
            self._ignored_in_the_way(feat)
        _denied(handler, f"git checkout '{name}'", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_tag_with_a_non_ascii_name_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "tag", "tç", "feat")
        self._ignored_in_the_way(feat)
        _denied(handler, "git checkout tç", feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        ("refspec", "ref", "name"),
        [
            ("+refs/heads/*:refs/mirror/*", "refs/mirror/rem2", "rem2"),
            ("+refs/heads/*:refs/remotes/origin/x/*", "refs/remotes/origin/x/rem3", "rem3"),
            ("+refs/heads/*:refs/remotes/origin/pre-*", "refs/remotes/origin/pre-rem6", "rem6"),
        ],
    )
    @pytest.mark.parametrize("in_the_way", [True, False])
    def test_a_shortcut_through_a_non_standard_refspec_is_denied(
        self,
        handler: DestructiveGitHandler,
        feat: Path,
        refspec: str,
        ref: str,
        name: str,
        in_the_way: bool,
    ) -> None:
        """Blocker 2: git maps the name through each fetch refspec, which can point
        anywhere, so any refspec but `+refs/heads/*:refs/remotes/<remote>/*` denies."""
        _git(feat, "config", "remote.origin.fetch", refspec)
        _git(feat, "update-ref", ref, "feat")
        if in_the_way:
            self._ignored_in_the_way(feat)
        _denied(handler, f"git checkout {name}", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_name_resolved_through_a_ref_outside_the_three_namespaces_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "update-ref", "refs/rem5", "feat")
        _denied(handler, "git checkout rem5", feat, RuleID.GIT_CHECKOUT_DISCARD)
        _denied(handler, "git checkout refs/rem5", feat, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_shortcut_ref_under_a_remote_that_is_not_configured_is_denied(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        _git(feat, "update-ref", "refs/remotes/stale/rem7", "feat")
        _denied(handler, "git checkout rem7", feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout feat",
            "git checkout remote-only",
            "git checkout origin/remote-only",
            "git checkout refs/heads/feat",
            "git checkout heads/feat",
            "git checkout feat~0",
            "git checkout 'feat^{commit}'",
            "git checkout HEAD@{0}",
            "git checkout not-a-ref-and-not-a-path",
        ],
    )
    def test_plain_names_with_nothing_in_the_way_stay_allowed(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        _allowed(handler, command, feat)

    @pytest.mark.parametrize(
        "command",
        [
            "git checkout HEAD {a,sub/c}.txt",
            "git checkout HEAD {a.txt,}",
            "git checkout HEAD ~+/a.txt",
            "git checkout {HEAD,a.txt}",
            "git checkout HEAD -- {a,b}.txt",
            "git checkout HEAD -- ~+/a.txt",
            "git checkout HEAD -- p{1..2}.txt",
            "git checkout HEAD -- x=~/a.txt",
            "git checkout HEAD@{0,1} -- a.txt",
            "git restore {a,b}.txt",
        ],
    )
    @pytest.mark.parametrize("edited", [True, False])
    def test_a_shell_expansion_in_an_operand_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, command: str, edited: bool
    ) -> None:
        """Blocker 3: bash expands `{a,b}`, `{1..2}` and a leading `~` before git runs, so
        the word judged is not the word git gets; such a word is denied whether or not
        the expansion would reach a local edit."""
        if edited:
            (repo / "a.txt").write_text("my unsaved edit\n")
        verdict, _ = _verdict(handler, command, repo)
        assert verdict == Decision.DENY

    @pytest.mark.parametrize(
        "command", ["git checkout HEAD@{0} -- absent.txt", "git checkout HEAD -- a{b}.txt"]
    )
    def test_braces_that_bash_leaves_alone_are_judged_as_written(
        self, handler: DestructiveGitHandler, repo: Path, command: str
    ) -> None:
        _allowed(handler, command, repo)


def _superproject_whose_branch_moves_a_submodule(tmp_path: Path) -> Path:
    """`super` has submodule `sm` at a commit without `ign2.txt`; branch `smA` moves it to
    one that tracks it, and `sm/ign2.txt` is an ignored local file in the submodule."""
    source = tmp_path / "smsrc"
    _git(tmp_path, "init", "-q", "-b", "main", str(source))
    (source / "base.txt").write_text("base\n")
    _git(source, "add", "base.txt")
    _git(source, "commit", "-q", "-m", "c0")
    super_repo = tmp_path / "super"
    _git(tmp_path, "init", "-q", "-b", "main", str(super_repo))
    _git(
        super_repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "sm"
    )
    _git(super_repo, "commit", "-q", "-m", "add sm at c0")
    (source / "ign2.txt").write_text("tracked in c1\n")
    _git(source, "add", "ign2.txt")
    _git(source, "commit", "-q", "-m", "c1 tracks ign2.txt")
    submodule = super_repo / "sm"
    _git(submodule, "-c", "protocol.file.allow=always", "fetch", "-q", "origin")
    _git(super_repo, "checkout", "-q", "-b", "smA")
    _git(submodule, "checkout", "-q", "origin/main")
    _git(super_repo, "add", "sm")
    _git(super_repo, "commit", "-q", "-m", "smA moves sm to c1")
    _git(super_repo, "checkout", "-q", "main")
    _git(super_repo, "submodule", "-q", "update")
    exclude = Path(_git(submodule, "rev-parse", "--git-path", "info/exclude"))
    exclude = exclude if exclude.is_absolute() else submodule / exclude
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("ign2.txt\n")
    (submodule / "ign2.txt").write_text("ignored local work in the submodule\n")
    return super_repo


class TestThirdReviewSubmoduleRecursion:
    """Third review, minor 1: a recursing switch writes inside a submodule, which the
    switch check never reads, so recursion is denied when the switch moves a gitlink."""

    @pytest.fixture
    def super_repo(self, tmp_path: Path) -> Path:
        return _superproject_whose_branch_moves_a_submodule(tmp_path)

    def test_the_recurse_option_is_denied(
        self, handler: DestructiveGitHandler, super_repo: Path
    ) -> None:
        _denied(
            handler,
            "git checkout --recurse-submodules smA",
            super_repo,
            RuleID.GIT_CHECKOUT_DISCARD,
        )

    def test_recursion_switched_on_in_config_is_denied(
        self, handler: DestructiveGitHandler, super_repo: Path
    ) -> None:
        _git(super_repo, "config", "submodule.recurse", "true")
        _denied(handler, "git checkout smA", super_repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_without_recursion_the_submodule_is_not_touched_and_the_switch_is_allowed(
        self, handler: DestructiveGitHandler, super_repo: Path
    ) -> None:
        _allowed(handler, "git checkout smA", super_repo)
        _allowed(handler, "git checkout --no-recurse-submodules smA", super_repo)


class TestThirdReviewManyPathsAreReadInBatches:
    """Third review, minor 2: a long path list is read in a few batched git calls."""

    def test_two_thousand_absent_paths_take_a_bounded_number_of_git_calls(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        command = "git checkout v1 " + " ".join(f"p{index}.txt" for index in range(2000))
        _allowed(handler, command, repo)
        assert len(calls) <= 40

    def test_a_present_edited_file_among_many_is_still_denied(
        self, handler: DestructiveGitHandler, repo: Path
    ) -> None:
        (repo / "a.txt").write_text("my unsaved edit\n")
        names = [f"p{index}.txt" for index in range(600)] + ["a.txt"]
        _denied(handler, "git checkout v1 " + " ".join(names), repo, RuleID.GIT_CHECKOUT_DISCARD)


class TestFourthReviewAnEarlierStatementCanMoveTheTarget:
    """Fourth review, blocker 1: a switch is read against the repository as it is BEFORE
    the command runs, so a switch after a statement that may change refs, HEAD, config
    or the environment is denied (fail closed)."""

    @pytest.fixture
    def feat(self, repo: Path) -> Path:
        return _feat_tracks_an_ignored_file(repo)

    @pytest.mark.parametrize(
        "command",
        [
            "git fetch -q origin && git checkout newb",
            "git fetch -q && git checkout newb",
            "git pull -q origin feat:newb2 ; git checkout newb2",
            "git branch topic feat && git checkout topic",
            "git branch -f feat2 feat && git checkout feat2",
            "git tag tt feat && git checkout tt",
            "git tag newb feat; git checkout newb",
            "git update-ref refs/remotes/origin/newb feat && git checkout newb",
            "git checkout feat && git checkout HEAD~1",
            "git checkout feat; git checkout HEAD^",
            "git config submodule.recurse true && git checkout main",
            "export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=submodule.recurse"
            " GIT_CONFIG_VALUE_0=true; git checkout main",
            "export GIT_CONFIG_PARAMETERS=\"'submodule.recurse'='true'\"; git checkout main",
            "GIT_DIR=elsewhere; git checkout main",
            "export HOME=/elsewhere; git checkout main",
            "declare -x XDG_CONFIG_HOME=/elsewhere; git checkout main",
            "make && git checkout main",
            "./setup.sh && git checkout main",
            "git log > out.log && git checkout main",
            "git checkout main & git fetch -q",
            "git fetch -q & git checkout main",
        ],
    )
    def test_a_switch_after_a_statement_that_may_change_state_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "git status && git checkout main",
            "git log --oneline -1 && git checkout main",
            "git diff --stat; git checkout main",
            "git branch --show-current && git checkout main",
            "git branch && git checkout main",
            "git status > /dev/null && git checkout main",
            "echo switching && git checkout main",
            "cd sub && git checkout main",
            "X=1; git checkout main",
            "export FOO=1; git checkout main",
            "git checkout main && git log --oneline -1",
            "git checkout main && git fetch -q",
        ],
    )
    def test_a_switch_after_read_only_statements_is_still_judged_and_allowed(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        """Nothing in the way and nothing before it that can move refs, HEAD or config."""
        _git(feat, "checkout", "-q", "feat")
        _allowed(handler, command, feat)

    def test_a_read_only_statement_does_not_hide_an_ignored_file_in_the_way(
        self, handler: DestructiveGitHandler, feat: Path
    ) -> None:
        (feat / "ign.txt").write_text("ignored local work\n")
        _denied(handler, "git status && git checkout feat", feat, RuleID.GIT_CHECKOUT_DISCARD)


class TestFourthReviewSubmoduleRecursionSetEarlier:
    @pytest.fixture
    def super_repo(self, tmp_path: Path) -> Path:
        return _superproject_whose_branch_moves_a_submodule(tmp_path)

    def test_recursion_switched_on_by_an_earlier_statement_is_denied(
        self, handler: DestructiveGitHandler, super_repo: Path
    ) -> None:
        _denied(
            handler,
            "git config submodule.recurse true && git checkout smA",
            super_repo,
            RuleID.GIT_CHECKOUT_DISCARD,
        )


class TestFourthReviewMinorOneAWideSwitchIsReadInFewCalls:
    """Fourth review, minor 1: a switch across thousands of paths asks git in a few calls,
    chunked by path count and by bytes of path."""

    def test_chunks_split_on_count_and_on_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(destructive_git, "_PATHS_PER_LISTING", 3)
        monkeypatch.setattr(destructive_git, "_PATH_BYTES_PER_LISTING", 10)
        assert destructive_git._chunk_bounds([]) == []
        assert destructive_git._chunk_bounds(["a", "b", "c", "d"]) == [(0, 3), (3, 4)]
        assert destructive_git._chunk_bounds(["aaaa", "bbbb", "cc"]) == [(0, 2), (2, 3)]
        assert destructive_git._chunk_bounds(["x" * 50, "y"]) == [(0, 1), (1, 2)]

    @staticmethod
    def _wide_branch(repo: Path, count: int) -> None:
        """Branch `wide` adds `count` files under `wide/`; main is checked out again."""
        _git(repo, "checkout", "-q", "-b", "wide")
        wide = repo / "wide"
        wide.mkdir()
        for index in range(count):
            (wide / f"p{index}.txt").write_text(f"{index}\n")
        _git(repo, "add", "wide")
        _git(repo, "commit", "-q", "-m", f"wide adds {count} files")
        _git(repo, "checkout", "-q", "main")

    @pytest.mark.parametrize("change", ["unstaged", "staged", "skip-worktree"])
    def test_a_local_change_among_many_touched_paths_is_denied(
        self, handler: DestructiveGitHandler, repo: Path, change: str
    ) -> None:
        """Past the named-pathspec limit the whole-tree listing must still see it."""
        self._wide_branch(repo, destructive_git._NAMED_PATHSPECS_LIMIT + 36)
        _git(repo, "checkout", "-q", "wide")
        edited = repo / "wide" / "p7.txt"
        if change == "skip-worktree":
            _git(repo, "update-index", "--skip-worktree", "wide/p7.txt")
        edited.write_text("my local edit\n")
        if change == "staged":
            _git(repo, "add", "wide/p7.txt")
        _denied(handler, "git checkout main", repo, RuleID.GIT_CHECKOUT_DISCARD)

    def test_a_switch_adding_two_thousand_paths_takes_a_few_git_calls(
        self, handler: DestructiveGitHandler, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._wide_branch(repo, 2000)
        calls: list[tuple[str, ...]] = []

        def recording(cwd: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return run_git(cwd, *args, **kwargs)

        monkeypatch.setattr(destructive_git, "run_git", recording)
        _allowed(handler, "git checkout wide", repo)
        assert len(calls) <= 10


class TestFifthReviewHiddenStatementsBeforeASwitch:
    """Fifth review, blocker 1 and minors: a statement can run unseen inside a quoted
    command substitution, a process substitution or a here-string, and the parse keeps
    it inside one word (or loses it), so any of those in the command makes a switch's
    reading stale. A backgrounded or piped compound runs beside everything after it."""

    @pytest.fixture
    def feat(self, repo: Path) -> Path:
        return _feat_tracks_an_ignored_file(repo)

    @pytest.mark.parametrize(
        "command",
        [
            'echo "$(git branch topic feat)"; git checkout -q topic',
            'x="$(git branch topic feat)"; git checkout -q topic',
            f'echo "{_BT}git branch topic feat{_BT}"; git checkout -q topic',
            'test -z "$(git tag tt feat)" && git checkout -q tt',
            '[ -z "$(git fetch -q origin 2>&1)" ] && git checkout -q newb',
            'git status "$(git branch topic feat)"; git checkout -q topic',
            "cat <(git branch topic feat) >/dev/null; git checkout -q topic",
            "grep -q x <(git branch topic feat); git checkout -q topic",
            "cat < <(git branch topic feat); git checkout -q topic",
            'cat <<< "$(git branch topic feat)"; git checkout -q topic',
            'head -n1 <<< "$(git branch topic feat)"; git checkout -q topic',
            'echo "$(git config submodule.recurse true)"; git checkout -q main',
            "echo ok > >(git branch topic feat); git checkout -q topic",
        ],
    )
    def test_a_switch_after_a_hidden_statement_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        self._in_the_way(feat)
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "( true; git checkout -q topic; git status ) & git branch topic feat; wait",
            "{ true; git checkout -q topic; git status; } & git branch topic feat; wait",
            "git branch topic feat | ( true; git checkout -q topic; git status )",
        ],
    )
    def test_a_switch_in_a_backgrounded_or_piped_compound_is_denied(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        self._in_the_way(feat)
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "git log -1 --format=%H --output=.git/refs/heads/topic feat && git checkout -q topic",
            "git diff --outp=diff.txt && git checkout -q main",
            "git show --output x.txt HEAD && git checkout -q main",
            "git grep -Ocat main && git checkout -q main",
            "git grep --open-files-in-pager=cat main && git checkout -q main",
        ],
    )
    def test_a_reader_that_writes_a_file_or_runs_a_pager_counts_as_a_change(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        _denied(handler, command, feat, RuleID.GIT_CHECKOUT_DISCARD)

    @pytest.mark.parametrize(
        "command",
        [
            "git status && git checkout main",
            "git log --oneline | grep x && git checkout main",
            "git diff --stat --output-indicator-new=+ && git checkout main",
        ],
    )
    def test_plain_readers_before_a_switch_stay_allowed(
        self, handler: DestructiveGitHandler, feat: Path, command: str
    ) -> None:
        _git(feat, "checkout", "-q", "feat")
        _allowed(handler, command, feat)

    @staticmethod
    def _in_the_way(repo: Path) -> None:
        (repo / "ign.txt").write_text("ignored local work\n")
