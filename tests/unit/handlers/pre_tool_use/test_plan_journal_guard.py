"""Tests for PlanJournalGuardHandler (Plan 00461).

A journal entry reaches a plan's ``JOURNAL/`` day-file through
``mkplan.bash --journal`` and nothing else, because the tool reads the real UTC
clock and a hand-typed timestamp does not. Every route that wrote an entry by
hand in the session that prompted this plan, and every route the pre-merge
review found around the first version, is reproduced here and must be DENIED.

The allowances are just as load-bearing, because a guard that blocks the
remedy, an ordinary git operation or a read gets switched off:

* ``mkplan.bash --journal`` itself;
* ``git`` (``git mv`` of a plan folder into ``Completed/``, ``git add``);
* READING a day-file (``tail``, ``grep``, a read-only one-liner);
* an Edit that adds no line: a deletion (conflict markers after a merge), a
  reordering, or a same-line redaction.
"""

import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.plan_journal_guard import (
    PlanJournalGuardHandler,
)
from claude_code_hooks_daemon.utils.path_predicates import TextOrReason

PLAN_DIR = "CLAUDE/Plan"
LIVE_FOLDER = "00461-journal-entries-only"
ARCHIVED_FOLDER = "00300-old-work"
LIVE_DAYFILE = "00461-Journal-26-09-24.md"
ARCHIVED_DAYFILE = "00300-Journal-26-09-01.md"
WORKTREE = "untracked/worktrees/wt-a"
WORKTREE_FOLDER = "00500-worktree-plan"
WORKTREE_DAYFILE = "00500-Journal-26-09-24.md"
RULE_ID = "R-JOURNAL-HAND-WRITTEN-ENTRY"

LAST_LINE = "Plan 00461 created via `mkplan.bash`.\n"

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
    "\n" + LAST_LINE
)

NEW_ENTRY = "\n## 14:05 · finding · T1.1 — hand-typed\n\nThe clock was guessed.\n"

#: `<checkout>/untracked/scratch/journal-<N>-<yymmdd>-<hhmmss>-<4 hex>.md`
BODY_FILE_RE = r"untracked/scratch/journal-{number}-\d{{6}}-\d{{6}}-[0-9a-f]{{4}}\.md"


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


def _deploy_scaffolder(plan_root: Path) -> None:
    plan_root.mkdir(parents=True, exist_ok=True)
    (plan_root / "mkplan.bash").write_text(
        "#!/usr/bin/env bash\n# Usage:\n#   mkplan.bash --journal <plan-number> ...\n"
    )
    (plan_root / "_JOURNAL_TEMPLATE_.md").write_text("# Plan {{PLAN_NUMBER}} — Journal\n")


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """The main checkout plus one git worktree, each with its own plan tree."""
    root = tmp_path.resolve()
    plan_root = root / PLAN_DIR
    _deploy_scaffolder(plan_root)

    live = plan_root / LIVE_FOLDER / "JOURNAL"
    live.mkdir(parents=True)
    (live / LIVE_DAYFILE).write_text(EXISTING_JOURNAL)
    (plan_root / LIVE_FOLDER / "PLAN.md").write_text("# Plan 00461: x\n")

    archived = plan_root / "Completed" / ARCHIVED_FOLDER / "JOURNAL"
    archived.mkdir(parents=True)
    (archived / ARCHIVED_DAYFILE).write_text(EXISTING_JOURNAL.replace("00461", "00300"))

    worktree_plan_root = root / WORKTREE / PLAN_DIR
    _deploy_scaffolder(worktree_plan_root)
    worktree_journal = worktree_plan_root / WORKTREE_FOLDER / "JOURNAL"
    worktree_journal.mkdir(parents=True)
    (worktree_journal / WORKTREE_DAYFILE).write_text(EXISTING_JOURNAL.replace("00461", "00500"))

    scratch = root / "untracked" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / "journal.patch").write_text(
        f"--- a/{_relative_live()}\n+++ b/{_relative_live()}\n@@ -1 +1,2 @@\n x\n+y\n"
    )
    (scratch / "plan.patch").write_text(
        f"--- a/{PLAN_DIR}/{LIVE_FOLDER}/PLAN.md\n+++ b/{PLAN_DIR}/{LIVE_FOLDER}/PLAN.md\n"
    )
    return root


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


