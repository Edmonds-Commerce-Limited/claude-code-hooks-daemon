"""ReleaseMergeFreezeHandler - nothing else moves `main` while a release PR is open.

PROJECT-SPECIFIC (Plan 00476 Task 3.2, Design 4). The release goes through a
pull request whose CI run is the recorded QA result, and the tag must land on
the commit that run gated. If `main` moves in between, the gated commit is no
longer the one that gets tagged. So while `untracked/release-state.json`
records an open release pull request (its `ci.pr_number`), this handler denies
the commands that move `main` other than the release itself:

* `git merge` run on `main`;
* `git push` whose destination is `main` (including a bare push from `main`,
  `HEAD:main`, `:main`, `--all` and `--mirror`);
* `gh pr merge` of any pull request other than the recorded one, and a
  `gh pr merge` that names none (it would merge whatever the branch holds).

The state file is the trigger, exactly as for `release_blocker`: no file means
no release, and that path costs one stat and no JSON parse. A state file that
cannot be read, is not a JSON object, or carries a malformed `ci` record
FAILS CLOSED for those same commands, with a reason naming the file: a guard
that cannot read its evidence must not look like a guard with nothing to say.
A state file with no `ci` record means the pull request is not open yet, so
nothing is frozen.
"""

import json
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.utils.git_commit_parsing import (
    GitInvocation,
    SimpleCommand,
    simple_commands,
)
from claude_code_hooks_daemon.utils.git_invocation_directory import (
    invocation_directory,
    placement_problem,
)
from claude_code_hooks_daemon.utils.git_sync import current_branch
from claude_code_hooks_daemon.utils.shell_segmentation import peel_command_wrappers

RULE_ID: Final[str] = "R-RELEASE-MERGE-FREEZE"

_RULE: Final[Rule] = Rule(
    rule_id=RULE_ID,
    blocked="a `git merge` on main, a `git push` to main, or a `gh pr merge` of any pull request other than the open release pull request, while `untracked/release-state.json` records one",
    why="The tagged commit must be the commit CI gated; anything else that moves main invalidates the recorded CI run",
    fix="Finish the release (RELEASING.md), or abort it by deleting the state file, then retry",
    verbose=(
        "The release state file records the release pull request's CI run. Merges to main\n"
        "are frozen until the release is finished or aborted (RELEASING.md). An unreadable\n"
        "or malformed state file also denies these commands, naming the file."
    ),
)

_MAIN_BRANCH: Final[str] = "main"
_STATE_PARTS: Final[tuple[str, ...]] = ("untracked", "release-state.json")
_STATE_FILE_NAME: Final[str] = "release-state.json"
_CI_KEY: Final[str] = "ci"
_PR_KEY: Final[str] = "pr_number"
_HEADS_PREFIX: Final[str] = "refs/heads/"
_MOVING_WORDS: Final[tuple[str, ...]] = ("merge", "push")

_MERGE_NON_MERGE_FLAGS: Final[frozenset[str]] = frozenset({"--abort", "--continue", "--quit"})
_PUSH_VALUED_FLAGS: Final[frozenset[str]] = frozenset(
    {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
)
_PUSH_EVERY_BRANCH_FLAGS: Final[frozenset[str]] = frozenset({"--all", "--mirror"})
_GH_MERGE_VALUED_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-b",
        "--body",
        "-F",
        "--body-file",
        "-t",
        "--subject",
        "-A",
        "--author-email",
        "--match-head-commit",
        "-R",
        "--repo",
    }
)
_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _positionals(arguments: tuple[str, ...] | list[str], valued: frozenset[str]) -> list[str]:
    """The non-flag words of ``arguments``, skipping the value of a valued flag."""
    found: list[str] = []
    skip = False
    for word in arguments:
        if skip:
            skip = False
        elif word.startswith("-") and word != "-":
            skip = word in valued
        else:
            found.append(word)
    return found


def _on_main(run: GitInvocation, cwd: Path) -> bool:
    """Whether ``run`` executes on `main`; a run that cannot be placed counts as on it."""
    if placement_problem(run, cwd) is not None:
        return True
    return current_branch(invocation_directory(run, cwd)) == _MAIN_BRANCH


def _push_moves_main(run: GitInvocation, cwd: Path) -> bool:
    """Whether a `git push` updates `main` on the remote."""
    flags = {word for word in run.arguments if word.startswith("-")}
    if flags & _PUSH_EVERY_BRANCH_FLAGS:
        return True
    refspecs = _positionals(run.arguments, _PUSH_VALUED_FLAGS)[1:]
    if not refspecs:
        # Tags only, or the current branch under the default push rules.
        return "--tags" not in flags and _on_main(run, cwd)
    for refspec in refspecs:
        destination = refspec.lstrip("+").rsplit(":", 1)[-1].removeprefix(_HEADS_PREFIX)
        if destination == "HEAD":
            if _on_main(run, cwd):
                return True
        elif destination == _MAIN_BRANCH:
            return True
    return False


