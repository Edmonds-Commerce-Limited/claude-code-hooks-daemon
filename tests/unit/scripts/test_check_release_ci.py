"""The release CI check: the tagged commit must be the commit CI passed (Plan 00476 Design 7).

``untracked/release-state.json`` records the release pull request's CI run.
Resuming ``/release`` runs the checker, which refuses (non-zero exit, one named
reason) unless the record exists, is well formed, concluded ``success``, tested
exactly the commit about to be tagged, and still reads the same on GitHub.
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
_SCRIPT = _REPO_ROOT / "scripts" / "release" / "check_release_ci.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_release_ci", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_release_ci"] = module
    spec.loader.exec_module(module)
    return module


check = _load()

SHA = "a" * 40
OTHER_SHA = "b" * 40


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "pr_number": 12,
        "run_id": 987654,
        "head_sha": SHA,
        "conclusion": "success",
    }
    record.update(overrides)
    return record


def _state(ci: Any = None, **extra: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "version": "3.60.0",
        "authorised_by_human_at": "2026-10-22T10:00:00Z",
        "last_completed_step": 8,
        "notes": "scope confirmed",
    }
    if ci is not None:
        state["ci"] = ci
    state.update(extra)
    return state


def _live(conclusion: str = "success", head_sha: str = SHA) -> Any:
    def fetch(run_id: int) -> dict[str, str]:
        return {"conclusion": conclusion, "headSha": head_sha}

    return fetch


class TestParseCiRecord:
    def test_accepts_a_complete_record(self) -> None:
        record = check.parse_ci_record(_state(_record()))
        assert (record.pr_number, record.run_id, record.head_sha) == (12, 987654, SHA)
        assert record.conclusion == "success"

    def test_state_without_ci_is_an_error(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="no-ci-record"):
            check.parse_ci_record(_state())

    def test_ci_must_be_an_object(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="malformed-ci-record"):
            check.parse_ci_record(_state(ci="green"))

    @pytest.mark.parametrize("missing", ["pr_number", "run_id", "head_sha", "conclusion"])
    def test_missing_field_is_an_error(self, missing: str) -> None:
        record = _record()
        del record[missing]
        with pytest.raises(check.ReleaseCiError, match="malformed-ci-record.*" + missing):
            check.parse_ci_record(_state(record))

    def test_unknown_field_is_an_error_not_ignored(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="malformed-ci-record.*surprise"):
            check.parse_ci_record(_state(_record(surprise=1)))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("pr_number", "12"),
            ("pr_number", 0),
            ("pr_number", True),
            ("run_id", -1),
            ("run_id", 1.5),
            ("head_sha", "abc123"),
            ("head_sha", "G" * 40),
            ("head_sha", 5),
            ("conclusion", ""),
            ("conclusion", None),
        ],
    )
    def test_wrongly_typed_field_is_an_error(self, field: str, value: Any) -> None:
        with pytest.raises(check.ReleaseCiError, match="malformed-ci-record.*" + field):
            check.parse_ci_record(_state(_record(**{field: value})))


class TestVerify:
    def test_passes_when_recorded_live_and_head_all_agree(self) -> None:
        check.verify(_state(_record()), head_sha=SHA, fetch_run=_live())

    def test_recorded_conclusion_not_success(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="ci-not-green"):
            check.verify(
                _state(_record(conclusion="failure")), head_sha=SHA, fetch_run=_live("failure")
            )

    def test_head_moved_since_ci_passed(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="head-not-tested") as caught:
            check.verify(_state(_record()), head_sha=OTHER_SHA, fetch_run=_live())
        assert SHA in str(caught.value) and OTHER_SHA in str(caught.value)

    def test_live_run_conclusion_differs_from_record(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="live-run-mismatch.*conclusion"):
            check.verify(_state(_record()), head_sha=SHA, fetch_run=_live("cancelled"))

    def test_live_run_tested_a_different_commit(self) -> None:
        with pytest.raises(check.ReleaseCiError, match="live-run-mismatch.*headSha"):
            check.verify(_state(_record()), head_sha=SHA, fetch_run=_live(head_sha=OTHER_SHA))

    def test_live_lookup_failure_is_loud_not_a_pass(self) -> None:
        def broken(run_id: int) -> dict[str, str]:
            raise check.ReleaseCiError("live-run-unavailable: gh exited 1")

        with pytest.raises(check.ReleaseCiError, match="live-run-unavailable"):
            check.verify(_state(_record()), head_sha=SHA, fetch_run=broken)

    def test_live_payload_missing_fields_is_an_error(self) -> None:
        def partial(run_id: int) -> dict[str, str]:
            return {"conclusion": "success"}

        with pytest.raises(check.ReleaseCiError, match="live-run-mismatch.*headSha"):
            check.verify(_state(_record()), head_sha=SHA, fetch_run=partial)


class TestLoadState:
    def test_missing_file_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(check.ReleaseCiError, match="no-state-file"):
            check.load_state(tmp_path / "release-state.json")

    def test_invalid_json_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "release-state.json"
        path.write_text("{not json")
        with pytest.raises(check.ReleaseCiError, match="unreadable-state-file"):
            check.load_state(path)

    def test_non_object_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "release-state.json"
        path.write_text("[]")
        with pytest.raises(check.ReleaseCiError, match="unreadable-state-file"):
            check.load_state(path)

    def test_reads_an_object(self, tmp_path: Path) -> None:
        path = tmp_path / "release-state.json"
        path.write_text(json.dumps(_state(_record())))
        assert check.load_state(path)["version"] == "3.60.0"


class TestFetchLiveRun:
    def test_parses_gh_run_view_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        class Done:
            returncode = 0
            stdout = json.dumps({"conclusion": "success", "headSha": SHA})
            stderr = ""

        def fake_run(cmd: list[str], **_: Any) -> Done:
            calls.append(cmd)
            return Done()

        monkeypatch.setattr(check.subprocess, "run", fake_run)
        assert check.fetch_live_run(55) == {"conclusion": "success", "headSha": SHA}
        assert calls == [["gh", "run", "view", "55", "--json", "conclusion,headSha"]]

    def test_gh_failure_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "HTTP 404"

        monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Failed())
        with pytest.raises(check.ReleaseCiError, match="live-run-unavailable.*HTTP 404"):
            check.fetch_live_run(55)

    def test_gh_non_json_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Garbled:
            returncode = 0
            stdout = "oops"
            stderr = ""

        monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Garbled())
        with pytest.raises(check.ReleaseCiError, match="live-run-unavailable"):
            check.fetch_live_run(55)


class TestMain:
    def _write(self, tmp_path: Path, state: dict[str, Any]) -> Path:
        path = tmp_path / "release-state.json"
        path.write_text(json.dumps(state))
        return path

    def test_green_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = self._write(tmp_path, _state(_record()))
        code = check.main(["--state-file", str(path)], head_resolver=lambda: SHA, fetch_run=_live())
        assert code == 0
        assert "release-ci: ok" in capsys.readouterr().out

    def test_mismatch_exits_nonzero_with_one_line_reason(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = self._write(tmp_path, _state(_record()))
        code = check.main(
            ["--state-file", str(path)], head_resolver=lambda: OTHER_SHA, fetch_run=_live()
        )
        err = capsys.readouterr().err.strip().splitlines()
        assert code == 1
        assert len(err) == 1 and err[0].startswith("release-ci: head-not-tested")

    def test_missing_state_file_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = check.main(
            ["--state-file", str(tmp_path / "absent.json")],
            head_resolver=lambda: SHA,
            fetch_run=_live(),
        )
        assert code == 1
        assert "no-state-file" in capsys.readouterr().err


class TestResolveHead:
    def test_returns_git_rev_parse_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Done:
            returncode = 0
            stdout = SHA + "\n"
            stderr = ""

        monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Done())
        assert check.resolve_head() == SHA

    def test_git_failure_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class Failed:
            returncode = 128
            stdout = ""
            stderr = "not a repo"

        monkeypatch.setattr(check.subprocess, "run", lambda *a, **k: Failed())
        with pytest.raises(check.ReleaseCiError, match="head-unresolvable"):
            check.resolve_head()
