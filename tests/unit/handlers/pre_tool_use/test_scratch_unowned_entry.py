"""Tests for the scratch_unowned_entry handler (Plan 00627 Task 4.5).

A write that would create a new entry directly in a scratch root, outside any
session directory, gets an advisory naming ``scratch new`` (or a deny when
``scratch.sweep.unowned_entry`` is ``block``; nothing when ``off``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pytest

from claude_code_hooks_daemon.config.models import ScratchConfig, ScratchSweepConfig
from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.scratch_unowned_entry import (
    ScratchUnownedEntryHandler,
)

_SESSION = "s-20261121T100000Z-aaaaaaaa"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    scratch = tmp_path / "untracked" / "scratch"
    (scratch / _SESSION).mkdir(parents=True)
    (scratch / "existing").mkdir()
    return scratch


def _handler(
    mode: Literal["advise", "block", "off"] | None = None,
) -> ScratchUnownedEntryHandler:
    handler = ScratchUnownedEntryHandler()
    if mode is not None:
        handler._scratch = ScratchConfig(sweep=ScratchSweepConfig(unowned_entry=mode))
    return handler


def _write(path: Path) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}}


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestIdentity:
    def test_id_priority(self) -> None:
        handler = ScratchUnownedEntryHandler()
        assert handler.name == HandlerID.SCRATCH_UNOWNED_ENTRY.display_name
        assert handler.priority == Priority.SCRATCH_UNOWNED_ENTRY

    def test_uninjected_defaults_to_advise(self, root: Path) -> None:
        result = _handler().handle(_write(root / "new.txt"))
        assert result.decision == Decision.ALLOW
        assert any("scratch new" in line for line in result.context)


class TestMatches:
    @pytest.mark.parametrize("relative", ["new.txt", "newdir/a.txt", "newdir/deep/b.txt"])
    def test_new_direct_entry(self, root: Path, relative: str) -> None:
        assert _handler().matches(_write(root / relative))

    @pytest.mark.parametrize(
        "relative",
        [f"{_SESSION}/probe/a.txt", "existing/a.txt", ".gitignore", "s-20261121T110000Z-bbbbbbbb"],
    )
    def test_owned_existing_or_exempt(self, root: Path, relative: str) -> None:
        assert not _handler().matches(_write(root / relative))

    @pytest.mark.parametrize(
        "spelling",
        [f"{_SESSION}/../sneaky.txt", "existing/../sneaky.txt", "./sneaky/a.txt"],
    )
    def test_dot_segments_cannot_hide_a_new_entry(self, root: Path, spelling: str) -> None:
        assert _handler().matches(_write(Path(f"{root}/{spelling}")))

    def test_dot_segment_spelling_of_the_root_is_still_the_root(self, root: Path) -> None:
        tricky = Path(f"{root.parent}/./scratch/sneaky.txt")
        assert _handler().matches(_write(tricky))

    @pytest.mark.parametrize(
        "command",
        [
            "mkdir untracked/scratch/made",
            "mkdir -p untracked/scratch/made/deep",
            "set -e\nmkdir untracked/scratch/made",
            "cd untracked/scratch && mkdir made",
            "env FOO=1 mkdir untracked/scratch/made",
            "bash -c 'mkdir untracked/scratch/made'",
        ],
    )
    def test_bash_directory_creation_is_seen(self, root: Path, command: str) -> None:
        assert _handler().matches(_bash(command, root.parent.parent))

    def test_bash_mkdir_inside_the_session_does_not_fire(self, root: Path) -> None:
        command = f"mkdir untracked/scratch/{_SESSION}/probe"
        assert not _handler().matches(_bash(command, root.parent.parent))

    @pytest.mark.parametrize("odd", [None, 7, ["a"], {"x": 1}])
    def test_odd_file_path_is_ignored_not_a_crash(self, odd: object) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": odd, "content": "x"}}
        assert not _handler().matches(hook_input)

    def test_bash_with_no_cwd_is_not_a_crash(self, root: Path) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "mkdir made"}}
        assert not _handler().matches(hook_input)

    def test_outside_a_scratch_root(self, tmp_path: Path) -> None:
        assert not _handler().matches(_write(tmp_path / "untracked" / "other" / "x.txt"))
        assert not _handler().matches(_write(tmp_path / "scratch" / "x.txt"))

    def test_the_root_itself(self, root: Path) -> None:
        assert not _handler().matches(_write(root))

    def test_bash_redirect(self, root: Path, tmp_path: Path) -> None:
        assert _handler().matches(_bash("echo hi > untracked/scratch/notes.txt", tmp_path))
        assert not _handler().matches(
            _bash(f"echo hi > untracked/scratch/{_SESSION}/notes.txt", tmp_path)
        )

    def test_unresolved_bash_destination_does_not_fire(self, root: Path, tmp_path: Path) -> None:
        assert not _handler().matches(_bash('echo hi > "$DIR/x.txt"', tmp_path))

    def test_off(self, root: Path) -> None:
        assert not _handler("off").matches(_write(root / "new.txt"))


class TestHandle:
    def test_advise_never_denies(self, root: Path) -> None:
        result = _handler("advise").handle(_write(root / "new.txt"))
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "new" in text and "scratch new" in text

    def test_block_denies_with_rule(self, root: Path) -> None:
        result = _handler("block").handle(_write(root / "new.txt"))
        assert result.decision == Decision.DENY
        assert "R-SCRATCH-UNOWNED-ENTRY" in (result.reason or "")

    def test_acceptance_tests_declare_both_answers(self) -> None:
        """The default advisory is probed live; the block-mode deny is declared
        but cannot be produced under the shipped ``advise`` default."""
        tests = _handler().get_acceptance_tests()
        allows = [t for t in tests if t.expected_decision == Decision.ALLOW]
        denies = [t for t in tests if t.expected_decision == Decision.DENY]
        assert len(allows) == 1 and allows[0].tool_payload is not None
        assert len(denies) == 1
        assert denies[0].harness_cannot_produce
        assert "block" in denies[0].harness_cannot_produce
        assert any("R-SCRATCH-UNOWNED-ENTRY" in p for p in denies[0].expected_message_patterns)

    def test_no_match_allows_silently(self, root: Path) -> None:
        result = _handler("block").handle(_write(root / "existing" / "a.txt"))
        assert result.decision == Decision.ALLOW
        assert not result.context
