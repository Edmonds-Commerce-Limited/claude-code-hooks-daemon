"""``branch-reject digest [--mark-read]`` (Plan 00620 Task 2.3, RULINGS.md section 3 item 5).

The digest lists every removal, git refusal and keep record not yet marked read, flags a
removal whose branch still resolves at its recorded tip, and states the removal rate.
Listing writes nothing. ``--mark-read`` marks exactly what it printed, and the
watermark gates nothing. An unreadable ledger or state is exit 2, never "nothing new".
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.unit.core.test_branch_reject import _ledger_line, _tip, config, repo

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    KeepRecord,
    LedgerRefusal,
    RejectStore,
    append_ledger,
    append_refusal,
    new_id,
    read_ledger_entries,
)
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_reject_digest

__all__ = ["config", "repo"]


@pytest.fixture
def project(repo: Path) -> Path:
    (repo / ".claude" / "hooks-daemon").mkdir(parents=True)
    return repo


@pytest.fixture
def store(project: Path, config: BranchRejectConfig) -> RejectStore:
    return RejectStore(project / config.state_dir)


@pytest.fixture
def ledger(project: Path, config: BranchRejectConfig) -> Path:
    return project / config.ledger_path


def _run(
    project: Path, capsys: pytest.CaptureFixture[str], **overrides: Any
) -> tuple[int, str, str]:
    values: dict[str, Any] = {"project_root": project, "mark_read": False, "format": "json"}
    values.update(overrides)
    code = cmd_branch_reject_digest(argparse.Namespace(**values))
    out, err = capsys.readouterr()
    return code, out, err


def _keep(branch: str = "kept") -> KeepRecord:
    return KeepRecord(
        verdict_id=new_id(),
        branch=branch,
        tip="3" * 40,
        commits=("3" * 40,),
        reasons=("still needed",),
        recorded_at=time.time(),
    )


class TestListing:
    def test_nothing_recorded_lists_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = _run(project, capsys)
        assert code == 0
        data = json.loads(out)
        assert data["removals"] == []
        assert data["refusals"] == []
        assert data["keeps"] == []
        assert data["removals_in_window"] == 0
        assert data["reviewers_next"] == 1

    def test_a_removal_is_listed_with_its_restore_lines(
        self, project: Path, ledger: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        append_ledger(ledger, _ledger_line(branch="gone"))
        code, out, _ = _run(project, capsys)
        assert code == 0
        (removal,) = json.loads(out)["removals"]
        assert removal["branch"] == "gone"
        assert removal["still_present_at_tip"] is False
        assert removal["restore_commands"]

    def test_a_branch_still_at_its_recorded_tip_is_flagged(
        self, project: Path, ledger: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A crash between the ledger append and git's answer leaves exactly this."""
        append_ledger(ledger, replace(_ledger_line(branch="feat"), tip=_tip(project)))
        code, out, _ = _run(project, capsys)
        assert code == 0
        (removal,) = json.loads(out)["removals"]
        assert removal["still_present_at_tip"] is True
        _, text, _ = _run(project, capsys, format="text")
        assert "STILL PRESENT at its tip" in text

    def test_refusals_and_keeps_are_listed(
        self,
        project: Path,
        ledger: Path,
        store: RejectStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        line = _ledger_line(branch="locked")
        append_ledger(ledger, line)
        append_refusal(
            ledger,
            LedgerRefusal(
                branch="locked",
                tip=line.tip,
                verdict_ids=line.verdict_ids,
                detail="ref locked",
                refused_at=line.removed_at,
            ),
        )
        store.write_keep(_keep())
        code, out, _ = _run(project, capsys)
        assert code == 0
        data = json.loads(out)
        assert [r["branch"] for r in data["refusals"]] == ["locked"]
        assert [k["branch"] for k in data["keeps"]] == ["kept"]
        _, text, _ = _run(project, capsys, format="text")
        assert "locked" in text
        assert "kept" in text

    def test_listing_writes_nothing(
        self,
        project: Path,
        ledger: Path,
        store: RejectStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        append_ledger(ledger, _ledger_line(branch="gone"))
        before = ledger.read_bytes()
        _run(project, capsys)
        _run(project, capsys, format="text")
        assert ledger.read_bytes() == before
        assert not store.digest_path.exists()


class TestRate:
    def test_the_rate_line_says_when_the_route_is_refusing(
        self,
        project: Path,
        ledger: Path,
        config: BranchRejectConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        now = time.time()
        for _ in range(config.refuse_after):
            append_ledger(ledger, _ledger_line(branch="gone", removed_at=now - 60))
        code, out, _ = _run(project, capsys)
        assert code == 0
        data = json.loads(out)
        assert data["removals_in_window"] == config.refuse_after
        assert data["reviewers_next"] is None
        _, text, _ = _run(project, capsys, format="text")
        assert "refusing" in text


class TestMarkRead:
    def test_mark_read_hides_what_was_listed_and_keeps_the_ledger(
        self,
        project: Path,
        ledger: Path,
        store: RejectStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        append_ledger(ledger, _ledger_line(branch="gone"))
        store.write_keep(_keep())
        before = ledger.read_bytes()
        code, out, _ = _run(project, capsys, mark_read=True)
        assert code == 0
        assert [r["branch"] for r in json.loads(out)["removals"]] == ["gone"]
        assert ledger.read_bytes() == before
        _, again, _ = _run(project, capsys)
        data = json.loads(again)
        assert data["removals"] == []
        assert data["keeps"] == []
        assert data["last_marked_at"] is not None

    def test_a_later_entry_is_listed_after_a_mark(
        self, project: Path, ledger: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        append_ledger(ledger, _ledger_line(branch="first"))
        _run(project, capsys, mark_read=True)
        append_ledger(ledger, _ledger_line(branch="second"))
        _, out, _ = _run(project, capsys)
        assert [r["branch"] for r in json.loads(out)["removals"]] == ["second"]


class TestFailClosed:
    def test_a_damaged_ledger_is_exit_two(
        self, project: Path, ledger: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("{not json\n", encoding="utf-8")
        code, out, err = _run(project, capsys)
        assert code == 2
        assert out == ""
        assert "ERROR" in err

    def test_a_damaged_watermark_is_exit_two_and_mark_read_writes_nothing(
        self,
        project: Path,
        ledger: Path,
        store: RejectStore,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        append_ledger(ledger, _ledger_line(branch="gone"))
        store.digest_path.parent.mkdir(parents=True, exist_ok=True)
        store.digest_path.write_text("garbage", encoding="utf-8")
        code, _, err = _run(project, capsys, mark_read=True)
        assert code == 2
        assert "ERROR" in err
        assert store.digest_path.read_text(encoding="utf-8") == "garbage"
        assert len(read_ledger_entries(ledger)) == 1


class TestParser:
    def test_the_parser_wires_the_subcommand(self) -> None:
        args = build_parser().parse_args(["branch-reject", "digest", "--mark-read"])
        assert args.func is cmd_branch_reject_digest
        assert args.mark_read is True
        assert args.format == "text"