def _gh_pr_merge_is_foreign(words: tuple[str, ...], release_pr: int | None) -> bool:
    """Whether ``words`` run `gh pr merge` on anything but the release pull request."""
    start = 0
    while start < len(words) and _ASSIGNMENT.match(words[start]):
        start += 1
    _, offset = peel_command_wrappers(words[start:])
    argv = words[start + offset :]
    if len(argv) < 3 or argv[0].rsplit("/", 1)[-1] != "gh":
        return False
    rest = argv[1:]
    if "pr" not in rest or "merge" not in rest or rest.index("pr") > rest.index("merge"):
        return False
    named = _positionals(rest[rest.index("merge") + 1 :], _GH_MERGE_VALUED_FLAGS)
    if release_pr is None or not named:
        return True
    target = named[0]
    return target != str(release_pr) and not target.endswith(f"/pull/{release_pr}")


def _moves_main(step: SimpleCommand, cwd: Path, release_pr: int | None) -> bool:
    """Whether one simple command moves `main` other than as the release itself."""
    run = step.git
    if run is None:
        return _gh_pr_merge_is_foreign(step.words, release_pr)
    if run.subcommand == "merge":
        if _MERGE_NON_MERGE_FLAGS & set(run.arguments):
            return False
        return _on_main(run, cwd)
    if run.subcommand == "push":
        return _push_moves_main(run, cwd)
    return False


class ReleaseMergeFreezeHandler(Handler):
    """Deny commands that move `main` while a release pull request is open."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="release-merge-freeze",
            # 54 - a free slot in the workflow band, read off the priority-collision test.
            priority=54,
            terminal=True,
            tags=["project", "blocking", "workflow"],
        )

    @staticmethod
    def _project_root(hook_input: dict[str, Any]) -> Path:
        """The project whose state file counts: the daemon's root, else the event cwd."""
        try:
            from claude_code_hooks_daemon.core.project_context import ProjectContext

            return Path(str(ProjectContext.project_root()))
        except (RuntimeError, AttributeError):
            cwd = hook_input.get("cwd")
            if isinstance(cwd, str) and cwd:
                return Path(cwd)
            raise

    @staticmethod
    def _release_pr(state_path: Path) -> tuple[int | None, str | None]:
        """The open release pull request number, or why the state file cannot say.

        ``(None, None)`` means a readable state with no ``ci`` record: no pull
        request is open yet.
        """
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f"{state_path} cannot be read as JSON ({exc})"
        if not isinstance(state, dict):
            return None, f"{state_path} does not contain a JSON object"
        if _CI_KEY not in state:
            return None, None
        record = state[_CI_KEY]
        number = record.get(_PR_KEY) if isinstance(record, dict) else None
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            return None, f"{state_path} has a `{_CI_KEY}` record without a positive `{_PR_KEY}`"
        return number, None

    def _verdict(self, hook_input: dict[str, Any]) -> str | None:
        """The deny reason for this event, or None to allow it."""
        if hook_input.get("tool_name") != "Bash":
            return None
        tool_input = hook_input.get("tool_input", {})
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if not isinstance(command, str):
            return None
        if "gh" not in command and not any(word in command for word in _MOVING_WORDS):
            return None

        root = self._project_root(hook_input)
        state_path = root.joinpath(*_STATE_PARTS)
        if not state_path.exists():
            return None
        release_pr, problem = self._release_pr(state_path)
        if problem is None and release_pr is None:
            return None

        cwd_value = hook_input.get("cwd")
        cwd = Path(cwd_value) if isinstance(cwd_value, str) and cwd_value else root
        if not any(_moves_main(step, cwd, release_pr) for step in simple_commands(command)):
            return None
        return self._reason(release_pr, problem)

    @staticmethod
    def _reason(release_pr: int | None, problem: str | None) -> str:
        head = RuleFormatter().headline(_RULE)
        if problem is not None:
            return (
                f"{head}\n\nRELEASE MERGE FREEZE - {_STATE_FILE_NAME} is unusable\n\n"
                f"{problem}.\n\nWithout it the open release pull request is unknown, so this "
                "command, which moves main, is denied (fail closed). Repair the file "
                "(RELEASING.md, release state file), or abort the release by deleting it."
            )
        return (
            f"{head}\n\nRELEASE MERGE FREEZE - release pull request #{release_pr} is open\n\n"
            f"`untracked/{_STATE_FILE_NAME}` records pull request #{release_pr} as the open "
            "release. The commit that gets tagged must be the commit CI gated, and this "
            "command would move main.\n\n"
            f"Only `gh pr merge {release_pr}` may merge into main now. Finish the release, or "
            f"abort it per RELEASING.md (delete `untracked/{_STATE_FILE_NAME}` after closing "
            "the pull request), then retry."
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match a Bash command that moves `main` during an open release."""
        return self._verdict(hook_input) is not None

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny, naming the open release pull request and the way out."""
        return HookResult(decision=Decision.DENY, reason=self._verdict(hook_input))

    def get_rules(self) -> list[Rule]:
        """The rule behind this handler's deny."""
        return [_RULE]

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        # A deny needs a release state file, which an acceptance run must not create,
        # so only the quiet path is exercised here; the unit tests cover the denies.
        return [
            AcceptanceTest(
                title="Allow a merge command mentioned in an echo",
                command="echo 'git merge feature'",
                description="Mentioning a merge is not running one; no release is open here",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses echo - safe to execute",
                test_type=TestType.BLOCKING,
                dispatch_as_bash=True,
            ),
        ]
