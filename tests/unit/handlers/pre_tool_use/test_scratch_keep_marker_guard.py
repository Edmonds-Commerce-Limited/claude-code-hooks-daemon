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

    @pytest.mark.parametrize(
        "command",
        [
            f"mkdir {_ENTRY}/.scratch-keep",
            f"mkdir -p {_ENTRY}/.scratch-keep",
            f"mkdir -p {_ENTRY}/.scratch-keep/a",
            f"mkdir -pv -m 0755 {_ENTRY}/.scratch-keep",
            f"mkdir --parents --mode=0755 -- {_ENTRY}/.scratch-keep/a/b",
            f'mkdir "{_ENTRY}/.scratch-keep"',
            f"mkdir '{_ENTRY}/.scratch-keep/'",
            f"mkdir {_ENTRY}/other {_ENTRY}/.scratch-keep",
            "mkdir .scratch-keep",
            f"cd {_ENTRY} && mkdir .scratch-keep",
            'mkdir -p "$ENTRY/.scratch-keep"',
            f"/bin/mkdir {_ENTRY}/.scratch-keep",
            f"sudo mkdir -p {_ENTRY}/.scratch-keep",
            f"timeout 5 mkdir {_ENTRY}/.scratch-keep",
            f"sh -c 'mkdir -p {_ENTRY}/.scratch-keep'",
            f"mkfifo {_ENTRY}/.scratch-keep",
            f"mkfifo -m 600 {_ENTRY}/.scratch-keep",
            f"mknod {_ENTRY}/.scratch-keep p",
            f"mknod -m 600 {_ENTRY}/.scratch-keep c 1 3",
        ],
    )
    def test_creating_a_marker_node_of_any_kind_is_denied(
        self, handler: ScratchKeepMarkerGuardHandler, command: str
    ) -> None:
        """N767 review: a directory, FIFO or device named the marker now keeps too."""
        assert handler.matches(_bash(command))
        assert handler.handle(_bash(command)).decision == Decision.DENY

    @pytest.mark.parametrize(
        "hook_input",
        [
            _write(f"{_ENTRY}/.scratch-keep/notes.md"),
            _edit(f"{_ENTRY}/.scratch-keep/why.txt"),
            _bash(f"echo r > {_ENTRY}/.scratch-keep/why.txt"),
            _bash(f"touch {_ENTRY}/.scratch-keep/why.txt"),
            _bash(f"rm -r {_ENTRY}/.scratch-keep/why.txt"),
        ],
    )
    def test_a_write_below_a_marker_directory_is_denied(
        self, handler: ScratchKeepMarkerGuardHandler, hook_input: dict[str, Any]
    ) -> None:
        """Write creates missing parents, so a path below the marker creates it."""
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_copy_into_an_existing_entry_directory_is_denied(
        self, handler: ScratchKeepMarkerGuardHandler, tmp_path: Path
    ) -> None:
        entry = tmp_path / "entry"
        entry.mkdir()
        hook_input = _bash(f"cp other/.scratch-keep {entry}/")
        assert handler.matches(hook_input)
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_copy_into_an_unreadable_destination_fails_closed(
        self, handler: ScratchKeepMarkerGuardHandler, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A destination whose kind cannot be read (EACCES) is treated as a
        directory, so the copy that would name the marker is denied, not crashed."""

        def _unreadable(self: Path) -> bool:
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "is_dir", _unreadable)
        hook_input = _bash("cp other/.scratch-keep somewhere")
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


class TestUnlexableStatementRoutes:
    """Characterisation: an unlexable command on the copy/interpreter routes.

    The statement scan the copy and interpreter routes share with the cap
    guard raises on text shlex cannot lex. This guard does not crash on it and
    keeps its existing verdict (not matched); that open route is reported to
    the plan owner rather than changed here.
    """

    @pytest.mark.parametrize(
        "command",
        [
            f"echo $'it\\'s'; cp /tmp/.scratch-keep {_ENTRY}/",
            "echo $'it\\'s'; python3 -c 'open(\".scratch-keep\",\"w\")'",
        ],
    )
    def test_does_not_crash_and_keeps_its_verdict(
        self, handler: ScratchKeepMarkerGuardHandler, command: str
    ) -> None:
        assert not handler.matches(_bash(command))


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
            _bash(f"mkdir -p {_ENTRY}/sub"),
            _bash(f"mkdir -p {_ENTRY}/.scratch-keeper {_ENTRY}/scratch-keep"),
            _bash(f"mkfifo {_ENTRY}/pipe"),
            _bash(f"ls {_ENTRY}/.scratch-keep/"),
            _bash(f"cat {_ENTRY}/.scratch-keep/why.txt"),
            _bash("git commit -m 'mkdir .scratch-keep is denied'"),
            _bash(f"echo 'mkdir {_ENTRY}/.scratch-keep' > {_ENTRY}/notes.txt"),
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

    def test_acceptance_tests_declare_the_decision_the_handler_gives(
        self, handler: ScratchKeepMarkerGuardHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        decisions = {test.expected_decision for test in tests}
        assert decisions == {Decision.DENY, Decision.ALLOW}
        for test in tests:
            payload = test.tool_payload
            assert payload is not None
            hook_input = {
                "tool_name": payload.tool_name,
                "tool_input": payload.tool_input,
                "cwd": "/",
            }
            assert handler.handle(hook_input).decision == test.expected_decision, test.title
