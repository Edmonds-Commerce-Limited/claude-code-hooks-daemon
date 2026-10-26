"""A forwarder fails open when ``init.sh`` does not parse (Plan 00552).

A git merge can leave conflict markers in ``.claude/init.sh``. Sourcing it then
makes bash exit 2 on the syntax error, and Claude Code reads a hook's exit 2 as
BLOCK, so every event (UserPromptSubmit included) is blocked and the session
cannot take a prompt. The generated parse guard runs ``bash -n`` on ``init.sh``
first and answers non-blocking instead.

The forwarders are driven for real under ``bash``, so the assertions are about
exit codes and what reaches stdout, not about script text.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from install import create_forwarder_script, create_status_line_script

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.events import raw_stdout_bash_keys
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import (
    INIT_PARSE_GUARD_FOOTER,
    INIT_PARSE_GUARD_HEADER,
    INIT_REPAIR_HINT,
    INIT_SH_ANCHOR,
    generate_forwarder_content,
)
from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

CONFLICTED_INIT = "echo before\n<<<<<<< HEAD\necho ours\n=======\necho theirs\n>>>>>>> branch\n"
HEALTHY_INIT = "echo INIT_SOURCED\nexit 0\n"
STATUS_LINE = "status-line"
RAW_STDOUT_KEYS = raw_stdout_bash_keys()
EVENTS: dict[str, str] = {
    bash_key: json_key for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
}


def _stub(tmp_path: Path, hook_name: str, *, relay: bool = False) -> Path:
    """Generate one forwarder into ``tmp_path/.claude/hooks`` with a healthy init.sh."""
    hooks_dir = tmp_path / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    if hook_name == STATUS_LINE:
        create_status_line_script(hooks_dir)
    else:
        create_forwarder_script(hooks_dir, hook_name, EVENTS[hook_name])
    path = hooks_dir / hook_name
    path.write_text(
        generate_forwarder_content(
            path.read_text(),
            hook_name,
            TransportConfig(relay_enabled=relay),
            tmp_path / "untracked",
            tmp_path,
        )
    )
    (tmp_path / ".claude" / "init.sh").write_text(HEALTHY_INIT)
    return path


def _run(stub: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(stub)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_DEFAULT,
        check=False,
    )


ALL_HOOKS = [*EVENTS, STATUS_LINE]


class TestGuardOnConflictedInit:
    @pytest.mark.parametrize("hook_name", ALL_HOOKS)
    def test_never_exits_2(self, tmp_path: Path, hook_name: str) -> None:
        stub = _stub(tmp_path, hook_name)
        (tmp_path / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        result = _run(stub)
        assert result.returncode != 2, result.stderr
        assert "INIT_SOURCED" not in result.stdout

    @pytest.mark.parametrize("hook_name", [h for h in EVENTS if h not in RAW_STDOUT_KEYS])
    def test_json_event_answers_non_blocking_json_naming_file_and_hint(
        self, tmp_path: Path, hook_name: str
    ) -> None:
        stub = _stub(tmp_path, hook_name)
        (tmp_path / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        result = _run(stub)
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        assert "init.sh" in payload["systemMessage"]
        assert INIT_REPAIR_HINT in payload["systemMessage"]
        assert "decision" not in payload

    @pytest.mark.parametrize("hook_name", ["user-prompt-submit", "stop", "subagent-stop"])
    def test_prompt_and_stop_events_exit_zero(self, tmp_path: Path, hook_name: str) -> None:
        stub = _stub(tmp_path, hook_name)
        (tmp_path / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        assert _run(stub).returncode == 0

    def test_status_line_prints_a_display_line_and_exits_zero(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path, STATUS_LINE)
        (tmp_path / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        result = _run(stub)
        assert result.returncode == 0
        assert "init.sh" in result.stdout
        assert not result.stdout.lstrip().startswith("{")

    def test_value_event_prints_nothing_on_stdout(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path, "worktree-create")
        (tmp_path / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        result = _run(stub)
        assert result.returncode == 1
        assert result.stdout == ""
        assert "init.sh" in result.stderr
        assert INIT_REPAIR_HINT in result.stderr

    def test_missing_init_sh_also_fails_open(self, tmp_path: Path) -> None:
        stub = _stub(tmp_path, "pre-tool-use")
        (tmp_path / ".claude" / "init.sh").unlink()
        result = _run(stub)
        assert result.returncode == 0
        assert "init.sh" in json.loads(result.stdout)["systemMessage"]

    def test_path_with_quote_still_yields_valid_json(self, tmp_path: Path) -> None:
        quoted = tmp_path / 'a"b'
        quoted.mkdir()
        stub = _stub(quoted, "pre-tool-use")
        (quoted / ".claude" / "init.sh").write_text(CONFLICTED_INIT)
        result = _run(stub)
        assert result.returncode == 0
        assert "init.sh" in json.loads(result.stdout)["systemMessage"]


class TestGuardOnHealthyInit:
    @pytest.mark.parametrize("hook_name", ["pre-tool-use", STATUS_LINE, "stop"])
    def test_healthy_init_is_sourced(self, tmp_path: Path, hook_name: str) -> None:
        stub = _stub(tmp_path, hook_name)
        result = _run(stub)
        assert "INIT_SOURCED" in result.stdout


class TestGuardPlacement:
    @pytest.mark.parametrize("hook_name", ALL_HOOKS)
    def test_guard_sits_directly_above_the_source_line(
        self, tmp_path: Path, hook_name: str
    ) -> None:
        content = _stub(tmp_path, hook_name).read_text()
        assert content.count(INIT_PARSE_GUARD_HEADER) == 1
        footer_end = content.index(INIT_PARSE_GUARD_FOOTER) + len(INIT_PARSE_GUARD_FOOTER)
        assert content[footer_end:].startswith(INIT_SH_ANCHOR)

    def test_relay_hot_path_runs_before_the_guard(self, tmp_path: Path) -> None:
        content = _stub(tmp_path, "pre-tool-use", relay=True).read_text()
        relay_end = content.index("# --- end relay hot path ---")
        assert relay_end < content.index(INIT_PARSE_GUARD_HEADER)

    @pytest.mark.parametrize("relay", [False, True])
    def test_generation_is_idempotent(self, tmp_path: Path, relay: bool) -> None:
        content = _stub(tmp_path, "pre-tool-use", relay=relay).read_text()
        again = generate_forwarder_content(
            content,
            "pre-tool-use",
            TransportConfig(relay_enabled=relay),
            tmp_path / "untracked",
            tmp_path,
        )
        assert again == content

    @pytest.mark.parametrize("hook_name", ALL_HOOKS)
    def test_guard_does_not_hide_errors(self, tmp_path: Path, hook_name: str) -> None:
        content = _stub(tmp_path, hook_name).read_text()
        start = content.index(INIT_PARSE_GUARD_HEADER)
        guard = content[start : content.index(INIT_PARSE_GUARD_FOOTER)]
        assert "/dev/null" not in guard
