"""The CI base lookup: the newest main run of qa.yml that reached a verdict.

GitHub keeps one PENDING run per concurrency group, so a run superseded while
pending is cancelled and never tests its commit. The next run must therefore
diff from the last commit that WAS tested (success or failure), not from the
sha before its own push.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "last_verdict_sha.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("last_verdict_sha", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["last_verdict_sha"] = module
    spec.loader.exec_module(module)
    return module


last_verdict_sha = _load()


def _run(sha: str, conclusion: str | None, started: str, branch: str = "main") -> dict[str, Any]:
    return {
        "head_sha": sha,
        "head_branch": branch,
        "conclusion": conclusion,
        "run_started_at": started,
    }


class TestPickVerdictSha:
    """Selection over the workflow-runs payload."""

    def test_newest_success_wins(self) -> None:
        runs = [
            _run("a" * 40, "success", "2026-09-30T10:00:00Z"),
            _run("b" * 40, "success", "2026-09-30T11:00:00Z"),
        ]
        assert last_verdict_sha.pick_verdict_sha(runs) == "b" * 40

    def test_failure_is_a_verdict(self) -> None:
        runs = [
            _run("a" * 40, "success", "2026-09-30T10:00:00Z"),
            _run("b" * 40, "failure", "2026-09-30T11:00:00Z"),
        ]
        assert last_verdict_sha.pick_verdict_sha(runs) == "b" * 40

    @pytest.mark.parametrize("conclusion", ["cancelled", "skipped", None, "timed_out"])
    def test_runs_that_did_not_reach_a_verdict_are_passed_over(
        self, conclusion: str | None
    ) -> None:
        runs = [
            _run("a" * 40, "success", "2026-09-30T10:00:00Z"),
            _run("b" * 40, conclusion, "2026-09-30T11:00:00Z"),
        ]
        assert last_verdict_sha.pick_verdict_sha(runs) == "a" * 40

    def test_other_branches_are_ignored(self) -> None:
        runs = [
            _run("a" * 40, "success", "2026-09-30T10:00:00Z"),
            _run("b" * 40, "success", "2026-09-30T11:00:00Z", branch="feature"),
        ]
        assert last_verdict_sha.pick_verdict_sha(runs) == "a" * 40

    def test_order_of_the_payload_does_not_matter(self) -> None:
        runs = [
            _run("b" * 40, "success", "2026-09-30T11:00:00Z"),
            _run("a" * 40, "success", "2026-09-30T10:00:00Z"),
        ]
        assert last_verdict_sha.pick_verdict_sha(runs) == "b" * 40

    def test_no_run_is_empty(self) -> None:
        assert last_verdict_sha.pick_verdict_sha([]) == ""
        cancelled = [_run("a" * 40, "cancelled", "2026-09-30T10:00:00Z")]
        assert last_verdict_sha.pick_verdict_sha(cancelled) == ""


class TestMain:
    """The CLI prints the sha, or nothing, and never fails the workflow."""

    def test_prints_the_sha(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {"workflow_runs": [_run("c" * 40, "success", "2026-09-30T10:00:00Z")]}
        monkeypatch.setattr(last_verdict_sha, "_gh_api", lambda endpoint: json.dumps(payload))
        assert last_verdict_sha.main(["--repo", "o/r"]) == 0
        assert capsys.readouterr().out == "c" * 40 + "\n"

    def test_api_failure_prints_nothing_and_says_why(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(endpoint: str) -> str:
            raise RuntimeError("gh exited 1: HTTP 403")

        monkeypatch.setattr(last_verdict_sha, "_gh_api", boom)
        assert last_verdict_sha.main(["--repo", "o/r"]) == 0
        captured = capsys.readouterr()
        assert captured.out == "\n"
        assert "HTTP 403" in captured.err

    def test_malformed_payload_prints_nothing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(last_verdict_sha, "_gh_api", lambda endpoint: "not json")
        assert last_verdict_sha.main(["--repo", "o/r"]) == 0
        captured = capsys.readouterr()
        assert captured.out == "\n"
        assert "unreadable" in captured.err

    def test_endpoint_asks_for_completed_main_runs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []

        def spy(endpoint: str) -> str:
            seen.append(endpoint)
            return json.dumps({"workflow_runs": []})

        monkeypatch.setattr(last_verdict_sha, "_gh_api", spy)
        last_verdict_sha.main(["--repo", "o/r"])
        assert seen == [
            "repos/o/r/actions/workflows/qa.yml/runs?branch=main&status=completed&per_page=50"
        ]
