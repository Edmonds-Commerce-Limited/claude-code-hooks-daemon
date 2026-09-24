"""Tests for PlanJournalGuardHandler (Plan 00461).

A journal entry reaches a plan's ``JOURNAL/`` day-file through
``mkplan.bash --journal`` and nothing else, because the tool reads the real UTC
clock and a hand-typed timestamp does not. Every route that wrote an entry by
hand in the session that prompted this plan is reproduced here and must be
DENIED: an Edit append, a Write, a heredoc, ``tee -a``, ``printf >>``, a copy
onto the file, an interpreter one-liner and an in-place editor.

The allowances are just as load-bearing, because a guard that blocks the
remedy or an ordinary git operation gets switched off:

* ``mkplan.bash --journal`` itself;
* ``git`` (``git mv`` of a plan folder into ``Completed/``, ``git add``);
* READING a day-file (``tail``, ``grep``, a read-only one-liner);
* a deletion-only Edit, e.g. removing merge conflict markers after two
  branches each appended an entry -- that is the append-only rule's business.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_journal_guard import (
    PlanJournalGuardHandler,
)

PLAN_DIR = "CLAUDE/Plan"
LIVE_FOLDER = "00461-journal-entries-only"
ARCHIVED_FOLDER = "00300-old-work"
LIVE_DAYFILE = "00461-Journal-26-09-24.md"
ARCHIVED_DAYFILE = "00300-Journal-26-09-01.md"

EXISTING_JOURNAL = (
    "# Plan 00461 — Journal 26-09-24\n"
    "\n"
    "_Scaffolded by `mkplan.bash`; timestamps in this file are UTC._\n"
    "\n"
    "> ```\n"
    "> ## HH:MM · category · REF   — optional short title\n"
    "> ```\n"
    "\n"
    "## 13:30 · action · — — plan scaffolded\n"
    "\n"
    "Plan 00461 created via `mkplan.bash`.\n"
)

NEW_ENTRY = "\n## 14:05 · finding · T1.1 — hand-typed\n\nThe clock was guessed.\n"


@pytest.fixture(autouse=True)
def mock_project_context() -> Any:
    """Handler instantiation reads ProjectContext; tests pin the root per case."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    """Reset the shared DaemonDataLayer singleton around every test."""
    from claude_code_hooks_daemon.core.data_layer import reset_data_layer

    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project with the scaffolder, the journal template and two journals."""
    plan_root = tmp_path / PLAN_DIR
    plan_root.mkdir(parents=True)
    (plan_root / "mkplan.bash").write_text(
        "#!/usr/bin/env bash\n# Usage:\n#   mkplan.bash --journal <plan-number> ...\n"
    )
    (plan_root / "_JOURNAL_TEMPLATE_.md").write_text("# Plan {{PLAN_NUMBER}} — Journal\n")

    live = plan_root / LIVE_FOLDER / "JOURNAL"
    live.mkdir(parents=True)
    (live / LIVE_DAYFILE).write_text(EXISTING_JOURNAL)
    (plan_root / LIVE_FOLDER / "PLAN.md").write_text("# Plan 00461: x\n")

    archived = plan_root / "Completed" / ARCHIVED_FOLDER / "JOURNAL"
    archived.mkdir(parents=True)
    (archived / ARCHIVED_DAYFILE).write_text(EXISTING_JOURNAL.replace("00461", "00300"))
    return tmp_path


@pytest.fixture
def handler(project: Path) -> PlanJournalGuardHandler:
    """Handler wired as the registry wires it, with the plan workflow on."""
    instance = PlanJournalGuardHandler()
    instance._workspace_root = project
    instance._track_plans_in_project = PLAN_DIR
    instance._plan_qa = None
    return instance


def _live_path(project: Path) -> Path:
    return project / PLAN_DIR / LIVE_FOLDER / "JOURNAL" / LIVE_DAYFILE


def _archived_path(project: Path) -> Path:
    return project / PLAN_DIR / "Completed" / ARCHIVED_FOLDER / "JOURNAL" / ARCHIVED_DAYFILE


