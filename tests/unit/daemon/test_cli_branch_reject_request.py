"""``branch-reject request <branch>`` (Plan 00620 Task 2.2 item 3, RULINGS.md section 3).

The command classifies the branch exactly as ``delete-branch`` does, admits a review,
stores one request per reviewer and prints the reviewer type and the exact prompt. It
accepts no free text, never deletes and never touches the ledger.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit.core.test_branch_reject import _commit, _git, _tip, config, repo

from claude_code_hooks_daemon.config.models import BranchRejectConfig
from claude_code_hooks_daemon.core.branch_reject import (
    PROMPT_MARKER,
    REVIEWER_AGENT_TYPE,
    KeepRecord,
    RejectStore,
    new_id,
    prompt_digest,
)
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_reject_request

__all__ = ["config", "repo"]


@pytest.fixture
def project(repo: Path) -> Path:
    (repo / ".claude" / "hooks-daemon").mkdir(parents=True)
    return repo


@pytest.fixture
def store(project: Path, config: BranchRejectConfig) -> RejectStore:
    return RejectStore(project / config.state_dir)


def _args(repo: Path, **overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"project_root": repo, "branch": "feat", "format": "json"}
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _run(
    project: Path, capsys: pytest.CaptureFixture[str], **overrides: Any
) -> tuple[int, str, str]:
    code = cmd_branch_reject_request(_args(project, **overrides))
    out, err = capsys.readouterr()
    return code, out, err


class TestRequest:
    def test_an_unproven_branch_gets_one_stored_request(
        self, project: Path, store: RejectStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = _run(project, capsys)
        assert code == 0
        data = json.loads(out)
        assert data["reviewer_type"] == REVIEWER_AGENT_TYPE
        assert data["reviewers_required"] == 1
        (entry,) = data["requests"]
        assert entry["prompt"].startswith(f"{PROMPT_MARKER}{entry['nonce']}\n")
        stored = store.read_request(entry["nonce"])
        assert stored is not None
        assert stored.prompt_sha256 == prompt_digest(entry["prompt"])
        assert stored.tip == _tip(project)

    def test_the_text_form_prints_the_type_and_delimited_prompt(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _ = _run(project, capsys, format="text")
        assert code == 0
        assert f"subagent_type: {REVIEWER_AGENT_TYPE}" in out
        assert "----- BEGIN PROMPT 1 of 1 -----\n" + PROMPT_MARKER in out
        assert "\nEND-BRANCH-REJECT-VERDICT\n----- END PROMPT 1 of 1 -----" in out

    def test_it_deletes_nothing_and_writes_no_ledger(
        self, project: Path, config: BranchRejectConfig, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(project, capsys)
        assert _git(project, "for-each-ref", "refs/heads/feat").strip()
        assert not (project / config.ledger_path).exists()

    def test_a_merged_branch_is_refused_and_stores_nothing(
        self, project: Path, store: RejectStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git(project, "merge", "-q", "--no-ff", "-m", "merge feat", "feat")
        code, _, err = _run(project, capsys)
        assert code == 1
        assert "delete-branch" in err
        assert not (store.root / "requests").exists()

    def test_a_protected_branch_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _git(project, "switch", "-q", "-c", "other")
        _commit(project, "o.py", "o = 1\n", "other")
        code, _, err = _run(project, capsys, branch="main")
        assert code == 1
        assert "main" in err

    def test_a_keep_on_this_tip_is_refused(
        self, project: Path, store: RejectStore, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store.write_keep(
            KeepRecord(
                verdict_id=new_id(),
                branch="feat",
                tip=_tip(project),
                commits=(),
                reasons=("needed",),
                recorded_at=1.0,
            )
        )
        code, _, err = _run(project, capsys)
        assert code == 1
        assert "final" in err

    def test_a_missing_branch_is_refused(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, _, _ = _run(project, capsys, branch="absent")
        assert code == 1


class TestParser:
    def test_it_takes_one_branch_and_no_free_text(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["branch-reject", "request", "feat"])
        assert args.branch == "feat"
        assert args.func is cmd_branch_reject_request
        for extra in (["--reason", "obsolete"], ["feat2"]):
            with pytest.raises(SystemExit):
                parser.parse_args(["branch-reject", "request", "feat", *extra])
