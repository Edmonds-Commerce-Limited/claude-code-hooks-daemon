"""Tests for ProjectContainmentHandler (Plan 00333).

The premise: a write whose target is NAMED outside the repository root is
denied. Every other path rule in this daemon is expressed in repo-relative
coordinates and treats a failed absolute-to-relative conversion as *allow*, so
an out-of-root target escapes them all rather than violating any one of them.
This handler is the one place that owns containment.

Two boundaries are load-bearing and are asserted here rather than assumed:

- **Named targets only.** A PreToolUse hook receives a command string, not
  syscalls, so it cannot see a library's temp file and must not pretend to.
- **Writes only.** Blocking reads would break diagnosis and gain nothing
  durable.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.project_containment import (
    ProjectContainmentHandler,
)

_ROOT = Path("/repo")


@pytest.fixture(autouse=True)
def _project_root() -> Any:
    """Pin the repository root so the boundary under test is deterministic."""
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root"
    ) as mock:
        mock.return_value = _ROOT
        yield mock


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture()
def handler() -> ProjectContainmentHandler:
    return ProjectContainmentHandler()


def _write(file_path: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": "x"}}


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestHandlerIdentity:
    def test_display_name(self, handler: ProjectContainmentHandler) -> None:
        assert handler.name == "enforce-project-containment"

    def test_it_runs_before_every_repo_relative_path_rule(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """markdown_organization is 35; for an out-of-root path it has nothing
        to say, so containment must decide first."""
        assert handler.priority < 35

    def test_it_is_terminal(self, handler: ProjectContainmentHandler) -> None:
        assert handler.terminal is True

    def test_it_exposes_its_rule(self, handler: ProjectContainmentHandler) -> None:
        assert [rule.rule_id for rule in handler.get_rules()] == [
            RuleID.WRITE_OUTSIDE_PROJECT_ROOT
        ]


class TestTheWriteEditSurface:
    def test_an_absolute_path_outside_the_root_matches(
        self, handler: ProjectContainmentHandler
    ) -> None:
        assert handler.matches(_write("/tmp/notes.md")) is True

    def test_a_path_inside_the_root_does_not_match(
        self, handler: ProjectContainmentHandler
    ) -> None:
        assert handler.matches(_write("/repo/untracked/scratch/notes.md")) is False

    def test_the_root_itself_does_not_match(self, handler: ProjectContainmentHandler) -> None:
        assert handler.matches(_write("/repo/README.md")) is False

    def test_a_relative_path_never_matches(self, handler: ProjectContainmentHandler) -> None:
        """A relative path is resolved against the working directory, which the
        daemon cannot know. Guessing would attribute a write to the wrong file,
        and a wrong path is worse than no path."""
        assert handler.matches(_write("untracked/scratch/notes.md")) is False

    def test_a_sibling_checkout_matches(self, handler: ProjectContainmentHandler) -> None:
        """The premise is containment, not a /tmp blocklist."""
        assert handler.matches(_write("/repo-other/notes.md")) is True

    def test_a_path_that_merely_shares_a_prefix_matches(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """``/repo-backup`` starts with ``/repo`` as a STRING but is not under
        it as a PATH. A prefix test rather than a component test would let this
        through, which is how containment checks usually fail."""
        assert handler.matches(_write("/repo-backup/notes.md")) is True

    def test_an_edit_is_covered_too(self, handler: ProjectContainmentHandler) -> None:
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/tmp/notes.md",
                "old_string": "a",
                "new_string": "b",
            },
        }

        assert handler.matches(hook_input) is True

    def test_notebook_edit_is_covered(self, handler: ProjectContainmentHandler) -> None:
        """``get_file_path`` returns None for NotebookEdit, so relying on it
        alone would leave a third write route open."""
        hook_input = {
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "/tmp/analysis.ipynb", "new_source": "x"},
        }

        assert handler.matches(hook_input) is True


class TestTheBashSurface:
    @pytest.mark.parametrize(
        "command",
        [
            "echo hi > /tmp/out.txt",
            "echo hi >> /tmp/out.txt",
            "echo hi | tee /tmp/out.txt",
            "cp /repo/README.md /tmp/copy.md",
        ],
    )
    def test_a_named_out_of_root_write_target_matches(
        self, handler: ProjectContainmentHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "echo hi > /repo/untracked/scratch/out.txt",
            "grep -c pattern /tmp/whatever.log",
            "cat /tmp/whatever.log",
            'echo hi > "$OUT"',
        ],
    )
    def test_these_do_not_match(
        self, handler: ProjectContainmentHandler, command: str
    ) -> None:
        """In order: an in-root write, two reads, and a target the daemon
        cannot resolve without executing the command."""
        assert handler.matches(_bash(command)) is False


class TestDestinationFlagsAndPositionalTargets:
    """The shapes `get_bash_write_targets` does not resolve (Plan 00333 T4.5).

    That accessor's premise is "content this command AUTHORED", which is why
    Plan 00260 excluded `cp`/`mv` from the content linters: a copy relocates
    bytes it did not write, so blaming it would report a defect it did not
    introduce. Containment has the opposite premise — any path the command
    WRITES TO loses the file just as thoroughly whether it authored the bytes
    or moved them. Different premise, different target set, so this extraction
    is handler-local rather than a widening of shared infrastructure that 22
    other handlers depend on.
    """

    @pytest.mark.parametrize(
        ("label", "command"),
        [
            ("curl -o", "curl -sSL https://example.com/x -o /tmp/x.sh"),
            ("curl --output", "curl https://example.com/x --output /tmp/x.sh"),
            ("curl --output=", "curl https://example.com/x --output=/tmp/x.sh"),
            ("wget -O", "wget https://example.com/x -O /tmp/x.sh"),
            ("tar -cf", "tar -cf /tmp/a.tar src"),
            ("tar -c -f", "tar -c -f /tmp/a.tar src"),
            ("mkdir", "mkdir -p /tmp/newdir"),
            ("rsync", "rsync -a src/ /tmp/dest/"),
            ("scp", "scp local.txt /tmp/remote.txt"),
        ],
    )
    def test_an_out_of_root_destination_matches(
        self, handler: ProjectContainmentHandler, label: str, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True, f"{label} reached out-of-root unjudged"

    @pytest.mark.parametrize(
        ("label", "command"),
        [
            ("curl in-repo", "curl https://example.com/x -o /repo/untracked/scratch/x.sh"),
            ("tar in-repo", "tar -cf /repo/untracked/scratch/a.tar src"),
            ("mkdir in-repo", "mkdir -p /repo/untracked/scratch/sub"),
            ("rsync in-repo", "rsync -a src/ /repo/untracked/scratch/"),
        ],
    )
    def test_an_in_repo_destination_does_not_match(
        self, handler: ProjectContainmentHandler, label: str, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False


class TestOutputFlagsAreCommandKeyed:
    """`-o` does not mean "output file" everywhere, and guessing that it does
    is how a containment guard starts denying reads.

    `grep -o` means only-matching and takes NO argument, so a blind "token
    after -o" rule would read the PATTERN as a destination. With a pattern
    like `/tmp/foo` that is a denial of a command that writes nothing at all.
    """

    def test_grep_only_matching_is_not_a_destination(
        self, handler: ProjectContainmentHandler
    ) -> None:
        assert handler.matches(_bash("grep -o /tmp/foo somefile.txt")) is False

    def test_sort_output_flag_is_not_assumed(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """An unlisted command's `-o` is left alone rather than guessed at."""
        assert handler.matches(_bash("somecmd -o /tmp/out.txt")) is False

    def test_tar_without_a_create_flag_is_reading_not_writing(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """`tar -xf /tmp/a.tar` EXTRACTS FROM that path — it is a read."""
        assert handler.matches(_bash("tar -xf /tmp/a.tar")) is False


class TestNestedShells:
    """A quoted inner command is still a command."""

    @pytest.mark.parametrize(
        "command",
        [
            'sh -c "echo hi > /tmp/x"',
            'bash -c "echo hi > /tmp/x"',
            "sh -c 'curl https://example.com -o /tmp/x'",
        ],
    )
    def test_a_write_inside_a_nested_shell_matches(
        self, handler: ProjectContainmentHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is True

    def test_a_nested_shell_writing_in_repo_does_not_match(
        self, handler: ProjectContainmentHandler
    ) -> None:
        assert handler.matches(_bash('sh -c "echo hi > /repo/untracked/x"')) is False

    def test_an_interpreter_one_liner_is_out_of_scope(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """Deliberately NOT matched, and asserted so the limit is visible.

        Resolving what `python3 -c` writes means running it, which a PreToolUse
        hook must never do. The resident guidance states this rather than
        letting a clean command imply containment.
        """
        assert handler.matches(_bash("python3 -c \"open('/tmp/x','w')\"")) is False


class TestReadsAreNeverBlocked:
    @pytest.mark.parametrize("tool", ["Read", "Grep", "Glob"])
    def test_a_read_shaped_tool_never_matches(
        self, handler: ProjectContainmentHandler, tool: str
    ) -> None:
        hook_input = {"tool_name": tool, "tool_input": {"file_path": "/tmp/whatever.log"}}

        assert handler.matches(hook_input) is False


class TestTheDenial:
    def test_it_denies(self, handler: ProjectContainmentHandler) -> None:
        assert handler.handle(_write("/tmp/notes.md")).decision == Decision.DENY

    def test_it_names_the_offending_path(self, handler: ProjectContainmentHandler) -> None:
        result = handler.handle(_write("/tmp/notes.md"))

        assert result.reason is not None
        assert "/tmp/notes.md" in result.reason

    def test_it_names_the_sanctioned_location(self, handler: ProjectContainmentHandler) -> None:
        """A guard that blocks without naming the alternative just obstructs."""
        result = handler.handle(_write("/tmp/notes.md"))

        assert result.reason is not None
        assert "untracked/scratch" in result.reason

    def test_it_names_every_offending_bash_target(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """A command can write two files; reporting one sends the reader back
        for a second denial."""
        result = handler.handle(_bash("echo a > /tmp/one.txt && echo b > /tmp/two.txt"))

        assert result.reason is not None
        assert "/tmp/one.txt" in result.reason
        assert "/tmp/two.txt" in result.reason

    def test_a_non_matching_input_is_allowed(self, handler: ProjectContainmentHandler) -> None:
        """Defensive: handle() must not deny what matches() would not select."""
        assert handler.handle(_write("/repo/README.md")).decision == Decision.ALLOW


class TestTheAllowlist:
    def test_it_is_empty_by_default(self, handler: ProjectContainmentHandler) -> None:
        """A declared exemption is a decision; an assumed one is a hole."""
        assert handler.matches(_write("/tmp/notes.md")) is True

    def test_a_configured_path_is_permitted(self, handler: ProjectContainmentHandler) -> None:
        handler._allowed_external_paths = ["/tmp/blessed"]

        assert handler.matches(_write("/tmp/blessed/notes.md")) is False

    def test_an_exemption_does_not_leak_to_siblings(
        self, handler: ProjectContainmentHandler
    ) -> None:
        handler._allowed_external_paths = ["/tmp/blessed"]

        assert handler.matches(_write("/tmp/blessed-not-really/notes.md")) is True

    def test_an_unrelated_path_is_still_denied(
        self, handler: ProjectContainmentHandler
    ) -> None:
        handler._allowed_external_paths = ["/tmp/blessed"]

        assert handler.matches(_write("/tmp/elsewhere/notes.md")) is True


class TestTheClaudeHomeDirectoryIsAllowed:
    """Claude Code's own state directory is not scratch, and is not ephemeral.

    Owner ruling: writes to the Claude home directory can and should be
    allowed. Under ccy it is mapped back into the bind mount, so it has the
    durability property this guard exists to protect — the reason `/tmp` is
    refused does not apply to it.

    This does NOT re-open Claude auto-memory. `markdown_organization` blocks
    `~/.claude/projects/*/memory/*.md` on its own premise (untracked knowledge
    bypasses review), via a raw-string marker rule evaluated independently of
    this handler. The two rules are deliberately separate: containment asks
    "is it durable?", the memory rule asks "is it reviewable?", and a path can
    fail the second while passing the first.
    """

    def test_the_claude_home_directory_is_permitted(
        self, handler: ProjectContainmentHandler, tmp_path: Path
    ) -> None:
        claude_home = tmp_path / "claude-home"
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(claude_home)}):
            assert handler.matches(_write(str(claude_home / "settings.json"))) is False

    def test_a_nested_path_under_it_is_permitted(
        self, handler: ProjectContainmentHandler, tmp_path: Path
    ) -> None:
        claude_home = tmp_path / "claude-home"
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(claude_home)}):
            target = claude_home / "projects" / "slug" / "notes.md"
            assert handler.matches(_write(str(target))) is False

    def test_a_sibling_that_merely_shares_the_prefix_is_still_denied(
        self, handler: ProjectContainmentHandler, tmp_path: Path
    ) -> None:
        claude_home = tmp_path / "claude-home"
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(claude_home)}):
            assert handler.matches(_write(str(tmp_path / "claude-home-backup" / "x.md"))) is True

    def test_it_falls_back_to_the_default_location(
        self, handler: ProjectContainmentHandler
    ) -> None:
        """With no CLAUDE_CONFIG_DIR set, the documented default applies."""
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("CLAUDE_CONFIG_DIR", None)
            target = Path.home() / ".claude" / "settings.json"

            assert handler.matches(_write(str(target))) is False

    def test_the_allowance_can_be_switched_off(
        self, handler: ProjectContainmentHandler, tmp_path: Path
    ) -> None:
        """An environment that does NOT map the Claude home durably can refuse
        it: there, it is as ephemeral as any other container path."""
        claude_home = tmp_path / "claude-home"
        handler._allow_claude_home = False

        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(claude_home)}):
            assert handler.matches(_write(str(claude_home / "settings.json"))) is True

    def test_unrelated_out_of_root_paths_are_unaffected(
        self, handler: ProjectContainmentHandler, tmp_path: Path
    ) -> None:
        """Control: the allowance must not become a general amnesty."""
        with patch.dict("os.environ", {"CLAUDE_CONFIG_DIR": str(tmp_path / "claude-home")}):
            assert handler.matches(_write("/tmp/notes.md")) is True


class TestClaudeMdGuidance:
    def test_it_publishes_resident_guidance(self, handler: ProjectContainmentHandler) -> None:
        guidance = handler.get_claude_md()

        assert guidance is not None
        assert "untracked/scratch" in guidance
