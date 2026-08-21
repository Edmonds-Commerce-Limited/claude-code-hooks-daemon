"""GitHooksExecutableFixerHandler - auto-fix non-executable git hooks.

When git encounters a hook file under the repository hooks directory that lacks
the execute permission bit, it silently skips that hook and prints a hint:

    hint: The '.git/hooks/pre-push' hook was ignored because
          it's not set as executable.

A silently-skipped hook means a project's safety/quality git hooks become inert
without warning. This handler detects that hint in Bash command output and
automatically remediates it by making every (non-sample) hook file executable,
using least-privilege bits (execute is added only where read is already
granted).
"""

import stat
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.utils.git_repo import run_git

# Stable fragment of git's hint that a hook was skipped for lacking +x.
# Matched case-insensitively against combined stdout/stderr.
_WARNING_SIGNATURE = "not set as executable"

# Sub-fields of tool_response for a real Claude Code Bash event. The envelope
# field itself is HookInputField.TOOL_RESPONSE — it was duplicated privately here
# only because the shared constants module published the wrong name and not this
# one. Note a Bash tool_response carries NO exit_code, so nothing may read one.
_STDOUT_FIELD = "stdout"
_STDERR_FIELD = "stderr"

# git ARGUMENTS resolving the active hooks directory (worktree/submodule safe,
# honours core.hooksPath). The binary is not named here: `run_git` supplies it
# along with `-C <repo>`, the declined index lock and the timeout.
_GIT_HOOKS_PATH_ARGS = ("rev-parse", "--git-path", "hooks")

# Sample hooks are intentionally inert; git ignores any file ending in .sample.
_SAMPLE_SUFFIX = ".sample"

# Permission bit arithmetic (least privilege).
_OWNER_EXEC_BIT = 0o100  # S_IXUSR - "is this file executable by its owner?"
_READ_BITS_MASK = 0o444  # owner/group/other read bits
_READ_TO_EXEC_SHIFT = 2  # read bit -> execute bit (r=4, x=1; shift right by 2)


