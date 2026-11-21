"""Tests for scratch_keep_marker_guard (Plan 00627 Task 4.4, R-SCRATCH-KEEP-MARKER).

`.scratch-keep` pins a scratch entry for ever (DESIGN R15), so it must be a
human's mark: an agent may not create, change or remove it by any write route.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.scratch_keep_marker_guard import (
    ScratchKeepMarkerGuardHandler,
)

_CWD = "/srv/project"
_ENTRY = "/srv/project/untracked/scratch/s1/probe"


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": _CWD}


def _write(path: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": "x"}, "cwd": _CWD}


def _edit(path: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"},
        "cwd": _CWD,
    }


@pytest.fixture
def handler() -> ScratchKeepMarkerGuardHandler:
    return ScratchKeepMarkerGuardHandler()


class TestDenied:
    @pytest.mark.parametrize(
        "hook_input",
        [
            _write(f"{_ENTRY}/.scratch-keep"),
            _edit(f"{_ENTRY}/.scratch-keep"),
            _bash(f"echo 'keep it' > {_ENTRY}/.scratch-keep"),
            _bash(f"echo 'keep it' >> {_ENTRY}/.scratch-keep"),
            _bash(f"echo reason | tee {_ENTRY}/.scratch-keep"),
            _bash(f"touch {_ENTRY}/.scratch-keep"),
            _bash(f"cp /tmp/reason {_ENTRY}/.scratch-keep"),
            _bash(f"mv /tmp/reason {_ENTRY}/.scratch-keep"),
            _bash(f"ln -s /tmp/reason {_ENTRY}/.scratch-keep"),
            _bash(f"install -m 644 /tmp/reason {_ENTRY}/.scratch-keep"),
            _bash("touch untracked/scratch/s1/probe/.scratch-keep"),
            _bash(f"cd {_ENTRY} && touch .scratch-keep"),
            _bash(f"mkdir -p {_ENTRY} && printf 'r\\n' > {_ENTRY}/.scratch-keep"),
            _bash(f"rm {_ENTRY}/.scratch-keep"),
            _bash(f"cat > {_ENTRY}/.scratch-keep <<'EOF'\nreason\nEOF"),
            # D-RULE review finding 3: a directory destination, a shell body,
            # an interpreter body.
            _bash(f"cp .scratch-keep {_ENTRY}/"),
            _bash(f"cp -t {_ENTRY} /tmp/x/.scratch-keep"),
            _bash(f"mv ../.scratch-keep a.txt {_ENTRY}"),
            _bash(f"install -m 644 .scratch-keep {_ENTRY}/"),
            _bash(f"timeout 5 cp .scratch-keep {_ENTRY}/"),
            _bash(f'sh -c "touch {_ENTRY}/.scratch-keep"'),
            _bash(f"bash -lc 'cd {_ENTRY} && touch .scratch-keep'"),
            _bash(f"set -e\nsh -c 'echo r > {_ENTRY}/.scratch-keep'"),
            _bash(f"python3 -c \"open('{_ENTRY}/.scratch-keep','w')\""),
            _bash("perl -e 'open(F, \">.scratch-keep\")'"),
            _bash("node -e \"require('fs').writeFileSync('.scratch-keep','')\""),
            _bash("sudo python3.12 -c \"import pathlib; pathlib.Path('.scratch-keep').touch()\""),
        ],
    )
    def test_every_write_route_is_denied(
        self, handler: ScratchKeepMarkerGuardHandler, hook_input: dict[str, Any]
    ) -> None:
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert f"BLOCKED [{RuleID.SCRATCH_KEEP_MARKER}]" in result.reason
        assert "human" in result.reason

    def test_copy_into_an_existing_entry_directory_is_denied(
        self, handler: ScratchKeepMarkerGuardHandler, tmp_path: Path
    ) -> None:
        entry = tmp_path / "entry"
        entry.mkdir()
        hook_input = _bash(f"cp other/.scratch-keep {entry}/")
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            'echo x > "$DIR/.scratch-keep"',
            "touch $ENTRY/.scratch-keep",
            # Unreadable text naming the marker: where it writes is unknown.
            "echo \"it's\" > .scratch-keep 'unbalanced",
        ],
    )
    def test_unresolved_destination_naming_the_marker_fails_closed(
        self, handler: ScratchKeepMarkerGuardHandler, command: str
    ) -> None:
        assert handler.matches(_bash(command))
        assert handler.handle(_bash(command)).decision == Decision.DENY


class TestAllowed:
    @pytest.mark.parametrize(
        "hook_input",
        [
            _write(f"{_ENTRY}/notes.md"),
            _write(f"{_ENTRY}/scratch-keep.md"),
            _write(f"{_ENTRY}/.scratch-keep.bak/x"),
            _bash(f"cat {_ENTRY}/.scratch-keep"),
            _bash(f"ls -la {_ENTRY}"),
            _bash("grep -rn scratch-keep src/"),
            _bash("git commit -m 'document .scratch-keep'"),
            _bash(f"echo x > {_ENTRY}/notes.txt"),
            _bash('echo x > "$DIR/notes.txt"'),
            _bash(
                "git commit -q -F - <<'EOF'\nGuard `.scratch-keep` writes; it's a human's mark\nEOF"
            ),
            _bash(
                f"cat > {_ENTRY}/notes.md <<'EOF'\nDon't touch .scratch-keep, it's the owner's\nEOF"
            ),
            {"tool_name": "Read", "tool_input": {"file_path": f"{_ENTRY}/.scratch-keep"}},
            _bash(f"cp {_ENTRY}/.scratch-keep /tmp/marker-copy.txt"),
            _bash(f"sh -c 'cat {_ENTRY}/.scratch-keep'"),
            _bash(f"test -e {_ENTRY}/.scratch-keep && echo kept"),
            _bash("python3 -c 'print(1)'"),
            _bash("git commit -m 'sh -c touch .scratch-keep is denied'"),
        ],
    )
    def test_reads_and_other_files_pass(
        self, handler: ScratchKeepMarkerGuardHandler, hook_input: dict[str, Any]
    ) -> None:
        assert not handler.matches(hook_input)


class TestContract:
    def test_rule_is_declared(self, handler: ScratchKeepMarkerGuardHandler) -> None:
        assert [rule.rule_id for rule in handler.get_rules()] == [RuleID.SCRATCH_KEEP_MARKER]

    def test_is_terminal(self, handler: ScratchKeepMarkerGuardHandler) -> None:
        assert handler.terminal is True

    def test_guidance_names_the_rule(self, handler: ScratchKeepMarkerGuardHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert ".scratch-keep" in guidance
        assert "R-SCRATCH-KEEP-MARKER" in guidance

    def test_acceptance_tests_deny(self, handler: ScratchKeepMarkerGuardHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert tests
        assert all(test.expected_decision == Decision.DENY for test in tests)
