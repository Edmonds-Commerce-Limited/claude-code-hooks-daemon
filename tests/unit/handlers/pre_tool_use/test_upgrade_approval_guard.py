"""Tests for UpgradeApprovalGuardHandler (Plan 00376, review finding MAJOR 4).

The pre-deploy upgrade gate lets the project OWNER approve a breaking upgrade
via a one-shot marker file written by ``hooks-daemon approve-upgrade <version>
--from <previous>`` (a command that requires a TTY and a typed confirmation
phrase). An AGENT must never be able to grant that approval itself, by any of
the routes the review found:

1. running the ``approve-upgrade`` CLI subcommand (or the standalone gate's
   ``approve`` subcommand) itself;
2. writing/touching the marker file under an ``upgrade-approvals/`` directory
   by any Bash route;
3. authoring the marker directly with Write/Edit/NotebookEdit;
4. exporting/assigning ``HOOKS_DAEMON_UPGRADE_HANDOFF``, the variable Layer 1
   names its one-shot handoff file in, which impersonates Layer 1;
5. forging a venv's ``.daemon-version`` stamp, by any of the routes in (2)
   or via Write/Edit.

Mentioning any of this inside a git commit message, non-executing echo/printf
prose, a grep search, or a quoted-delimiter heredoc body must NOT be denied —
those are the same inert-text exemptions the rest of this codebase's Bash
guards already grant.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.upgrade_approval_guard import (
    UpgradeApprovalGuardHandler,
)

AGENT_RULE_ID = RuleID.UPGRADE_APPROVAL_AGENT_ACTION
ENV_RULE_ID = RuleID.UPGRADE_APPROVAL_ENV_BYPASS


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """The DisclosureTracker is a process-wide singleton (Plan 00116, Decision G)."""
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str, cwd: str | None = None) -> dict[str, Any]:
    hook_input: dict[str, Any] = {"tool_name": "Bash", "tool_input": {"command": command}}
    if cwd is not None:
        hook_input["cwd"] = cwd
    return hook_input


def _write(file_path: str, content: str = "") -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


def _edit(file_path: str, new_string: str = "x") -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": "", "new_string": new_string},
    }


def _notebook_edit(notebook_path: str) -> dict[str, Any]:
    return {
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": notebook_path, "new_source": "x"},
    }


@pytest.fixture
def handler() -> UpgradeApprovalGuardHandler:
    return UpgradeApprovalGuardHandler()


class TestInit:
    def test_priority_is_20(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.priority == 20

    def test_terminal(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.terminal is True


class TestApproveUpgradeCommand:
    """Item 1: running `approve-upgrade` (or the standalone `approve`) itself."""

    @pytest.mark.parametrize(
        "command",
        [
            ".claude/hooks-daemon/bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0",
            "bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0",
            "hooks-daemon approve-upgrade 4.0.0 --from 3.66.0",
            "python -m claude_code_hooks_daemon.daemon.cli approve-upgrade 4.0.0 --from 3.66.0",
            "python3 -m claude_code_hooks_daemon.daemon.cli approve-upgrade 4.0.0 --from 3.66.0",
            "python3 /workspace/src/claude_code_hooks_daemon/install/"
            "upgrade_gate_standalone.py approve --to 4.0.0 --from 3.66.0",
        ],
    )
    def test_denies_running_the_approval_command(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    def test_denies_when_chained_after_another_command(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        hook_input = _bash("echo hi && bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0")
        assert handler.matches(hook_input) is True

    def test_allows_ordinary_hooks_daemon_commands(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        assert handler.matches(_bash("bin/hooks-daemon status")) is False
        assert handler.matches(_bash("bin/hooks-daemon restart")) is False

    def test_allows_git_commit_message_mentioning_it(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        command = (
            "git commit -m 'document the bin/hooks-daemon approve-upgrade 4.0.0 "
            "--from 3.66.0 flow'"
        )
        assert handler.matches(_bash(command)) is False

    def test_allows_echo_mentioning_it(self, handler: UpgradeApprovalGuardHandler) -> None:
        command = "echo 'run: bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0'"
        assert handler.matches(_bash(command)) is False

    def test_allows_printf_mentioning_it(self, handler: UpgradeApprovalGuardHandler) -> None:
        command = "printf 'run: bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0\\n'"
        assert handler.matches(_bash(command)) is False

    def test_allows_grep_for_it(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("grep approve-upgrade docs/UPGRADING.md")) is False

    def test_allows_quoted_heredoc_body_written_to_file(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        command = (
            "cat > untracked/scratch/notes.md <<'EOF'\n"
            "run: bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0\n"
            "EOF\n"
        )
        assert handler.matches(_bash(command)) is False

    def test_echo_with_live_substitution_is_still_denied(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        """An echo whose argument really EXECUTES something is not exempt."""
        command = 'echo "$(bin/hooks-daemon approve-upgrade 4.0.0 --from 3.66.0)"'
        assert handler.matches(_bash(command)) is True


class TestApprovalMarkerWrites:
    """Item 2: writing/touching the marker under upgrade-approvals/ via Bash."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo approved > untracked/upgrade-approvals/4.0.0.approved",
            "echo approved >> untracked/upgrade-approvals/4.0.0.approved",
            "printf approved | tee untracked/upgrade-approvals/4.0.0.approved",
            "touch untracked/upgrade-approvals/4.0.0.approved",
            "cp /tmp/marker untracked/upgrade-approvals/4.0.0.approved",
            "mv /tmp/marker untracked/upgrade-approvals/4.0.0.approved",
            "mkdir -p untracked/upgrade-approvals",
        ],
    )
    def test_denies_writing_under_the_approvals_directory(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            "ls untracked/upgrade-approvals",
            "cat untracked/upgrade-approvals/4.0.0.approved",
            "stat untracked/upgrade-approvals/4.0.0.approved",
            "grep 4.0.0 untracked/upgrade-approvals/4.0.0.approved",
            "find untracked/upgrade-approvals -print",
            "test -f untracked/upgrade-approvals/4.0.0.approved",
        ],
    )
    def test_allows_read_only_access(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False

    def test_allows_unrelated_mkdir(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("mkdir -p untracked/scratch")) is False


class TestApprovalMarkerFileTool:
    """Item 3: Write/Edit/NotebookEdit authoring the marker directly."""

    def test_denies_write(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = _write("untracked/upgrade-approvals/4.0.0.approved", "forged\n")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    def test_denies_edit(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = _edit("untracked/upgrade-approvals/4.0.0.approved")
        assert handler.matches(hook_input) is True

    def test_denies_notebook_edit(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = _notebook_edit("untracked/upgrade-approvals/notes.ipynb")
        assert handler.matches(hook_input) is True

    def test_allows_write_elsewhere(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = _write("untracked/scratch/notes.md", "hello\n")
        assert handler.matches(hook_input) is False


class TestEnvVarBypass:
    """Item 4: HOOKS_DAEMON_UPGRADE_HANDOFF."""

    @pytest.mark.parametrize(
        "command",
        [
            "HOOKS_DAEMON_UPGRADE_HANDOFF=/tmp/x bash scripts/upgrade_version.sh --project-root /workspace",
            "export HOOKS_DAEMON_UPGRADE_HANDOFF=/tmp/x",
            "env HOOKS_DAEMON_UPGRADE_HANDOFF=/tmp/x bash scripts/upgrade_version.sh",
            "declare -x HOOKS_DAEMON_UPGRADE_HANDOFF=/tmp/x",
        ],
    )
    def test_denies_setting_the_bypass_vars(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            'echo "$HOOKS_DAEMON_UPGRADE_HANDOFF"',
            "grep HOOKS_DAEMON_UPGRADE_HANDOFF scripts/upgrade_version.sh",
            'printf "%s\\n" "${HOOKS_DAEMON_UPGRADE_HANDOFF}"',
        ],
    )
    def test_allows_merely_reading_the_vars(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False


class TestUpgradeSteeringVariables:
    """An upgrade run with a variable that picks its interpreter, venv or code.

    Review of e27bd73f: `HOOKS_DAEMON_PYTHON` pointed the gate at a crafted
    interpreter that printed `gate-verdict=proceed`. Layer 2 no longer takes
    the gate's interpreter or the installed version from these, and the guard
    denies an agent setting them on an upgrade invocation.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "HOOKS_DAEMON_PYTHON=/tmp/fake bash scripts/upgrade.sh --project-root .",
            "HOOKS_DAEMON_VENV_PATH=/tmp/forged bash .claude/hooks-daemon/scripts/upgrade.sh"
            " --project-root .",
            "PATH=/tmp/fake:$PATH bash .claude/skills/hooks-daemon/scripts/upgrade.sh v4.0.0",
            "HOSTNAME=other bash scripts/upgrade_version.sh /p /p/.claude/hooks-daemon v4.0.0",
            "env HOOKS_DAEMON_CLONE_URL=/tmp/evil bash /tmp/upgrade.sh --project-root .",
            "HOOKS_DAEMON_UPGRADE_BASE_URL=file:///tmp/evil bash .claude/skills/hooks-daemon/"
            "scripts/upgrade.sh",
            "export HOOKS_DAEMON_PYTHON=/tmp/fake && bash scripts/upgrade.sh --project-root .",
            "UPGRADE_FLAGS=--skip-reading-confirmation=abc bash scripts/upgrade_version.sh a b c",
            "HOOKS_DAEMON_PYTHON=/tmp/fake python3 src/claude_code_hooks_daemon/install/"
            "upgrade_gate_standalone.py --to 4.0.0",
            "HOOKS_DAEMON_UPGRADE_SECOND_PASS=1 bash scripts/upgrade_version.sh a b c",
            "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION=v4.0.0 bash scripts/upgrade_version.sh a b c",
            "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.excludesFile bash scripts/upgrade.sh",
            "GIT_DIR=/tmp/other bash scripts/upgrade.sh --project-root .",
        ],
    )
    def test_denies_steering_an_upgrade(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            "bash scripts/upgrade.sh --project-root . v4.0.0",
            "HOOKS_DAEMON_PYTHON=/usr/bin/python3.12 bash scripts/install.sh --project-root .",
            "PATH=/opt/bin:$PATH make test",
            "grep HOOKS_DAEMON_PYTHON scripts/upgrade.sh",
            "echo 'HOOKS_DAEMON_PYTHON=/x bash scripts/upgrade.sh'",
        ],
    )
    def test_allows_other_uses(self, handler: UpgradeApprovalGuardHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False, command


class TestVenvVersionStampForgery:
    """Item 5: forging a venv's .daemon-version stamp."""

    @pytest.mark.parametrize(
        "command",
        [
            "echo 4.0.0 > untracked/venv-abc123/.daemon-version",
            "touch untracked/venv-abc123/.daemon-version",
            "cp /tmp/stamp untracked/venv-abc123/.daemon-version",
        ],
    )
    def test_denies_bash_write_to_the_stamp(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    def test_denies_write_tool(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = _write("untracked/venv-abc123/.daemon-version", "4.0.0\n")
        assert handler.matches(hook_input) is True

    def test_allows_reading_the_stamp(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("cat untracked/venv-abc123/.daemon-version")) is False

    def test_allows_unrelated_daemon_version_mention(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        """A `.daemon-version` NOT under `untracked/venv*/` is out of scope."""
        assert handler.matches(_bash("cat some/other/.daemon-version")) is False
        assert handler.matches(_write("some/other/.daemon-version", "x")) is False


class TestNonMatchingCalls:
    def test_allows_non_bash_non_file_tool(self, handler: UpgradeApprovalGuardHandler) -> None:
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "README.md"}}
        assert handler.matches(hook_input) is False

    def test_allows_empty_bash_command(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("")) is False

    def test_allows_ordinary_bash_command(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("git status")) is False


class TestGetRules:
    def test_returns_two_rules(self, handler: UpgradeApprovalGuardHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 2
        assert all(isinstance(rule, Rule) for rule in rules)
        assert {rule.rule_id for rule in rules} == {AGENT_RULE_ID, ENV_RULE_ID}


class TestDenyMessageContent:
    def test_agent_action_message_names_the_owner_and_the_remedy(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        result = handler.handle(_bash("touch untracked/upgrade-approvals/4.0.0.approved"))
        assert result.reason is not None
        assert "owner" in result.reason.lower()
        assert "approve-upgrade" in result.reason
        assert "TTY" in result.reason or "terminal" in result.reason.lower()

    def test_env_bypass_message_names_layer1_as_the_only_route(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        result = handler.handle(_bash("export HOOKS_DAEMON_UPGRADE_HANDOFF=/tmp/x"))
        assert result.reason is not None
        assert "Layer 1" in result.reason
        assert "scripts/upgrade.sh" in result.reason
