"""Plan 00477 Phase 3 - an unprovisioned fresh clone is detected and says so loudly.

A fresh clone of a client project carries the tracked assets (hook forwarders,
``init.sh``, ``hooks-daemon.yaml``, ``provision.sh``) but no daemon clone. The
hook path runs in bash with nothing from the daemon's venv, so the forwarders
are driven for real, under ``bash``, against a copy of ``init.sh``.

What the human and the agent must get:

* SessionStart and every UserPromptSubmit: a ``systemMessage`` (shown to the
  human) plus ``additionalContext`` (seen by the agent), naming the expected
  version and ``bash .claude/provision.sh``.
* The status line: one text line naming the same command.
* ``daemon.unprovisioned_mode`` (default ``warn``): under ``block`` PreToolUse
  denies, except the provision command alone and the hooks-daemon provision
  skill call.
* ``ci_enabled: true`` keeps its own, older blocking answer.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
BASH: Final[str] = shutil.which("bash") or "/bin/bash"
PROVISION_COMMAND: Final[str] = "bash .claude/provision.sh"
SKILL_COMMAND: Final[str] = "skill=hooks-daemon"

HEADER: Final[str] = "> Generated on 2026-09-01 (v3.50.0) by the hooks daemon\n"
CONFIG_WARN: Final[str] = 'daemon:\n  expected_version: "3.68.0"\n  log_level: INFO\n'
CONFIG_BLOCK: Final[str] = (
    'daemon:\n  expected_version: "3.68.0"\n  unprovisioned_mode: block\n  log_level: INFO\n'
)

FORWARDERS: Final[tuple[str, ...]] = (
    "session-start",
    "user-prompt-submit",
    "pre-tool-use",
    "post-tool-use",
    "stop",
    "status-line",
)

#: Tools the hook path may run, linked into a private bin dir so a run can be
#: made without jq (and, in one test, without python3).
_TOOLS: Final[tuple[str, ...]] = (
    "sh", "bash", "env", "cat", "dirname", "basename", "tr", "hostname", "stat",
    "date", "mkdir", "touch", "chmod", "rm", "ls", "grep", "awk", "uname", "head",
    "cut", "sort", "wc", "readlink", "realpath", "id", "sleep", "mktemp", "ln",
    "printf", "pgrep", "ps", "flock", "timeout",
)  # fmt: skip


def _link_tools(bin_dir: Path, *, jq: bool, python3: bool) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = list(_TOOLS)
    if jq:
        names.append("jq")
    if python3:
        names.append("python3")
    for name in names:
        found = shutil.which(name)
        if found and not (bin_dir / name).exists():
            (bin_dir / name).symlink_to(found)


def _fresh_clone(
    tmp_path: Path,
    config: str | None = CONFIG_WARN,
    header: str | None = None,
    hooks_daemon_dir: bool = False,
) -> Path:
    """A fresh client checkout: tracked assets, no daemon clone."""
    project = tmp_path / "project"
    claude = project / ".claude"
    hooks = claude / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "init.sh", claude / "init.sh")
    for name in FORWARDERS:
        shutil.copy2(REPO_ROOT / ".claude" / "hooks" / name, hooks / name)
    (claude / "provision.sh").write_text("#!/bin/bash\n")
    if config is not None:
        (claude / "hooks-daemon.yaml").write_text(config)
    if header is not None:
        (claude / "HOOKS-DAEMON.md").write_text(f"# Hooks Daemon\n\n{header}")
    if hooks_daemon_dir:
        (claude / "hooks-daemon").mkdir()
    return project


def _run(
    project: Path,
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    jq: bool = True,
    python3: bool = True,
) -> subprocess.CompletedProcess[str]:
    bin_dir = project.parent / "bin"
    _link_tools(bin_dir, jq=jq, python3=python3)
    body = {
        "cwd": str(project),
        "hook_event_name": event,
        "synthetic_source": "test-probe",
        "probe_as": "main",
    }
    body.update(payload or {})
    return subprocess.run(
        [BASH, str(project / ".claude" / "hooks" / event)],
        input=json.dumps(body),
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.REQUEST_DEFAULT,
        cwd=project,
        env={"PATH": str(bin_dir), "HOME": str(project.parent)},
    )


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, result.stderr
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def _bash_call(command: str) -> dict[str, Any]:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "synthetic_source": "test-probe",
        "probe_as": "main",
    }


def _is_denied(result: subprocess.CompletedProcess[str]) -> bool:
    out = _json(result)
    decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
    return str(decision) == "deny"


class TestSessionStartAndUserPromptSubmit:
    @pytest.mark.parametrize(
        ("hook", "event"),
        [("session-start", "SessionStart"), ("user-prompt-submit", "UserPromptSubmit")],
    )
    def test_human_and_agent_both_get_the_provision_message(
        self, tmp_path: Path, hook: str, event: str
    ) -> None:
        out = _json(_run(_fresh_clone(tmp_path), hook))

        shown_to_human = out["systemMessage"]
        assert out["hookSpecificOutput"]["hookEventName"] == event
        seen_by_agent = out["hookSpecificOutput"]["additionalContext"]
        for text in (shown_to_human, seen_by_agent):
            assert "NEEDS PROVISIONING" in text
            assert "3.68.0" in text
            assert PROVISION_COMMAND in text
            assert SKILL_COMMAND in text
            assert str(tmp_path / "project") in text

    def test_the_message_says_nothing_is_being_checked(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path), "session-start"))

        assert "INACTIVE" in out["systemMessage"]

    def test_it_repeats_on_every_prompt_until_provisioned(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path)

        first = _json(_run(project, "user-prompt-submit"))
        second = _json(_run(project, "user-prompt-submit"))

        assert first["systemMessage"] == second["systemMessage"]
        assert PROVISION_COMMAND in second["systemMessage"]

    def test_the_version_comes_from_the_header_for_a_project_that_predates_the_key(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path, "daemon:\n  log_level: INFO\n", HEADER)

        assert "3.50.0" in _json(_run(project, "session-start"))["systemMessage"]

    def test_an_unknown_version_is_said_to_be_unknown(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, "daemon:\n  log_level: INFO\n")

        message = _json(_run(project, "session-start"))["systemMessage"]

        assert "unknown" in message
        assert PROVISION_COMMAND in message

    def test_an_invalid_version_key_is_reported(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, "daemon:\n  expected_version: main\n", HEADER)

        message = _json(_run(project, "session-start"))["systemMessage"]

        assert "unknown" in message
        assert "not X.Y.Z" in message

    def test_the_empty_daemon_dir_a_source_leaves_behind_is_still_a_fresh_clone(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path, hooks_daemon_dir=True)

        assert "NEEDS PROVISIONING" in _json(_run(project, "session-start"))["systemMessage"]

    def test_works_without_jq(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path), "session-start", jq=False))

        assert PROVISION_COMMAND in out["systemMessage"]
        assert PROVISION_COMMAND in out["hookSpecificOutput"]["additionalContext"]

    def test_a_quote_or_backslash_in_the_checkout_path_cannot_break_the_json(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path / 'we"ird\\dir')

        assert "NEEDS PROVISIONING" in _json(_run(project, "session-start"))["systemMessage"]


class TestStatusLine:
    def test_names_the_command(self, tmp_path: Path) -> None:
        result = _run(_fresh_clone(tmp_path), "status-line")

        assert PROVISION_COMMAND in result.stdout
        assert "\n" not in result.stdout.strip()

    def test_is_not_json(self, tmp_path: Path) -> None:
        result = _run(_fresh_clone(tmp_path), "status-line")

        assert not result.stdout.lstrip().startswith("{")

    def test_a_venv_less_clone_keeps_the_generic_marker(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path)
        resolve_venv = project / ".claude" / "hooks-daemon" / "scripts" / "lib" / "resolve_venv.sh"
        resolve_venv.parent.mkdir(parents=True)
        resolve_venv.write_text("#!/bin/bash\n")

        result = _run(project, "status-line")

        assert result.stdout.strip() == "⚠️ DAEMON FAILED"


class TestWarnMode:
    """The default: nothing is blocked, but everything says so."""

    def test_pre_tool_use_is_not_denied_and_carries_the_message(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path)

        out = _json(_run(project, "pre-tool-use", _bash_call("ls")))

        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "permissionDecision" not in out["hookSpecificOutput"]
        assert PROVISION_COMMAND in out["hookSpecificOutput"]["additionalContext"]
        assert "systemMessage" not in out

    def test_stop_is_not_blocked(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path), "stop"))

        assert "decision" not in out
        assert PROVISION_COMMAND in out["systemMessage"]

    def test_another_event_carries_the_message_to_the_agent_only(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path), "post-tool-use", _bash_call("ls")))

        assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert PROVISION_COMMAND in out["hookSpecificOutput"]["additionalContext"]
        assert "systemMessage" not in out

    def test_the_mode_line_says_calls_are_not_blocked(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path), "session-start"))

        assert "unprovisioned_mode: warn" in out["systemMessage"]

    def test_an_explicit_warn_behaves_as_the_default(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_WARN + "  unprovisioned_mode: warn\n")

        assert not _is_denied(_run(project, "pre-tool-use", _bash_call("ls")))

    def test_an_invalid_mode_warns_and_says_the_value_is_invalid(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_WARN + "  unprovisioned_mode: blok\n")

        assert not _is_denied(_run(project, "pre-tool-use", _bash_call("ls")))
        message = _json(_run(project, "session-start"))["systemMessage"]
        assert "'blok' is not warn or block" in message

    def test_a_mode_key_outside_the_daemon_block_is_not_the_key(self, tmp_path: Path) -> None:
        config = CONFIG_WARN + "handlers:\n  unprovisioned_mode: block\n"

        assert not _is_denied(
            _run(_fresh_clone(tmp_path, config), "pre-tool-use", _bash_call("ls"))
        )


class TestBlockMode:
    def test_pre_tool_use_denies_with_the_provision_message(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        out = _json(_run(project, "pre-tool-use", _bash_call("ls")))

        decision = out["hookSpecificOutput"]
        assert decision["hookEventName"] == "PreToolUse"
        assert decision["permissionDecision"] == "deny"
        assert PROVISION_COMMAND in decision["permissionDecisionReason"]
        assert "3.68.0" in decision["permissionDecisionReason"]

    @pytest.mark.parametrize("quoted", ['"block"', "'block'", "block  # per project"])
    def test_the_value_may_be_quoted_or_carry_a_comment(self, tmp_path: Path, quoted: str) -> None:
        config = f'daemon:\n  expected_version: "3.68.0"\n  unprovisioned_mode: {quoted}\n'

        assert _is_denied(_run(_fresh_clone(tmp_path, config), "pre-tool-use", _bash_call("ls")))

    def test_a_non_bash_tool_is_denied(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/x", "content": "y"},
            "synthetic_source": "test-probe",
            "probe_as": "main",
        }

        assert _is_denied(_run(project, "pre-tool-use", call))

    def test_the_provision_command_is_allowed(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        assert not _is_denied(_run(project, "pre-tool-use", _bash_call(PROVISION_COMMAND)))

    def test_the_provision_command_may_be_padded_with_spaces_and_tabs(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        assert not _is_denied(
            _run(project, "pre-tool-use", _bash_call(f" \t{PROVISION_COMMAND}  "))
        )

    def test_the_absolute_spelling_is_allowed(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        command = f"bash {project / '.claude' / 'provision.sh'}"

        assert not _is_denied(_run(project, "pre-tool-use", _bash_call(command)))

    @pytest.mark.parametrize(
        "command",
        [
            f"{PROVISION_COMMAND} && ls",
            f"{PROVISION_COMMAND}; ls",
            f"{PROVISION_COMMAND} | cat",
            f"{PROVISION_COMMAND} extra",
            f"echo {PROVISION_COMMAND}",
            f"cat .claude/provision.sh # {PROVISION_COMMAND}",
            "bash .claude/provision.sh\nrm -rf x",
            "bash ./.claude/provision.sh",
            "bash .claude/init.sh",
            "sh .claude/provision.sh",
            "bash -x .claude/provision.sh",
            "BASH_ENV=/tmp/x bash .claude/provision.sh",
            "bash .claude/provision.sh $(id)",
            "bash .claude/provision.sh`id`",
            "ls",
        ],
    )
    def test_anything_but_the_command_alone_is_denied(self, tmp_path: Path, command: str) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        assert _is_denied(_run(project, "pre-tool-use", _bash_call(command)))

    def test_a_relative_spelling_from_a_directory_holding_another_script_is_denied(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        planted = tmp_path / "planted"
        (planted / ".claude").mkdir(parents=True)
        (planted / ".claude" / "provision.sh").write_text("#!/bin/bash\n")
        call = _bash_call(PROVISION_COMMAND) | {"cwd": str(planted)}

        assert _is_denied(_run(project, "pre-tool-use", call))

    def test_a_relative_spelling_with_no_cwd_is_denied(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        call = _bash_call(PROVISION_COMMAND) | {"cwd": "relative/dir"}

        assert _is_denied(_run(project, "pre-tool-use", call))

    def test_the_provision_skill_call_is_allowed(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        call = {
            "tool_name": "Skill",
            "tool_input": {"skill": "hooks-daemon", "args": "provision"},
            "synthetic_source": "test-probe",
            "probe_as": "main",
        }

        assert not _is_denied(_run(project, "pre-tool-use", call))

    @pytest.mark.parametrize(
        "tool_input",
        [
            {"skill": "hooks-daemon", "args": "install"},
            {"skill": "hooks-daemon", "args": "provision --force"},
            {"skill": "hooks-daemon", "args": "upgrade provision"},
            {"skill": "hooks-daemon"},
            {"skill": "other-skill", "args": "provision"},
            {"skill": "hooks-daemon", "args": ["provision"]},
        ],
    )
    def test_any_other_skill_call_is_denied(
        self, tmp_path: Path, tool_input: dict[str, Any]
    ) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)
        call = {
            "tool_name": "Skill",
            "tool_input": tool_input,
            "synthetic_source": "test-probe",
            "probe_as": "main",
        }

        assert _is_denied(_run(project, "pre-tool-use", call))

    def test_the_deny_survives_a_missing_jq(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        assert _is_denied(_run(project, "pre-tool-use", _bash_call("ls"), jq=False))
        assert not _is_denied(
            _run(project, "pre-tool-use", _bash_call(PROVISION_COMMAND), jq=False)
        )

    def test_with_neither_jq_nor_python3_the_deny_is_static_and_exempts_nothing(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path, CONFIG_BLOCK)

        result = _run(
            project, "pre-tool-use", _bash_call(PROVISION_COMMAND), jq=False, python3=False
        )

        assert _is_denied(result)
        assert "provision" in _json(result)["hookSpecificOutput"]["permissionDecisionReason"]

    def test_stop_blocks_naming_the_command(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path, CONFIG_BLOCK), "stop"))

        assert out["decision"] == "block"
        assert PROVISION_COMMAND in out["reason"]

    def test_session_start_still_informs_and_does_not_block(self, tmp_path: Path) -> None:
        out = _json(_run(_fresh_clone(tmp_path, CONFIG_BLOCK), "session-start"))

        assert "decision" not in out
        assert "unprovisioned_mode: block" in out["systemMessage"]
        assert PROVISION_COMMAND in out["hookSpecificOutput"]["additionalContext"]

    def test_status_line_still_names_the_command(self, tmp_path: Path) -> None:
        result = _run(_fresh_clone(tmp_path, CONFIG_BLOCK), "status-line")

        assert PROVISION_COMMAND in result.stdout


class TestStatesThatAreNotNeedsProvision:
    def test_ci_enabled_keeps_its_own_blocking_answer(self, tmp_path: Path) -> None:
        config = CONFIG_WARN + "  ci_enabled: true\n"
        project = _fresh_clone(tmp_path, config)

        out = _json(_run(project, "pre-tool-use", _bash_call("ls")))

        hso = out["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "ci_enabled: true" in hso["permissionDecisionReason"]
        assert "NEEDS PROVISIONING" not in hso["permissionDecisionReason"]

    def test_ci_enabled_wins_over_block_mode(self, tmp_path: Path) -> None:
        config = CONFIG_BLOCK + "  ci_enabled: true\n"

        out = _json(_run(_fresh_clone(tmp_path, config), "pre-tool-use", _bash_call("ls")))

        hso = out["hookSpecificOutput"]
        assert hso["permissionDecision"] == "deny"
        assert "NEEDS PROVISIONING" not in hso["permissionDecisionReason"]

    def test_a_clone_with_no_venv_is_the_repair_state(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path)
        resolve_venv = project / ".claude" / "hooks-daemon" / "scripts" / "lib" / "resolve_venv.sh"
        resolve_venv.parent.mkdir(parents=True)
        resolve_venv.write_text("#!/bin/bash\n")

        out = _json(_run(project, "session-start"))

        assert "NEEDS PROVISIONING" not in out["hookSpecificOutput"]["additionalContext"]
        assert "venv missing" in out["hookSpecificOutput"]["additionalContext"]
        assert "systemMessage" not in out

    def test_a_project_with_no_daemon_config_is_not_a_provisionable_checkout(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path, config=None)

        out = _json(_run(project, "session-start"))

        assert "NEEDS PROVISIONING" not in out["hookSpecificOutput"]["additionalContext"]
        assert "Not installed" in out["hookSpecificOutput"]["additionalContext"]

    def test_a_project_that_predates_provision_sh_is_not_told_to_run_it(
        self, tmp_path: Path
    ) -> None:
        project = _fresh_clone(tmp_path)
        (project / ".claude" / "provision.sh").unlink()

        out = _json(_run(project, "session-start"))

        assert PROVISION_COMMAND not in out["hookSpecificOutput"]["additionalContext"]
        assert "Not installed" in out["hookSpecificOutput"]["additionalContext"]

    def test_the_daemons_own_repository_never_needs_provisioning(self, tmp_path: Path) -> None:
        project = _fresh_clone(tmp_path)
        version_py = project / "src" / "claude_code_hooks_daemon" / "version.py"
        version_py.parent.mkdir(parents=True)
        version_py.write_text('__version__ = "3.68.0"\n')

        result = _run(project, "session-start")

        assert "NEEDS PROVISIONING" not in result.stdout


class TestHookPathCost:
    def test_the_check_adds_only_file_tests_when_a_daemon_is_present(self, tmp_path: Path) -> None:
        """No expected-version or mode lookup happens unless the state is reached."""
        project = _fresh_clone(tmp_path)
        resolve_venv = project / ".claude" / "hooks-daemon" / "scripts" / "lib" / "resolve_venv.sh"
        resolve_venv.parent.mkdir(parents=True)
        resolve_venv.write_text("#!/bin/bash\n")
        probe = project / "awk-probe"
        bin_dir = project.parent / "bin"
        _link_tools(bin_dir, jq=True, python3=True)
        awk = bin_dir / "awk"
        awk.unlink()
        awk.write_text(f'#!/bin/bash\necho run >> "{probe}"\nexec {shutil.which("awk")} "$@"\n')
        awk.chmod(0o700)

        _run(project, "session-start")

        assert not probe.exists(), "awk ran on a path that is not NEEDS_PROVISION"
