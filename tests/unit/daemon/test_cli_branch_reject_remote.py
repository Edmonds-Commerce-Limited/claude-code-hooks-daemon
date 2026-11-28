"""``branch-reject request --remote-only`` and the remote no-value delete (ledger N763)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit.core.test_branch_reject import HOUR, _items, _reviewer
from tests.unit.core.test_branch_reject_remote import (
    PR,
    REMOTE,
    FakeGh,
    _git,
    _heads,
    _pr,
    _tip,
    origin_and_clone,
)

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.core import branch_reject_remote
from claude_code_hooks_daemon.core.branch_reject import (
    DECISION_NO_VALUE,
    DispatchRecord,
    RejectStore,
    Verdict,
    read_ledger,
)
from claude_code_hooks_daemon.daemon.cli import (
    build_parser,
    cmd_branch_reject_digest,
    cmd_branch_reject_request,
    cmd_delete_branch,
)

__all__ = ["origin_and_clone"]


@pytest.fixture
def project(origin_and_clone: tuple[Path, Path]) -> Path:
    work = origin_and_clone[1]
    (work / ".claude" / "hooks-daemon").mkdir(parents=True)
    return work


@pytest.fixture
def store(project: Path) -> RejectStore:
    return RejectStore(project / BranchesConfig().reject.state_dir)


def _gh(monkeypatch: pytest.MonkeyPatch, gh: FakeGh) -> None:
    monkeypatch.setattr(branch_reject_remote, "pr_runner", lambda _repo: gh)


def _request(project: Path, capsys: pytest.CaptureFixture[str], **extra: Any) -> tuple[int, str, str]:
    args = argparse.Namespace(
        project_root=project, branch="novel", format="json", remote_only=True, **extra
    )
    code = cmd_branch_reject_request(args)
    out, err = capsys.readouterr()
    return code, out, err


def _delete(project: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    args = argparse.Namespace(
        project_root=project,
        branches=["novel"],
        protected_ref=None,
        dry_run=False,
        format="text",
        remote_only=True,
    )
    code = cmd_delete_branch(args)
    out, err = capsys.readouterr()
    return code, out, err


def _verdict_for(store: RejectStore, nonce: str) -> None:
    request = store.read_request(nonce)
    assert request is not None
    reviewer = _reviewer()
    store.write_dispatch(
        DispatchRecord(
            nonce=nonce,
            session_id=reviewer.session_id,
            tool_use_id="toolu_x",
            agent_id=reviewer.agent_id,
        )
    )
    store.write_verdict(
        Verdict(
            verdict_id=nonce,
            nonce=nonce,
            branch=request.branch,
            tip=request.tip,
            default_sha=request.default_sha,
            inventory=request.inventory,
            items=_items(request.inventory, DECISION_NO_VALUE),
            overall=DECISION_NO_VALUE,
            issued_at=request.created_at,
            reviewer=reviewer,
            remote=request.remote,
        )
    )


def test_the_flag_is_parsed() -> None:
    args = build_parser().parse_args(["branch-reject", "request", "novel", "--remote-only"])
    assert args.remote_only is True
    assert build_parser().parse_args(["branch-reject", "request", "x"]).remote_only is False


def test_a_closed_pr_branch_gets_a_remote_scope_request(
    project: Path,
    store: RejectStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gh(monkeypatch, FakeGh([_pr(oid=_tip(project))]))
    code, out, err = _request(project, capsys)
    assert code == 0, err
    data = json.loads(out)
    assert (data["remote"], data["pr_number"], data["tip"]) == (REMOTE, PR, _tip(project))
    (entry,) = data["requests"]
    stored = store.read_request(entry["nonce"])
    assert stored is not None and stored.remote == REMOTE


def test_an_open_pr_is_refused_and_stores_nothing(
    project: Path,
    store: RejectStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gh(monkeypatch, FakeGh([_pr("OPEN", oid=_tip(project))]))
    code, _, err = _request(project, capsys)
    assert code == 1
    assert "open" in err
    assert not (store.root / "requests").exists()


def test_the_local_request_points_a_remote_only_branch_at_the_flag(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(
        project_root=project, branch="novel", format="json", remote_only=False
    )
    assert cmd_branch_reject_request(args) == 1
    assert "--remote-only" in capsys.readouterr().err


def test_delete_without_a_verdict_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _gh(monkeypatch, FakeGh([_pr(oid=_tip(project))]))
    code, _, _ = _delete(project, capsys)
    assert code == 1
    assert "refs/heads/novel" in _heads(project)


def test_a_no_value_verdict_unlocks_the_leased_remote_delete(
    project: Path,
    store: RejectStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tip = _tip(project)
    _gh(monkeypatch, FakeGh([_pr(oid=tip)]))
    code, out, err = _request(project, capsys)
    assert code == 0, err
    (entry,) = json.loads(out)["requests"]
    _verdict_for(store, entry["nonce"])
    code, out, err = _delete(project, capsys)
    assert code == 0, err
    assert "refs/heads/novel" not in _heads(project)
    assert f"git push {REMOTE} {tip}:refs/heads/novel" in out
    assert "recovery bundle" in out
    (line,) = read_ledger(project / BranchesConfig().reject.ledger_path)
    assert line.remote == REMOTE
    digest = argparse.Namespace(project_root=project, format="text", mark_read=False)
    assert cmd_branch_reject_digest(digest) == 0
    shown = capsys.readouterr().out
    assert f"REMOVED {REMOTE}/novel (remote)" in shown
    assert "STILL PRESENT" not in shown


def test_a_tip_moved_after_the_verdict_is_refused_by_the_cli(
    project: Path,
    store: RejectStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gh(monkeypatch, FakeGh([_pr(oid=_tip(project))]))
    code, out, _ = _request(project, capsys)
    assert code == 0
    (entry,) = json.loads(out)["requests"]
    _verdict_for(store, entry["nonce"])
    _git(project, "checkout", "-q", "-b", "novel", f"{REMOTE}/novel")
    _git(project, "commit", "-q", "--allow-empty", "-m", "after the verdict")
    _git(project, "push", "-q", REMOTE, "novel")
    _git(project, "checkout", "-q", "main")
    _git(project, "branch", "-q", "-D", "novel")
    _gh(monkeypatch, FakeGh([_pr(oid=_tip(project))]))
    code, _, _ = _delete(project, capsys)
    assert code == 1
    assert _tip(project) in _heads(project)


def test_an_expired_verdict_is_refused_by_the_cli(
    project: Path,
    store: RejectStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _gh(monkeypatch, FakeGh([_pr(oid=_tip(project))]))
    code, out, _ = _request(project, capsys)
    assert code == 0
    (entry,) = json.loads(out)["requests"]
    _verdict_for(store, entry["nonce"])
    lifetime = BranchesConfig().reject.verdict_lifetime_hours * HOUR
    real = branch_reject_remote.delete_rejected_remote

    def later(*args: Any, **kwargs: Any) -> Any:
        route = args[4]
        moved = type(route)(**{**route.__dict__, "now": route.now + lifetime + HOUR})
        return real(*args[:4], moved, *args[5:], **kwargs)

    monkeypatch.setattr(branch_reject_remote, "delete_rejected_remote", later)
    code, _, err = _delete(project, capsys)
    assert code == 1
    assert "expired" in err
    assert "refs/heads/novel" in _heads(project)
