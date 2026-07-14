"""Tests for the ``journal-append-only`` EDIT check (Plan 00163).

Journals are an append-only log: an edit must only ADD to the end. The check
compares the pre-edit on-disk content (``file_content_before``) with the
would-be content on a trailing-newline-normalised prefix test. Creation and
pure append are clean; a shrink or an earlier-history rewrite ADVISE (forever
advisory — Decision 4).
"""

from pathlib import Path

from claude_code_hooks_daemon.plan_qa.checks import journal_append_only
from claude_code_hooks_daemon.plan_qa.types import CheckContext, Level, Stage

_BEFORE = "# Journal\n\n## 09:00 · action · —\n\nfirst entry\n"
_APPEND = _BEFORE + "\n## 10:00 · finding · —\n\nsecond entry\n"


def _ctx(
    *,
    before: str | None,
    after: str,
    basename: str = "00163-Journal-26-07-14.md",
    journal_enabled: bool = True,
    journal_mode: str = "advise",
) -> CheckContext:
    root = Path("/repo")
    file_path = root / "CLAUDE" / "Plan" / "00163-thing" / "JOURNAL" / basename
    return CheckContext(
        project_root=root,
        plan_dir_rel="CLAUDE/Plan",
        file_path=file_path,
        file_content=after,
        file_content_before=before,
        file_exists_before=before is not None,
        journal_enabled=journal_enabled,
        journal_mode=journal_mode,
    )


class TestSpec:
    def test_registered_edit_advise(self) -> None:
        spec = journal_append_only.CHECK
        assert spec.check_id == "journal-append-only"
        assert spec.stage == Stage.EDIT
        assert spec.level == Level.ADVISE


class TestRun:
    def test_creation_is_clean(self) -> None:
        assert journal_append_only.CHECK.run(_ctx(before=None, after=_BEFORE)) == []

    def test_pure_append_is_clean(self) -> None:
        assert journal_append_only.CHECK.run(_ctx(before=_BEFORE, after=_APPEND)) == []

    def test_trailing_newline_difference_tolerated(self) -> None:
        # A single trailing-newline delta is not a history rewrite.
        assert journal_append_only.CHECK.run(_ctx(before=_BEFORE, after=_BEFORE.rstrip("\n"))) == []

    def test_shrink_advises_truncation(self) -> None:
        findings = journal_append_only.CHECK.run(_ctx(before=_APPEND, after=_BEFORE))
        assert len(findings) == 1
        assert findings[0].level == Level.ADVISE
        assert "shrink" in findings[0].message.lower() or "remov" in findings[0].message.lower()

    def test_earlier_rewrite_advises(self) -> None:
        rewritten = _BEFORE.replace("first entry", "EDITED first entry") + "\n## 10:00\n\nx\n"
        findings = journal_append_only.CHECK.run(_ctx(before=_BEFORE, after=rewritten))
        assert len(findings) == 1
        assert "rewrite" in findings[0].message.lower() or "history" in findings[0].message.lower()

    def test_block_mode_still_advises(self) -> None:
        # Append-only stays advisory forever, even under mode: block.
        findings = journal_append_only.CHECK.run(
            _ctx(before=_APPEND, after=_BEFORE, journal_mode="block")
        )
        assert findings[0].level == Level.ADVISE

    def test_non_journal_ignored(self) -> None:
        root = Path("/repo")
        ctx = CheckContext(
            project_root=root,
            plan_dir_rel="CLAUDE/Plan",
            file_path=root / "CLAUDE" / "Plan" / "00163-thing" / "PLAN.md",
            file_content="new",
            file_content_before="old",
            journal_enabled=True,
        )
        assert journal_append_only.CHECK.run(ctx) == []

    def test_disabled_ignored(self) -> None:
        assert (
            journal_append_only.CHECK.run(
                _ctx(before=_APPEND, after=_BEFORE, journal_enabled=False)
            )
            == []
        )
