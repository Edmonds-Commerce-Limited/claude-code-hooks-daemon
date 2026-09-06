"""A write outside the repository root must be denied (Plan 00333).

Every path guard in this daemon is expressed in repo-relative coordinates, and
the absolute-to-relative conversion **is** the containment test. When that
conversion fails the verdict is uniformly *allow* --
``markdown_organization.py:956`` catches the ``ValueError`` and returns
``False``; ``sensitive_content.py:358`` comments *"Outside the project root: not
ours to judge"*; six more handlers do the same. So a markdown file at the repo
root is denied for being in the wrong location while the identical file at
``/tmp/notes.md`` is silently permitted, because it left the coordinate system
the rules are defined in.

The harm is durability, not tidiness. The container's temp directory is
ephemeral while the repository is a bind mount, so anything written there is
lost on restart, invisible to git and outside review. The project already held
this position in three places before it was ever a rule -- ``daemon/paths.py``
stores runtime files in ``untracked/`` *"not /tmp, to prevent security
vulnerabilities"*, ``scripts/echd-capture`` prefers ``untracked/captures`` and
calls the temp directory a *"last resort"*, and ``worktree_seed_suggestions``
calls ``untracked/`` *"this daemon's own scratch convention"*. The tools obeyed
it; the agent, for whom it was never a rule, did not.

**These tests drive the FULL discovered chain**, not one handler. That is the
whole point: the defect is not that some handler forgot a case, it is that no
handler in the system owns the premise. A test that registered only the new
guard would pass on the day it was written and prove nothing about the system
that shipped.

**Scope, deliberately.** The guard judges paths NAMED in a tool input. It does
not police what a program does at runtime, because a PreToolUse hook receives a
command string rather than syscalls. Measured on the container that prompted
this plan: of 324 MB in ``/tmp``, 308 MB was pytest's own ``tmp_path`` tree and
2,415 of 2,834 entries were zero-length ``uv`` lock files. A guard fighting uv,
pytest, pyright, node and semgrep would be switched off within a day, so it does
not try.

No test here creates a file outside the repository. A PreToolUse handler judges
the input, so naming the path is sufficient -- writing one to prove writes are
bad would be its own joke.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

from .conftest import make_bash_input, make_read_input, make_write_input

#: The handler that owns the containment premise. Named here rather than
#: inlined so a rename surfaces as one failure instead of a dozen.
_GUARD_NAME = "enforce-project-containment"


@pytest.fixture()
def full_chain(project_context: Path) -> EventRouter:
    """Every discovered handler, at its default configuration.

    Passing no handler config means "defaults", which is what a project that
    has never touched its handler config actually runs. A guard that only
    worked when explicitly enabled would not have caught this.

    The config file is rewritten with a QUOTED version first: the shared
    fixture emits ``version: 1.0``, which YAML types as a float and Pydantic
    then rejects when a handler loads the file during registration. Other
    integration tests never hit it because they pass a hand-built config
    instead of letting registration read from disk.
    """
    (project_context / ".claude" / "hooks-daemon.yaml").write_text(
        'version: "1.0"\n', encoding="utf-8"
    )

    router = EventRouter()
    registry = HandlerRegistry()
    registry.discover()
    registry.register_all(router)
    return router


class TestAnOutOfRootWriteIsDenied:
    """The defect, stated directly, on the Write/Edit surface."""

    def test_a_write_to_the_container_temp_dir_is_denied(
        self, full_chain: EventRouter
    ) -> None:
        """The shape the owner reported: scratch that outlives the container."""
        result = full_chain.route(
            EventType.PRE_TOOL_USE,
            make_write_input("/tmp/00333-repro.md", "# durable work, ephemeral home"),
        )

        assert result.result.decision == Decision.DENY, (
            "a Write to /tmp was allowed through the entire handler chain. This "
            "is the whole defect: the file is outside every guard's coordinate "
            "system, so nothing judged it at all."
        )

    def test_the_denial_comes_from_the_containment_guard(
        self, full_chain: EventRouter
    ) -> None:
        """Denied for the right reason, not incidentally by another handler."""
        result = full_chain.route(
            EventType.PRE_TOOL_USE,
            make_write_input("/tmp/00333-repro.md", "# content"),
        )

        assert result.terminated_by == _GUARD_NAME

    def test_the_denial_names_the_sanctioned_location(
        self, full_chain: EventRouter
    ) -> None:
        """A guard that blocks without naming the alternative just obstructs."""
        result = full_chain.route(
            EventType.PRE_TOOL_USE,
            make_write_input("/tmp/00333-repro.md", "# content"),
        )

        assert result.result.reason is not None
        assert "untracked/scratch" in result.result.reason

    def test_any_out_of_root_path_is_denied_not_just_the_temp_dir(
        self, full_chain: EventRouter, tmp_path: Path
    ) -> None:
        """The premise is containment, not a blocklist of one directory.

        A rule keyed on the literal string ``/tmp`` would pass every other test
        in this class and still leave ``/var/tmp``, ``$HOME`` and a sibling
        checkout wide open.
        """
        outside = tmp_path / "not-the-project" / "notes.md"

        result = full_chain.route(
            EventType.PRE_TOOL_USE, make_write_input(str(outside), "# content")
        )

        assert result.result.decision == Decision.DENY


class TestTheBashSideDoorIsClosed:
    """A path-keyed guard blind to Bash guards nothing (Plan 00260).

    ``get_bash_write_targets`` already resolves the absolute paths a command
    plainly writes, and is differential-tested against a real shell, so this is
    a caller rather than new machinery.
    """

    @pytest.mark.parametrize(
        ("label", "command"),
        [
            ("redirect", "echo hello > /tmp/00333-repro.txt"),
            ("append", "echo hello >> /tmp/00333-repro.txt"),
            ("tee", "echo hello | tee /tmp/00333-repro.txt"),
            ("heredoc", "cat > /tmp/00333-repro.txt <<'EOF'\nhello\nEOF"),
            ("copy", "cp README.md /tmp/00333-repro.md"),
        ],
    )
    def test_a_bash_write_outside_the_root_is_denied(
        self, full_chain: EventRouter, label: str, command: str
    ) -> None:
        result = full_chain.route(EventType.PRE_TOOL_USE, make_bash_input(command))

        assert result.result.decision == Decision.DENY, (
            f"the {label} shape reached /tmp unjudged. Closing only the "
            "Write/Edit surface would move the escape rather than end it."
        )


class TestTheGuardDoesNotOverreach:
    """Every one of these would be a reason to switch the guard off."""

    def test_a_write_inside_the_repo_is_not_denied_by_this_guard(
        self, full_chain: EventRouter, project_context: Path
    ) -> None:
        inside = project_context / "untracked" / "scratch" / "note.md"

        result = full_chain.route(
            EventType.PRE_TOOL_USE, make_write_input(str(inside), "# scratch")
        )

        assert result.terminated_by != _GUARD_NAME

    def test_reading_an_out_of_root_path_is_not_denied(
        self, full_chain: EventRouter
    ) -> None:
        """Blocking reads would break diagnosis and gain nothing durable."""
        result = full_chain.route(EventType.PRE_TOOL_USE, make_read_input("/tmp/whatever.log"))

        assert result.terminated_by != _GUARD_NAME

    def test_a_bash_command_that_only_reads_out_of_root_is_not_denied(
        self, full_chain: EventRouter
    ) -> None:
        result = full_chain.route(
            EventType.PRE_TOOL_USE, make_bash_input("grep -c pattern /tmp/whatever.log")
        )

        assert result.terminated_by != _GUARD_NAME

    def test_a_command_whose_target_needs_shell_expansion_is_not_denied(
        self, full_chain: EventRouter
    ) -> None:
        """``get_bash_write_targets`` is conservative and yields nothing here.

        A wrong path is worse than no path: it would attribute a write to a
        file the command never touched. The guard inherits that contract rather
        than guessing.
        """
        result = full_chain.route(EventType.PRE_TOOL_USE, make_bash_input('echo hi > "$OUT"'))

        assert result.terminated_by != _GUARD_NAME