class GitHooksExecutableFixerHandler(Handler):
    """Detect git's "not set as executable" hint and fix the hooks automatically.

    Non-terminal: it remediates as a side effect and reports what it changed via
    advisory context. It never blocks the command.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GIT_HOOKS_EXECUTABLE_FIXER,
            priority=Priority.GIT_HOOKS_EXECUTABLE_FIXER,
            terminal=False,
            tags=[
                HandlerTag.GIT,
                HandlerTag.AUTOMATION,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Bash output that contains git's non-executable-hook hint."""
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH:
            return False
        return _WARNING_SIGNATURE in self._combined_output(hook_input).lower()

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Make non-executable git hook files executable; report what changed."""
        cwd = hook_input.get(HookInputField.CWD)

        # Resolve the active hooks directory via git itself (worktree/submodule
        # safe, honours core.hooksPath), through the bounded runner so the
        # optional index lock is declined and a timeout applies. run_git never
        # raises: an absent binary or a timeout arrives as a non-zero
        # returncode, which _parse_hooks_dir already treats as "no answer".
        repo = self._repo_root(cwd)
        if repo is None:
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    "git reported a hook is not set as executable, but no project "
                    "directory could be resolved for the event - no automatic fix "
                    "applied."
                ],
            )

        git_result = run_git(repo, *_GIT_HOOKS_PATH_ARGS)

        hooks_dir = self._parse_hooks_dir(git_result.returncode, git_result.stdout, cwd)
        if hooks_dir is None or not hooks_dir.is_dir():
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    "git reported a hook is not set as executable, but the hooks "
                    "directory could not be located - no automatic fix applied."
                ],
            )

        fixed = self._make_hooks_executable(hooks_dir)
        if not fixed:
            return HookResult(decision=Decision.ALLOW)

        listing = ", ".join(sorted(fixed))
        return HookResult(
            decision=Decision.ALLOW,
            context=[
                "🔧 Auto-fixed non-executable git hook(s) so they will no longer "
                f"be silently skipped: {listing} (in {hooks_dir})."
            ],
        )

    @staticmethod
    def _repo_root(cwd: str | None) -> Path | None:
        """The directory to run git in: the EVENT's cwd, or None.

        The event's cwd is the only correct source here. The warning this
        handler reacts to was emitted by a git command in a particular working
        tree, which may be a worktree or a submodule — exactly where
        ``--git-path`` earns its keep — so resolving anywhere else would fix
        the hooks of a different repository.

        That rules out a ``ProjectContext`` fallback, and the absence is
        deliberate rather than an omission: falling back to the project root
        would answer confidently for the WRONG tree, which is worse than
        declining. Returning None here is a resolved verdict ("the event did
        not say where"), not a swallowed error — the caller turns it into
        visible advisory text.

        What this replaces: the previous code passed ``cwd=None`` straight to
        ``subprocess.run``, which inherits the DAEMON's working directory —
        and that is ``/``, never the project (the git-scoping lesson of Plan
        00237). git then failed in a non-repository and the handler silently
        did nothing, which reads exactly like a repo with nothing to fix.
        """
        return Path(cwd) if cwd else None

    @staticmethod
    def _combined_output(hook_input: dict[str, Any]) -> str:
        """Return stdout+stderr from the Bash tool response as a single string."""
        tool_response = hook_input.get(HookInputField.TOOL_RESPONSE)
        if not isinstance(tool_response, dict):
            return ""
        stdout = tool_response.get(_STDOUT_FIELD) or ""
        stderr = tool_response.get(_STDERR_FIELD) or ""
        return f"{stdout}\n{stderr}"

    @staticmethod
    def _parse_hooks_dir(returncode: int, stdout: str, cwd: str | None) -> Path | None:
        """Parse ``git rev-parse --git-path hooks`` output into an absolute path.

        Returns None when git reported failure (not a repository) or produced no
        path. A relative path is resolved against the working directory.
        """
        if returncode != 0:
            return None

        raw = stdout.strip()
        if not raw:
            return None

        hooks_path = Path(raw)
        if not hooks_path.is_absolute() and cwd:
            hooks_path = Path(cwd) / hooks_path
        return hooks_path

    @staticmethod
    def _make_hooks_executable(hooks_dir: Path) -> list[str]:
        """Add execute bits to non-sample, non-executable hook files.

        Returns the names of files that were changed.
        """
        fixed: list[str] = []
        for entry in hooks_dir.iterdir():
            if not entry.is_file():
                continue
            if entry.name.endswith(_SAMPLE_SUFFIX):
                continue

            mode = stat.S_IMODE(entry.stat().st_mode)
            if mode & _OWNER_EXEC_BIT:
                continue  # already executable by owner - nothing to do

            # Least privilege: grant execute only where read is already granted.
            exec_bits = (mode & _READ_BITS_MASK) >> _READ_TO_EXEC_SHIFT
            entry.chmod(mode | exec_bits)
            fixed.append(entry.name)

        return fixed

    def get_claude_md(self) -> str | None:
        return (
            "## git_hooks_executable_fixer — auto-fixes non-executable git hooks\n\n"
            "When a git command prints `hint: The '...' hook was ignored because "
            "it's not set as executable`, this handler automatically `chmod +x`s "
            "every non-`.sample` file in the repository's hooks directory "
            "(resolved via `git rev-parse --git-path hooks`, so worktrees and "
            "`core.hooksPath` are handled). Execute bits are added with least "
            "privilege (only where read is already granted). It never blocks the "
            "command and reports which hooks it fixed via advisory context. "
            "`.sample` files and already-executable hooks are left untouched."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the git hooks executable fixer."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Detects git non-executable-hook hint",
                command=(
                    "echo \"hint: The '.git/hooks/pre-push' hook was ignored "
                    "because it's not set as executable.\""
                ),
                description=(
                    "Recognises git's non-executable-hook hint in Bash output and "
                    "reports remediation context"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"executable"],
                safety_notes="echo only prints text - no real hooks are modified",
                test_type=TestType.ADVISORY,
                requires_event="PostToolUse after a Bash command emitting the git hint",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