def _edit(path: Path, old: str, new: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _write(path: Path, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _append_edit(path: Path) -> dict[str, Any]:
    last_line = "Plan 00461 created via `mkplan.bash`.\n"
    return _edit(path, last_line, last_line + NEW_ENTRY)


def _relative_live() -> str:
    return f"{PLAN_DIR}/{LIVE_FOLDER}/JOURNAL/{LIVE_DAYFILE}"


class TestInitialisation:
    def test_is_a_terminal_blocking_planning_handler(self) -> None:
        instance = PlanJournalGuardHandler()
        assert instance.name == "plan-journal-guard"
        assert instance.terminal is True
        assert "planning" in instance.tags
        assert "blocking" in instance.tags

    def test_declares_its_rule(self) -> None:
        rules = PlanJournalGuardHandler().get_rules()
        assert [rule.rule_id for rule in rules] == ["R-JOURNAL-HAND-WRITTEN-ENTRY"]


class TestEditWriteSurfaceIsDenied:
    """Task 1.1: the Edit/Write routes that are allowed today."""

    def test_edit_appending_an_entry_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _append_edit(_live_path(project))
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_write_creating_a_new_dayfile_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        new_file = _live_path(project).with_name("00461-Journal-26-09-25.md")
        hook_input = _write(new_file, "# Plan 00461 — Journal 26-09-25\n")
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_write_that_adds_an_entry_to_an_existing_dayfile_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _write(_live_path(project), EXISTING_JOURNAL + NEW_ENTRY)
        assert handler.matches(hook_input) is True

    def test_an_archived_plans_journal_is_covered_too(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        last_line = "Plan 00300 created via `mkplan.bash`.\n"
        hook_input = _edit(_archived_path(project), last_line, last_line + NEW_ENTRY)
        assert handler.matches(hook_input) is True
        reason = handler.handle(hook_input).reason or ""
        assert "--journal 300 " in reason


class TestEditWriteSurfaceIsAllowed:
    def test_deletion_only_edit_removing_conflict_markers_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """After a merge of two appends, deleting the markers adds no entry."""
        path = _live_path(project)
        conflicted = (
            EXISTING_JOURNAL
            + "<<<<<<< HEAD\n## 14:00 · action · — ours\n\nA.\n=======\n"
            + "## 14:02 · action · — theirs\n\nB.\n>>>>>>> branch\n"
        )
        path.write_text(conflicted)
        hook_input = _edit(path, "<<<<<<< HEAD\n", "")
        assert handler.matches(hook_input) is False

    def test_body_only_edit_adds_no_entry_and_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _edit(_live_path(project), "created via", "scaffolded via")
        assert handler.matches(hook_input) is False

    def test_an_entry_shaped_line_inside_a_fence_is_not_an_entry(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        last_line = "Plan 00461 created via `mkplan.bash`.\n"
        fenced = last_line + "\n```\n## 23:59 · quoted from a log\n```\n"
        assert handler.matches(_edit(_live_path(project), last_line, fenced)) is False

    def test_edit_whose_old_string_is_absent_is_left_to_the_tool(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _edit(_live_path(project), "not in the file", "x" + NEW_ENTRY)
        assert handler.matches(hook_input) is False

    def test_plan_md_is_not_a_journal(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        plan_md = project / PLAN_DIR / LIVE_FOLDER / "PLAN.md"
        assert handler.matches(_write(plan_md, "# Plan\n" + NEW_ENTRY)) is False

    def test_a_non_dayfile_inside_journal_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        notes = _live_path(project).with_name("notes.md")
        assert handler.matches(_write(notes, NEW_ENTRY)) is False

    def test_a_dayfile_in_another_checkout_is_not_judged(
        self, handler: PlanJournalGuardHandler, tmp_path: Path
    ) -> None:
        """The printed command would write to THIS checkout, so stay silent."""
        elsewhere = (
            tmp_path.parent / "other-checkout" / PLAN_DIR / LIVE_FOLDER / "JOURNAL" / LIVE_DAYFILE
        )
        assert handler.matches(_write(elsewhere, NEW_ENTRY)) is False


class TestBashSurfaceIsDenied:
    """Task 1.1: every Bash route that writes into a day-file."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cat >> {_relative_live()} <<'EOF'\n## 14:05 · action · —\n\nbody\nEOF",
            f"cat <<'EOF' >> {_relative_live()}\n## 14:05 · action · —\nEOF",
            f"echo '## 14:05 · action · —' | tee -a {_relative_live()}",
            f"printf '\\n## 14:05 · action · —\\n' >> {_relative_live()}",
            f"echo x > {_relative_live()}",
            f"cp untracked/scratch/entry.md {_relative_live()}",
            f"mv untracked/scratch/entry.md {_relative_live()}",
            f"dd if=untracked/scratch/entry.md of={_relative_live()}",
            f"git show HEAD:{_relative_live()} > {_relative_live()}",
            ("python3 -c \"open('" + _relative_live() + "', 'a').write('## 14:05 · action · —')\""),
            "python3 -c \"from pathlib import Path; Path('"
            + _relative_live()
            + "').write_text('x')\"",
            f"/usr/bin/python3 -c \"open('{_relative_live()}', 'a').write('x')\"",
            f"perl -pi -e 's/a/b/' {_relative_live()}",
            f"sed -i 's/a/b/' {_relative_live()}",
            f'bash -c "echo x >> {_relative_live()}"',
        ],
    )
    def test_hand_write_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        hook_input = _bash(command, project)
        assert handler.matches(hook_input) is True, command
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_absolute_path_is_denied(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        command = f"echo x >> {_live_path(project)}"
        assert handler.matches(_bash(command, project / "src")) is True

    def test_a_write_hidden_after_an_unrelated_git_segment_is_still_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        command = f"git status && cp untracked/scratch/e.md {_relative_live()}"
        assert handler.matches(_bash(command, project)) is True


class TestBashSurfaceIsAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            f"{PLAN_DIR}/mkplan.bash --journal 461 finding untracked/scratch/e.md --title 'x'",
            f"bash {PLAN_DIR}/mkplan.bash --journal 461 action untracked/scratch/e.md",
            f"git mv {PLAN_DIR}/{LIVE_FOLDER} {PLAN_DIR}/Completed/",
            f"git mv {_relative_live()} {PLAN_DIR}/{LIVE_FOLDER}/JOURNAL/00461-Journal-26-09-23.md",
            f"git add {_relative_live()} && git commit -m 'journal'",
            f"tail -n 40 {_relative_live()}",
            f"grep -n 'rate limit' {_relative_live()}",
            f"cat {_relative_live()} > untracked/scratch/copy.md",
            f"python3 -c \"print(open('{_relative_live()}').read())\"",
            f"sed -n '1,5p' {_relative_live()}",
            f"mkdir -p {PLAN_DIR}/{LIVE_FOLDER}/JOURNAL",
            f"echo x >> {PLAN_DIR}/{LIVE_FOLDER}/JOURNAL/notes.md",
            "echo 'no journal here' > untracked/scratch/x.md",
        ],
    )
    def test_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        assert handler.matches(_bash(command, project)) is False, command


class TestCommandShapes:
    """The per-stage reader: command words, program flags, unparseable input."""

    @pytest.mark.parametrize(
        "command",
        [
            f"FOO=1 python3 -c \"open('{_relative_live()}', 'a').write('x')\"",
            f"sudo sed -i 's/a/b/' {_relative_live()}",
            f"sudo -E sed -i 's/a/b/' {_relative_live()}",
            f"sed -i 's/a/b/' {_relative_live()} && echo $'it\\'s done'",
            f"sed --in-place 's/a/b/' {_relative_live()}",
            f'perl -ne \'open(my $f, ">>", "{_relative_live()}")\' x',
            f"node --eval \"require('fs').appendFileSync('{_relative_live()}', 'x')\"",
            f"awk '{{print > \"{_relative_live()}\"}}' untracked/scratch/body.md",
        ],
    )
    def test_is_denied(self, handler: PlanJournalGuardHandler, project: Path, command: str) -> None:
        assert handler.matches(_bash(command, project)) is True, command

    @pytest.mark.parametrize(
        "command",
        [
            f"awk 'NR>=1 && NR<=20' {_relative_live()}",
            f"env ; tail -n 5 {_relative_live()}",
            f"{PLAN_DIR}/mkplan.bash --journal 461 action untracked/scratch/e.md "
            f"&& tail -n 5 {_relative_live()}",
            f"ruby -w {_relative_live()}",
            f"echo x >> {PLAN_DIR}/JOURNAL/{LIVE_DAYFILE}",
            # An unterminated quote: bash refuses to run the command at all
            # ("unexpected EOF"), so nothing reaches the day-file.
            f"python3 -c \"open('{_relative_live()}', 'a').write('x')",
        ],
    )
    def test_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        assert handler.matches(_bash(command, project)) is False, command

    def test_home_relative_path_in_a_program_is_resolved(
        self, handler: PlanJournalGuardHandler, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(project))
        command = f"python3 -c \"open('~/{_relative_live()}', 'a').write('x')\""
        assert handler.matches(_bash(command, project)) is True

    def test_another_users_home_is_not_resolved(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        command = f"python3 -c \"open('~someone/{_relative_live()}', 'a').write('x')\""
        assert handler.matches(_bash(command, project)) is False

    def test_relative_path_without_cwd_cannot_be_placed(
        self, handler: PlanJournalGuardHandler
    ) -> None:
        command = f"python3 -c \"open('{_relative_live()}', 'a').write('x')\""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is False


class TestUnreadableState:
    def test_edit_of_a_missing_dayfile_is_left_to_the_tool(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        missing = _live_path(project).with_name("00461-Journal-26-09-25.md")
        assert handler.matches(_edit(missing, "x", "x" + NEW_ENTRY)) is False

    def test_edit_with_no_file_path_is_ignored(self, handler: PlanJournalGuardHandler) -> None:
        assert handler.matches({"tool_name": "Edit", "tool_input": {}}) is False

    def test_undecodable_dayfile_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        _live_path(project).write_bytes(b"\xff\xfe not utf-8")
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_unstattable_dayfile_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from claude_code_hooks_daemon.handlers.pre_tool_use import plan_journal_guard

        real = plan_journal_guard.path_is_file

        def unstattable_dayfile(path: Any, *, unreadable_means: Any) -> Any:
            if str(path).endswith(LIVE_DAYFILE):
                return unreadable_means
            return real(path, unreadable_means=unreadable_means)

        monkeypatch.setattr(plan_journal_guard, "path_is_file", unstattable_dayfile)
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_undecodable_scaffolder_stands_the_guard_down(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        (project / PLAN_DIR / "mkplan.bash").write_bytes(b"\xff\xfe --journal")
        assert handler.matches(_append_edit(_live_path(project))) is False


class TestDenyMessage:
    def test_names_the_exact_command_for_that_plan(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert f"{PLAN_DIR}/mkplan.bash --journal 461 " in reason

    def test_shows_the_two_step_body_file_pattern(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert "untracked/scratch/" in reason
        assert "Write tool" in reason

    def test_says_why(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert "UTC" in reason
        assert "40 minutes" in reason

    def test_bash_deny_names_the_command_too(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _bash(f"echo x >> {_relative_live()}", project)
        reason = handler.handle(hook_input).reason or ""
        assert f"{PLAN_DIR}/mkplan.bash --journal 461 " in reason

    def test_second_fire_is_terse_but_keeps_the_command(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _append_edit(_live_path(project))
        hook_input["transcript_path"] = "/tmp/transcript.jsonl"
        first = handler.handle(hook_input).reason or ""
        second = handler.handle(hook_input).reason or ""
        assert len(second) < len(first)
        assert "--journal 461 " in second


class TestGate:
    """Same condition as plan_number_helper: never name a tool that is not there."""

    def test_plan_workflow_disabled(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        handler._track_plans_in_project = None
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_scaffolder_absent(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        (project / PLAN_DIR / "mkplan.bash").unlink()
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_scaffolder_without_journal_mode(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """A client still on a pre-v3.66.0 scaffolder has no --journal to use."""
        (project / PLAN_DIR / "mkplan.bash").write_text("#!/usr/bin/env bash\necho old\n")
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_journal_template_absent(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        """`--journal` dies without the template, so it cannot be the remedy."""
        (project / PLAN_DIR / "_JOURNAL_TEMPLATE_.md").unlink()
        assert handler.matches(_append_edit(_live_path(project))) is False

    @pytest.mark.parametrize(("enabled", "mode"), [(False, "advise"), (True, "off")])
    def test_journalling_switched_off(
        self, handler: PlanJournalGuardHandler, project: Path, enabled: bool, mode: str
    ) -> None:
        policy = MagicMock()
        policy.journal.enabled = enabled
        policy.journal.mode = mode
        policy.journal.dir_name = "JOURNAL"
        handler._plan_qa = policy
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_a_non_default_journal_dir_stands_the_guard_down(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """`--journal` always writes into `JOURNAL/`, so it is no remedy for `LOG/`."""
        policy = MagicMock()
        policy.journal.enabled = True
        policy.journal.mode = "advise"
        policy.journal.dir_name = "LOG"
        handler._plan_qa = policy
        log_dir = project / PLAN_DIR / LIVE_FOLDER / "LOG"
        log_dir.mkdir()
        (log_dir / LIVE_DAYFILE).write_text(EXISTING_JOURNAL)
        assert handler.matches(_append_edit(log_dir / LIVE_DAYFILE)) is False
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_default_journal_policy_is_active(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        policy = MagicMock()
        policy.journal.enabled = True
        policy.journal.mode = "advise"
        policy.journal.dir_name = "JOURNAL"
        handler._plan_qa = policy
        assert handler.matches(_append_edit(_live_path(project))) is True

    def test_other_tools_are_ignored(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False

    def test_bash_without_a_command_is_ignored(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {}}) is False


class TestGuidanceAndProbes:
    def test_claude_md_names_the_tool_as_the_only_way(self) -> None:
        guidance = PlanJournalGuardHandler().get_claude_md() or ""
        assert "mkplan.bash --journal" in guidance
        assert "untracked/scratch/" in guidance

    def test_acceptance_probes_deny_a_hand_append_and_allow_the_tool(self) -> None:
        tests = PlanJournalGuardHandler().get_acceptance_tests()
        decisions = {test.expected_decision for test in tests}
        assert decisions == {Decision.DENY, Decision.ALLOW}
        allow = next(test for test in tests if test.expected_decision == Decision.ALLOW)
        assert "mkplan.bash --journal" in allow.command
