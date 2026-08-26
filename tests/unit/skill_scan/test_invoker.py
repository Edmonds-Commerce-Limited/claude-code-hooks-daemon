"""Tests for skill_scan.invoker (Plan 00274).

The model stage is behind the ``ModelInvoker`` protocol so the pipeline is
testable without a CLI; ``ClaudeCliInvoker`` itself is tested with the
subprocess mocked. Every failure mode degrades to an error string — never a
raise (00266 fail-open rule).
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.skill_scan.constants import MODEL_TIMEOUT_SECONDS
from claude_code_hooks_daemon.skill_scan.invoker import (
    ClaudeCliInvoker,
    parse_model_output,
)

_RUN_TARGET = "claude_code_hooks_daemon.skill_scan.invoker.subprocess.run"


def _completed(returncode: int = 0, stdout: str = "ok", stderr: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestClaudeCliInvoker:
    def test_success_returns_stdout(self) -> None:
        with patch(_RUN_TARGET, return_value=_completed(stdout="  answer  ")) as run:
            output, error = ClaudeCliInvoker(model="haiku").invoke("prompt")
        assert output == "answer"
        assert error is None
        argv = run.call_args[0][0]
        assert argv[0] == "claude"
        assert "-p" in argv
        assert "haiku" in argv

    def test_missing_cli_degrades(self) -> None:
        with patch(_RUN_TARGET, side_effect=FileNotFoundError):
            output, error = ClaudeCliInvoker(model="haiku").invoke("prompt")
        assert output is None
        assert error is not None
        assert "not found" in error

    def test_timeout_degrades(self) -> None:
        exc = subprocess.TimeoutExpired(cmd="claude", timeout=MODEL_TIMEOUT_SECONDS)
        with patch(_RUN_TARGET, side_effect=exc):
            output, error = ClaudeCliInvoker(model="haiku").invoke("prompt")
        assert output is None
        assert error is not None
        assert "timed out" in error

    def test_nonzero_exit_degrades_with_detail(self) -> None:
        with patch(
            _RUN_TARGET, return_value=_completed(returncode=1, stdout="", stderr="Not logged in")
        ):
            output, error = ClaudeCliInvoker(model="haiku").invoke("prompt")
        assert output is None
        assert error is not None
        assert "Not logged in" in error
        assert "exited 1" in error

    def test_no_auth_error_mentions_remedy(self) -> None:
        with patch(
            _RUN_TARGET, return_value=_completed(returncode=1, stderr="Not logged in")
        ):
            _, error = ClaudeCliInvoker(model="haiku").invoke("prompt")
        assert error is not None
        assert "authenticated" in error


class TestParseModelOutput:
    def test_valid_json_parsed(self) -> None:
        raw = (
            '{"workloads": [{"name": "docs-regen", "purpose": "regen docs",'
            ' "evidence_cluster_ids": [1, 2]}],'
            ' "corrections": [{"name": "qa-reminder", "purpose": "note",'
            ' "evidence_cluster_ids": [3]}]}'
        )
        suggestions = parse_model_output(raw)
        assert suggestions is not None
        assert suggestions.workloads[0].name == "docs-regen"
        assert suggestions.workloads[0].evidence_cluster_ids == (1, 2)
        assert suggestions.corrections[0].name == "qa-reminder"

    def test_json_inside_code_fence_parsed(self) -> None:
        raw = '```json\n{"workloads": [], "corrections": []}\n```'
        suggestions = parse_model_output(raw)
        assert suggestions is not None
        assert suggestions.workloads == ()

    def test_garbage_returns_none(self) -> None:
        assert parse_model_output("I could not comply, sorry.") is None

    def test_wrong_shape_returns_none(self) -> None:
        assert parse_model_output('["a", "b"]') is None

    def test_malformed_entries_skipped(self) -> None:
        raw = '{"workloads": [{"purpose": "no name"}, "not-a-dict"], "corrections": []}'
        suggestions = parse_model_output(raw)
        assert suggestions is not None
        assert suggestions.workloads == ()