def _worktree_path(project: Path) -> Path:
    return project / WORKTREE / PLAN_DIR / WORKTREE_FOLDER / "JOURNAL" / WORKTREE_DAYFILE


def _edit(path: Path, old: str, new: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": old, "new_string": new},
    }


def _write(path: Path, content: str) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _append_edit(
    path: Path, addition: str = NEW_ENTRY, last_line: str = LAST_LINE
) -> dict[str, Any]:
    return _edit(path, last_line, last_line + addition)


def _relative_live() -> str:
    return f"{PLAN_DIR}/{LIVE_FOLDER}/JOURNAL/{LIVE_DAYFILE}"


def _live_journal_dir() -> str:
    return f"{PLAN_DIR}/{LIVE_FOLDER}/JOURNAL"


class TestInitialisation:
    def test_is_a_terminal_blocking_planning_handler(self) -> None:
        instance = PlanJournalGuardHandler()
        assert instance.name == "plan-journal-guard"
        assert instance.terminal is True
        assert "planning" in instance.tags
        assert "blocking" in instance.tags

    def test_declares_its_rule(self) -> None:
        rules = PlanJournalGuardHandler().get_rules()
        assert [rule.rule_id for rule in rules] == [RULE_ID]


class TestEditWriteSurfaceIsDenied:
    def test_edit_appending_an_entry_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _append_edit(_live_path(project))
        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY

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
        assert handler.matches(_write(_live_path(project), EXISTING_JOURNAL + NEW_ENTRY)) is True

    def test_an_archived_plans_journal_is_covered_too(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        last_line = "Plan 00300 created via `mkplan.bash`.\n"
        hook_input = _append_edit(_archived_path(project), last_line=last_line)
        assert handler.matches(hook_input) is True
        assert "--journal 300 " in (handler.handle(hook_input).reason or "")

    @pytest.mark.parametrize(
        "addition",
        [
            "\n##  14:30 · finding · — two spaces\n",
            "\n##\t14:30 · finding · — a tab\n",
            "\n### 14:30 · finding · — a level-3 heading\n",
            "\n ## 14:30 · finding · — a leading space\n",
            "\n## 9:30 · finding · — one-digit hour\n",
            "\n## [14:30] finding\n",
            "\n## finding — no time at all\n",
            "\n**14:30 · finding**\n",
            "\n```\n## 14:30 · finding · — after an unclosed fence\n",
            "Addendum: the clock was wrong, it was 09:11.\n",
        ],
    )
    def test_any_added_line_is_denied_whatever_its_shape(
        self, handler: PlanJournalGuardHandler, project: Path, addition: str
    ) -> None:
        """M1: text appended under the last entry inherits its stamp."""
        assert handler.matches(_append_edit(_live_path(project), addition)) is True, addition

    def test_a_write_adding_an_untimed_paragraph_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        content = EXISTING_JOURNAL + "Addendum: one more thing.\n"
        assert handler.matches(_write(_live_path(project), content)) is True


class TestEditWriteSurfaceIsAllowed:
    def test_deletion_only_edit_removing_conflict_markers_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """After a merge of two appends, deleting the markers adds no line."""
        path = _live_path(project)
        path.write_text(
            EXISTING_JOURNAL
            + "<<<<<<< HEAD\n## 14:00 · action · — ours\n\nA.\n=======\n"
            + "## 14:02 · action · — theirs\n\nB.\n>>>>>>> branch\n"
        )
        assert handler.matches(_edit(path, "<<<<<<< HEAD\n", "")) is False

    def test_reordering_two_entries_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        path = _live_path(project)
        first = "## 14:02 · action · — theirs\n\nB.\n"
        second = "## 14:00 · action · — ours\n\nA.\n"
        path.write_text(EXISTING_JOURNAL + "\n" + first + "\n" + second)
        hook_input = _edit(path, first + "\n" + second, second + "\n" + first)
        assert handler.matches(hook_input) is False

    def test_same_line_redaction_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _edit(_live_path(project), "created via", "scaffolded via")
        assert handler.matches(hook_input) is False

    def test_a_same_count_heading_rewrite_passes_to_the_append_only_check(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """m4, by design: a rewrite adds no line, so it is `journal-append-only`'s."""
        content = EXISTING_JOURNAL.replace(
            "## 13:30 · action · — — plan scaffolded", "## 15:00 · finding · — replaced"
        )
        assert handler.matches(_write(_live_path(project), content)) is False

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

    def test_a_dayfile_outside_the_project_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        elsewhere = project.parent / "unrelated" / PLAN_DIR / LIVE_FOLDER / "JOURNAL" / LIVE_DAYFILE
        assert handler.matches(_write(elsewhere, NEW_ENTRY)) is False


class TestWorktreeJournals:
    """B1: sub-agents in a worktree send their hooks to the MAIN daemon."""

    def test_an_edit_to_a_worktree_dayfile_is_denied_naming_that_checkouts_script(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        last_line = "Plan 00500 created via `mkplan.bash`.\n"
        hook_input = _append_edit(_worktree_path(project), last_line=last_line)

        assert handler.matches(hook_input) is True
        reason = handler.handle(hook_input).reason or ""
        worktree_root = project / WORKTREE
        assert f"{worktree_root}/{PLAN_DIR}/mkplan.bash --journal 500 " in reason
        assert re.search(
            re.escape(str(worktree_root)) + "/" + BODY_FILE_RE.format(number=500), reason
        )

    def test_a_relative_bash_append_from_the_worktree_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        relative = f"{PLAN_DIR}/{WORKTREE_FOLDER}/JOURNAL/{WORKTREE_DAYFILE}"
        hook_input = _bash(f"echo '## 14:30' >> {relative}", project / WORKTREE)
        assert handler.matches(hook_input) is True

    def test_an_absolute_bash_append_into_the_worktree_is_denied(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        hook_input = _bash(f"echo '## 14:30' >> {_worktree_path(project)}", project)
        assert handler.matches(hook_input) is True

    def test_a_worktree_without_the_scaffolder_stands_down(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        (project / WORKTREE / PLAN_DIR / "mkplan.bash").unlink()
        last_line = "Plan 00500 created via `mkplan.bash`.\n"
        assert handler.matches(_append_edit(_worktree_path(project), last_line=last_line)) is False


class TestBashSurfaceIsDenied:
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
            "python3 -c \"open('" + _relative_live() + "', 'a').write('## 14:05 · action · —')\"",
            "python3 -c \"from pathlib import Path; Path('"
            + _relative_live()
            + "').write_text('x')\"",
            f"python3 -c \"open('{_relative_live()}', mode='w').write('x')\"",
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


class TestUnplaceableDestinationsFailClosed:
    """M2: a destination the resolver cannot place is denied if it names a journal."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cd {_live_journal_dir()} && cat >> {LIVE_DAYFILE} <<'EOF'\n## 14:05\nEOF",
            f"cd {_live_journal_dir()}; echo x >> {LIVE_DAYFILE}",
            f"(cd {_live_journal_dir()} && echo x >> {LIVE_DAYFILE})",
            f"pushd {_live_journal_dir()} && echo x >> {LIVE_DAYFILE}",
            f"cat >> {_live_journal_dir()}/00461-Journal-$(date -u +%y-%m-%d).md <<'EOF'\nx\nEOF",
            f"echo x >> {_live_journal_dir()}/00461-Journal-`date -u +%y-%m-%d`.md",
            f"echo x >> {_live_journal_dir()}/*.md",
            f"echo x >> $PLANS/{LIVE_FOLDER}/JOURNAL/{LIVE_DAYFILE}",
            f'cd {_live_journal_dir()} && echo x >> "$F"',
        ],
    )
    def test_is_denied(self, handler: PlanJournalGuardHandler, project: Path, command: str) -> None:
        assert handler.matches(_bash(command, project)) is True, command

    def test_the_deny_still_names_the_plan(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        command = (
            f"cat >> {_live_journal_dir()}/00461-Journal-$(date -u +%y-%m-%d).md <<'EOF'\nx\nEOF"
        )
        reason = handler.handle(_bash(command, project)).reason or ""
        assert f"{project}/{PLAN_DIR}/mkplan.bash --journal 461 " in reason

    def test_an_absolute_cd_names_that_checkouts_script(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        worktree_journal = _worktree_path(project).parent
        command = f'cd {worktree_journal} && echo x >> "$F"'
        reason = handler.handle(_bash(command, project)).reason or ""
        assert f"{project / WORKTREE}/{PLAN_DIR}/mkplan.bash --journal 500 " in reason

    def test_without_a_cwd_the_main_checkout_is_named(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        command = f"echo x >> {_live_journal_dir()}/00461-Journal-$(date -u +%y-%m-%d).md"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        reason = handler.handle(hook_input).reason or ""
        assert f"{project}/{PLAN_DIR}/mkplan.bash --journal 461 " in reason

    def test_an_unnamed_plan_is_a_placeholder(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        command = f'cd {PLAN_DIR}/JOURNAL && echo x >> "$F"'
        reason = handler.handle(_bash(command, project)).reason or ""
        assert "--journal <plan-number> <category> " in reason

    @pytest.mark.parametrize(
        "command",
        [
            f"cd {_live_journal_dir()} && tail -n 5 {LIVE_DAYFILE}",
            "cd untracked/scratch && echo x > note.md",
            f"ls {_live_journal_dir()}/*.md > untracked/scratch/list.txt",
            "echo x > untracked/scratch/$NAME.md",
            f"ls {_live_journal_dir()} > untracked/scratch/$NAME.txt",
        ],
    )
    def test_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        assert handler.matches(_bash(command, project)) is False, command

    def test_an_absolute_destination_after_cd_is_placed_not_failed_closed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        output = project / "untracked" / "scratch" / "n.txt"
        command = f"cd {_live_journal_dir()} && grep -c x {LIVE_DAYFILE} > {output}"
        assert handler.matches(_bash(command, project)) is False


class TestWrappersAndOtherWriters:
    """m1: the writer behind a wrapper, stdin program, patch or link."""

    @pytest.mark.parametrize(
        "command",
        [
            f'timeout 5 bash -c "echo x >> {_relative_live()}"',
            f"nohup sh -c 'echo x >> {_relative_live()}'",
            f"nice -n 5 sed -i 's/a/b/' {_relative_live()}",
            f"stdbuf -oL sed -i 's/a/b/' {_relative_live()}",
            f"time sed -i 's/a/b/' {_relative_live()}",
            f"uv run python -c \"open('{_relative_live()}', 'a').write('x')\"",
            f"poetry run python -c \"open('{_relative_live()}', 'a').write('x')\"",
            f"python3 - <<'EOF'\nopen('{_relative_live()}', 'a').write('x')\nEOF",
            f"python3 <<EOF\nopen('{_relative_live()}', 'a').write('x')\nEOF",
            f"awk -i inplace '{{print}}' {_relative_live()}",
            f"gawk -i inplace -v x=1 '{{print}}' {_relative_live()}",
            "git apply untracked/scratch/journal.patch",
            "patch -p1 < untracked/scratch/journal.patch",
            "patch -p1 -i untracked/scratch/journal.patch",
            f"ln -sf /tmp/x {_relative_live()}",
            f"rsync untracked/scratch/x.md {_relative_live()}",
            f"echo x | sponge -a {_relative_live()}",
        ],
    )
    def test_is_denied(self, handler: PlanJournalGuardHandler, project: Path, command: str) -> None:
        assert handler.matches(_bash(command, project)) is True, command

    def test_a_patch_that_touches_no_journal_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        assert handler.matches(_bash("git apply untracked/scratch/plan.patch", project)) is False


class TestReadsAreNotDenied:
    """m2: a write signal elsewhere in a program does not make a read a write."""

    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c \"print(open('{_relative_live()}').read())\"",
            f"python3 -c \"print(open('{_relative_live()}').read().count('a'))\"",
            f"python3 -c \"import sys; sys.stdout.write(open('{_relative_live()}').read())\"",
            f"python3 -c \"print(len(open('{_relative_live()}').read()) > 3)\"",
            f'bash -c "wc -l {_relative_live()} > untracked/scratch/n.txt"',
            f"perl -Ilib script.pl {_relative_live()}",
            f"perl -Mlib=x script.pl {_relative_live()}",
            f"awk 'NR>=1 && NR<=20' {_relative_live()}",
            f"sed -n '1,5p' {_relative_live()}",
            f"cat > untracked/scratch/notes.md <<EOF\npython3 -c \"open('{_relative_live()}', 'a').write('x')\"\nEOF",
            f"cat > untracked/scratch/notes.md <<'EOF'\necho x >> {_relative_live()}\nEOF",
        ],
    )
    def test_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        assert handler.matches(_bash(command, project)) is False, command


class TestBashSurfaceIsAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            f"{PLAN_DIR}/mkplan.bash --journal 461 finding untracked/scratch/e.md --title 'x'",
            f"bash {PLAN_DIR}/mkplan.bash --journal 461 action untracked/scratch/e.md",
            f"{PLAN_DIR}/mkplan.bash --journal 461 action untracked/scratch/e.md "
            f"&& tail -n 5 {_relative_live()}",
            f"git mv {PLAN_DIR}/{LIVE_FOLDER} {PLAN_DIR}/Completed/",
            f"git mv {_relative_live()} {_live_journal_dir()}/00461-Journal-26-09-23.md",
            f"git add {_relative_live()} && git commit -m 'journal'",
            f"tail -n 40 {_relative_live()}",
            f"grep -n 'rate limit' {_relative_live()}",
            f"cat {_relative_live()} > untracked/scratch/copy.md",
            f"mkdir -p {_live_journal_dir()}",
            f"echo x >> {_live_journal_dir()}/notes.md",
            f"echo x >> {PLAN_DIR}/JOURNAL/{LIVE_DAYFILE}",
            f"env ; tail -n 5 {_relative_live()}",
            f"ruby -w {_relative_live()}",
            "echo 'no journal here' > untracked/scratch/x.md",
            # An unterminated quote: bash refuses to run the command at all.
            f"python3 -c \"open('{_relative_live()}', 'a').write('x')",
        ],
    )
    def test_is_allowed(
        self, handler: PlanJournalGuardHandler, project: Path, command: str
    ) -> None:
        assert handler.matches(_bash(command, project)) is False, command


class TestCommandShapes:
    @pytest.mark.parametrize(
        "command",
        [
            f"FOO=1 python3 -c \"open('{_relative_live()}', 'a').write('x')\"",
            f"sudo sed -i 's/a/b/' {_relative_live()}",
            f"sudo -E sed -i 's/a/b/' {_relative_live()}",
            f"sed -i 's/a/b/' {_relative_live()} && echo $'it\\'s done'",
            f"sed --in-place 's/a/b/' {_relative_live()}",
            f"sed -i.bak 's/a/b/' {_relative_live()}",
            f"env python3 -c \"open('{_relative_live()}', 'a').write('x')\"",
            f'perl -ne \'open(my $f, ">>", "{_relative_live()}")\' x',
            f"ruby -e \"File.write('{_relative_live()}', 'x')\"",
            f"node --eval \"require('fs').appendFileSync('{_relative_live()}', 'x')\"",
            f"awk '{{print > \"{_relative_live()}\"}}' untracked/scratch/body.md",
        ],
    )
    def test_is_denied(self, handler: PlanJournalGuardHandler, project: Path, command: str) -> None:
        assert handler.matches(_bash(command, project)) is True, command

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
        assert handler.matches({"tool_name": "Bash", "tool_input": {"command": command}}) is False


class TestUnreadableState:
    def test_edit_of_a_missing_dayfile_is_left_to_the_tool(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        missing = _live_path(project).with_name("00461-Journal-26-09-25.md")
        assert handler.matches(_edit(missing, "x", "x" + NEW_ENTRY)) is False

    def test_edit_with_no_file_path_is_ignored(self, handler: PlanJournalGuardHandler) -> None:
        assert handler.matches({"tool_name": "Edit", "tool_input": {}}) is False

    def test_a_stray_undecodable_byte_does_not_blind_the_guard(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        _live_path(project).write_bytes(b"\xff\n" + EXISTING_JOURNAL.encode("utf-8"))
        assert handler.matches(_append_edit(_live_path(project))) is True

    def test_unreadable_dayfile_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Edit tool meets the same error itself, so there is nothing to count."""
        _refuse_to_read(handler, monkeypatch, LIVE_DAYFILE)
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_unstattable_dayfile_is_not_judged(
        self, handler: PlanJournalGuardHandler, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(handler, "_file_state", lambda path: None)
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_unreadable_scaffolder_stands_the_guard_down(
        self, handler: PlanJournalGuardHandler, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unable to confirm the remedy exists, the guard does not name it."""
        _refuse_to_read(handler, monkeypatch, "mkplan.bash")
        assert handler.matches(_append_edit(_live_path(project))) is False


def _refuse_to_read(
    handler: PlanJournalGuardHandler, monkeypatch: pytest.MonkeyPatch, basename: str
) -> None:
    """Make one file unreadable through the handler's read seam, as EACCES would.

    A seam rather than chmod: the suite may run as root, which reads a mode-000
    file regardless.
    """
    real = handler._read_text

    def refusing(path: Path) -> TextOrReason:
        if path.name == basename:
            return TextOrReason(reason="[Errno 13] Permission denied")
        return real(path)

    monkeypatch.setattr(handler, "_read_text", refusing)


class TestDenyMessage:
    def test_names_the_rule(self, handler: PlanJournalGuardHandler, project: Path) -> None:
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert RULE_ID in reason

    def test_names_the_exact_command_with_absolute_paths(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """m7: a relative command fails from a cwd that has moved."""
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert f"{project}/{PLAN_DIR}/mkplan.bash --journal 461 " in reason
        assert re.search(re.escape(str(project)) + "/" + BODY_FILE_RE.format(number=461), reason)

    def test_each_deny_prints_a_fresh_body_file(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """M3: a fixed name trips the clobber guard on the second entry."""
        pattern = re.escape(str(project)) + "/" + BODY_FILE_RE.format(number=461)
        first = re.search(pattern, handler.handle(_append_edit(_live_path(project))).reason or "")
        second = re.search(pattern, handler.handle(_append_edit(_live_path(project))).reason or "")
        assert first is not None and second is not None
        assert first.group(0) != second.group(0)

    def test_first_fire_carries_the_rules_teaching_text(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        (rule,) = handler.get_rules()
        reason = handler.handle(_append_edit(_live_path(project))).reason or ""
        assert rule.verbose in reason

    def test_bash_deny_names_the_command_too(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        reason = handler.handle(_bash(f"echo x >> {_relative_live()}", project)).reason or ""
        assert f"{project}/{PLAN_DIR}/mkplan.bash --journal 461 " in reason

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
        handler._plan_qa = _policy(enabled=enabled, mode=mode)
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_a_non_default_journal_dir_stands_the_guard_down(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        """`--journal` always writes into `JOURNAL/`, so it is no remedy for `LOG/`."""
        handler._plan_qa = _policy(dir_name="LOG")
        log_dir = project / PLAN_DIR / LIVE_FOLDER / "LOG"
        log_dir.mkdir()
        (log_dir / LIVE_DAYFILE).write_text(EXISTING_JOURNAL)
        assert handler.matches(_append_edit(log_dir / LIVE_DAYFILE)) is False
        assert handler.matches(_append_edit(_live_path(project))) is False

    def test_default_journal_policy_is_active(
        self, handler: PlanJournalGuardHandler, project: Path
    ) -> None:
        handler._plan_qa = _policy()
        assert handler.matches(_append_edit(_live_path(project))) is True

    def test_other_tools_are_ignored(self, handler: PlanJournalGuardHandler) -> None:
        assert handler.matches({"tool_name": "Read", "tool_input": {}}) is False

    def test_bash_without_a_command_is_ignored(self, handler: PlanJournalGuardHandler) -> None:
        assert handler.matches({"tool_name": "Bash", "tool_input": {}}) is False


class TestStandingDownIsLogged:
    """m3: a guard that switches itself off must say so, once."""

    @pytest.mark.parametrize(
        ("break_it", "expected"),
        [
            (
                lambda root: (root / PLAN_DIR / "_JOURNAL_TEMPLATE_.md").unlink(),
                "_JOURNAL_TEMPLATE_",
            ),
            (lambda root: (root / PLAN_DIR / "mkplan.bash").unlink(), "mkplan.bash"),
            (
                lambda root: (root / PLAN_DIR / "mkplan.bash").write_text("echo old\n"),
                "--journal",
            ),
        ],
    )
    def test_a_missing_remedy_is_logged_once(
        self,
        handler: PlanJournalGuardHandler,
        project: Path,
        caplog: pytest.LogCaptureFixture,
        break_it: Any,
        expected: str,
    ) -> None:
        break_it(project)
        with caplog.at_level(logging.INFO):
            handler.matches(_append_edit(_live_path(project)))
            handler.matches(_append_edit(_live_path(project)))
        messages = [
            r.getMessage() for r in caplog.records if "plan_journal_guard" in r.getMessage()
        ]
        assert len(messages) == 1, messages
        assert expected in messages[0]
        assert "inert" in messages[0]

    @pytest.mark.parametrize(
        "policy_kwargs", [{"enabled": False}, {"mode": "off"}, {"dir_name": "LOG"}]
    )
    def test_a_policy_switch_off_is_logged_once(
        self,
        handler: PlanJournalGuardHandler,
        project: Path,
        caplog: pytest.LogCaptureFixture,
        policy_kwargs: dict[str, Any],
    ) -> None:
        handler._plan_qa = _policy(**policy_kwargs)
        with caplog.at_level(logging.INFO):
            handler.matches(_append_edit(_live_path(project)))
            handler.matches(_append_edit(_live_path(project)))
        messages = [
            r.getMessage() for r in caplog.records if "plan_journal_guard" in r.getMessage()
        ]
        assert len(messages) == 1, messages
        assert "inert" in messages[0]


def _policy(enabled: bool = True, mode: str = "advise", dir_name: str = "JOURNAL") -> MagicMock:
    policy = MagicMock()
    policy.journal.enabled = enabled
    policy.journal.mode = mode
    policy.journal.dir_name = dir_name
    return policy


class TestGuidanceAndProbes:
    def test_claude_md_names_the_tool_as_the_only_way(self) -> None:
        guidance = PlanJournalGuardHandler().get_claude_md() or ""
        assert "mkplan.bash --journal" in guidance
        assert "untracked/scratch/" in guidance

    def test_claude_md_states_when_the_guard_is_inert(self) -> None:
        """m3: resident guidance must not promise a guard that may be off."""
        guidance = PlanJournalGuardHandler().get_claude_md() or ""
        assert "_JOURNAL_TEMPLATE_.md" in guidance
        assert "inert" in guidance

    def test_acceptance_probes_deny_a_hand_append_and_allow_the_tool(self) -> None:
        tests = PlanJournalGuardHandler().get_acceptance_tests()
        decisions = {test.expected_decision for test in tests}
        assert decisions == {Decision.DENY, Decision.ALLOW}
        allow = next(test for test in tests if test.expected_decision == Decision.ALLOW)
        assert "mkplan.bash --journal" in allow.command
