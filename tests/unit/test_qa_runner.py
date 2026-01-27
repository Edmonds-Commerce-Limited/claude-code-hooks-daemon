"""Unit tests for QA runner module - Python tools (ruff, mypy, black, pytest, bandit).

Test Driven Development: Tests written FIRST, implementation follows.
"""

import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.qa.runner import (
    QAExecutionError,
    QAResult,
    QARunner,
    ToolResult,
)


class TestQAResult:
    """Test QAResult data class."""

    def test_qa_result_initialization(self) -> None:
        """Test QAResult can be initialized with basic data."""
        result = QAResult(
            status="passed",
            tools_run=["ruff", "mypy"],
            total_errors=0,
            total_warnings=5,
            timestamp="2025-01-20T10:00:00Z",
        )
        assert result.status == "passed"
        assert result.tools_run == ["ruff", "mypy"]
        assert result.total_errors == 0
        assert result.total_warnings == 5

    def test_qa_result_to_dict(self) -> None:
        """Test QAResult can be converted to dictionary."""
        result = QAResult(
            status="failed",
            tools_run=["ruff"],
            total_errors=12,
            total_warnings=3,
            timestamp="2025-01-20T10:00:00Z",
        )
        result_dict = result.to_dict()
        assert result_dict["status"] == "failed"
        assert result_dict["total_errors"] == 12
        assert len(result_dict["tools_run"]) == 1

    def test_qa_result_to_json(self) -> None:
        """Test QAResult can be converted to JSON."""
        result = QAResult(
            status="passed",
            tools_run=["ruff"],
            total_errors=0,
            total_warnings=0,
            timestamp="2025-01-20T10:00:00Z",
        )
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["status"] == "passed"

    def test_qa_result_default_timestamp(self) -> None:
        """Test QAResult generates timestamp if not provided."""
        result = QAResult(status="passed", tools_run=["ruff"])
        assert result.timestamp != ""
        assert "T" in result.timestamp  # ISO format


class TestToolResult:
    """Test ToolResult data class."""

    def test_tool_result_initialization(self) -> None:
        """Test ToolResult can be initialized."""
        result = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="All files pass linting",
            duration_ms=1234,
        )
        assert result.tool_name == "ruff"
        assert result.passed is True
        assert result.error_count == 0

    def test_tool_result_with_failures(self) -> None:
        """Test ToolResult captures failure information."""
        result = ToolResult(
            tool_name="mypy",
            passed=False,
            error_count=12,
            warning_count=0,
            output="src/module.py:42 - error: Type mismatch",
            duration_ms=5678,
        )
        assert result.tool_name == "mypy"
        assert result.passed is False
        assert result.error_count == 12

    def test_tool_result_to_dict(self) -> None:
        """Test ToolResult can be converted to dictionary."""
        result = ToolResult(
            tool_name="black",
            passed=True,
            error_count=0,
            warning_count=0,
            output="All files formatted",
            duration_ms=500,
        )
        result_dict = result.to_dict()
        assert result_dict["tool_name"] == "black"
        assert result_dict["passed"] is True


class TestQARunner:
    """Test QARunner class."""

    def test_qa_runner_initialization(self) -> None:
        """Test QARunner can be initialized."""
        runner = QARunner(project_root="/workspace")
        assert runner.project_root == Path("/workspace")
        assert runner.results is None or isinstance(runner.results, QAResult)

    def test_qa_runner_default_tools(self) -> None:
        """Test QARunner has correct default Python tools."""
        runner = QARunner(project_root="/workspace")
        assert "ruff" in runner.tools_to_run
        assert "mypy" in runner.tools_to_run
        assert "black" in runner.tools_to_run
        assert "pytest" in runner.tools_to_run
        # Should NOT contain JavaScript tools
        assert "eslint" not in runner.tools_to_run
        assert "typescript" not in runner.tools_to_run
        assert "prettier" not in runner.tools_to_run

    def test_qa_runner_with_custom_output_dir(self) -> None:
        """Test QARunner accepts custom output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = QARunner(project_root="/workspace", output_dir=tmpdir)
            assert runner.output_dir == Path(tmpdir)


class TestRuffRunner:
    """Test ruff linting execution."""

    @patch("subprocess.run")
    def test_run_ruff_success(self, mock_run: MagicMock) -> None:
        """Test running ruff successfully with no issues."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[]",  # Empty JSON array = no issues
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_ruff()

        assert result.tool_name == "ruff"
        assert result.passed is True
        assert result.error_count == 0

    @patch("subprocess.run")
    def test_run_ruff_with_errors(self, mock_run: MagicMock) -> None:
        """Test running ruff with linting errors."""
        ruff_json_output = json.dumps(
            [
                {
                    "code": "F401",
                    "message": "'os' imported but unused",
                    "location": {"row": 1, "column": 0},
                    "filename": "src/module.py",
                },
                {
                    "code": "E501",
                    "message": "Line too long",
                    "location": {"row": 10, "column": 100},
                    "filename": "src/module.py",
                },
            ]
        )
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=ruff_json_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_ruff()

        assert result.tool_name == "ruff"
        assert result.passed is False
        assert result.error_count == 2

    @patch("subprocess.run")
    def test_run_ruff_command_format(self, mock_run: MagicMock) -> None:
        """Test ruff is called with correct command format."""
        mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")

        runner = QARunner(project_root="/workspace")
        runner.run_ruff()

        # Verify the command was called correctly
        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "ruff" in command
        assert "check" in command
        assert "--output-format=json" in command or "--output-format json" in command

    @patch("subprocess.run")
    def test_run_ruff_timeout_error(self, mock_run: MagicMock) -> None:
        """Test handling ruff timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("ruff check", 60)

        runner = QARunner(project_root="/workspace")
        result = runner.run_ruff()

        assert result.tool_name == "ruff"
        assert result.passed is False
        assert result.error_count == -1


class TestMypyRunner:
    """Test mypy type checking execution."""

    @patch("subprocess.run")
    def test_run_mypy_success(self, mock_run: MagicMock) -> None:
        """Test running mypy successfully with no type errors."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Success: no issues found in 42 source files\n",
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_mypy()

        assert result.tool_name == "mypy"
        assert result.passed is True
        assert result.error_count == 0

    @patch("subprocess.run")
    def test_run_mypy_with_errors(self, mock_run: MagicMock) -> None:
        """Test running mypy with type errors."""
        mypy_output = """src/module.py:10: error: Incompatible return value type (got "str", expected "int")
src/module.py:25: error: Argument 1 to "foo" has incompatible type "int"; expected "str"
src/other.py:5: error: Missing return statement
Found 3 errors in 2 files (checked 10 source files)
"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=mypy_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_mypy()

        assert result.tool_name == "mypy"
        assert result.passed is False
        assert result.error_count == 3

    @patch("subprocess.run")
    def test_run_mypy_parses_found_errors(self, mock_run: MagicMock) -> None:
        """Test mypy output parsing extracts error count from 'Found X errors'."""
        mypy_output = """src/a.py:1: error: Something wrong
Found 5 errors in 2 files
"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=mypy_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_mypy()

        # Should extract 5 from "Found 5 errors"
        assert result.error_count == 5

    @patch("subprocess.run")
    def test_run_mypy_command_format(self, mock_run: MagicMock) -> None:
        """Test mypy is called with correct command format."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="Success: no issues found\n", stderr=""
        )

        runner = QARunner(project_root="/workspace")
        runner.run_mypy()

        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "mypy" in command
        assert "src/" in command

    @patch("subprocess.run")
    def test_run_mypy_timeout_error(self, mock_run: MagicMock) -> None:
        """Test handling mypy timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("mypy src/", 60)

        runner = QARunner(project_root="/workspace")
        result = runner.run_mypy()

        assert result.tool_name == "mypy"
        assert result.passed is False
        assert result.error_count == -1


class TestBlackRunner:
    """Test black format checking execution."""

    @patch("subprocess.run")
    def test_run_black_success(self, mock_run: MagicMock) -> None:
        """Test running black successfully with all files formatted."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="All done! 10 files would be left unchanged.\n",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_black()

        assert result.tool_name == "black"
        assert result.passed is True
        assert result.error_count == 0

    @patch("subprocess.run")
    def test_run_black_with_formatting_issues(self, mock_run: MagicMock) -> None:
        """Test running black with files needing formatting."""
        black_output = """would reformat src/module.py
would reformat tests/test_module.py
Oh no! 2 files would be reformatted, 10 files would be left unchanged.
"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr=black_output,
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_black()

        assert result.tool_name == "black"
        assert result.passed is False
        assert result.error_count == 2

    @patch("subprocess.run")
    def test_run_black_parses_would_reformat(self, mock_run: MagicMock) -> None:
        """Test black output parsing counts 'would reformat' lines."""
        black_output = """would reformat src/a.py
would reformat src/b.py
would reformat src/c.py
Oh no! 3 files would be reformatted.
"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr=black_output,
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_black()

        assert result.error_count == 3

    @patch("subprocess.run")
    def test_run_black_command_format(self, mock_run: MagicMock) -> None:
        """Test black is called with correct command format."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="All done! 5 files left unchanged.\n"
        )

        runner = QARunner(project_root="/workspace")
        runner.run_black()

        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "black" in command
        assert "--check" in command

    @patch("subprocess.run")
    def test_run_black_timeout_error(self, mock_run: MagicMock) -> None:
        """Test handling black timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("black --check", 60)

        runner = QARunner(project_root="/workspace")
        result = runner.run_black()

        assert result.tool_name == "black"
        assert result.passed is False
        assert result.error_count == -1


class TestPytestRunner:
    """Test pytest execution."""

    @patch("subprocess.run")
    def test_run_pytest_success(self, mock_run: MagicMock) -> None:
        """Test running pytest successfully with all tests passing."""
        pytest_output = """============================= test session starts ==============================
collected 28 items

tests/test_module.py ............................                              [100%]

============================== 28 passed in 1.50s ===============================
"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=pytest_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_pytest()

        assert result.tool_name == "pytest"
        assert result.passed is True
        assert result.error_count == 0

    @patch("subprocess.run")
    def test_run_pytest_with_failures(self, mock_run: MagicMock) -> None:
        """Test running pytest with test failures."""
        pytest_output = """============================= test session starts ==============================
collected 28 items

tests/test_module.py ....F.....F..........F....                               [100%]

=================================== FAILURES ===================================
FAILED tests/test_module.py::test_foo - AssertionError
FAILED tests/test_module.py::test_bar - TypeError
FAILED tests/test_module.py::test_baz - ValueError
=========================== 3 failed, 25 passed in 2.50s =======================
"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=pytest_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_pytest()

        assert result.tool_name == "pytest"
        assert result.passed is False
        assert result.error_count == 3

    @patch("subprocess.run")
    def test_run_pytest_parses_failure_count(self, mock_run: MagicMock) -> None:
        """Test pytest output parsing extracts failure count."""
        pytest_output = (
            """=========================== 5 failed, 20 passed in 1.00s ======================="""
        )
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=pytest_output,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_pytest()

        assert result.error_count == 5

    @patch("subprocess.run")
    def test_run_pytest_command_format(self, mock_run: MagicMock) -> None:
        """Test pytest is called with correct command format."""
        mock_run.return_value = MagicMock(returncode=0, stdout="1 passed\n", stderr="")

        runner = QARunner(project_root="/workspace")
        runner.run_pytest()

        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "pytest" in command

    @patch("subprocess.run")
    def test_run_pytest_timeout_error(self, mock_run: MagicMock) -> None:
        """Test handling pytest timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("pytest", 120)

        runner = QARunner(project_root="/workspace")
        result = runner.run_pytest()

        assert result.tool_name == "pytest"
        assert result.passed is False
        assert result.error_count == -1


class TestBanditRunner:
    """Test bandit security linting execution."""

    @patch("subprocess.run")
    def test_run_bandit_success(self, mock_run: MagicMock) -> None:
        """Test running bandit successfully with no security issues."""
        bandit_json = json.dumps(
            {
                "errors": [],
                "generated_at": "2025-01-20T10:00:00Z",
                "metrics": {},
                "results": [],
            }
        )
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=bandit_json,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_bandit()

        assert result.tool_name == "bandit"
        assert result.passed is True
        assert result.error_count == 0

    @patch("subprocess.run")
    def test_run_bandit_with_issues(self, mock_run: MagicMock) -> None:
        """Test running bandit with security issues."""
        bandit_json = json.dumps(
            {
                "errors": [],
                "generated_at": "2025-01-20T10:00:00Z",
                "metrics": {},
                "results": [
                    {
                        "code": "1 import subprocess",
                        "filename": "src/module.py",
                        "issue_confidence": "HIGH",
                        "issue_severity": "MEDIUM",
                        "issue_text": "Consider possible security implications",
                        "line_number": 1,
                        "test_id": "B404",
                        "test_name": "blacklist",
                    },
                    {
                        "code": "2 subprocess.call(cmd, shell=True)",
                        "filename": "src/module.py",
                        "issue_confidence": "HIGH",
                        "issue_severity": "HIGH",
                        "issue_text": "Subprocess call with shell=True is dangerous",
                        "line_number": 10,
                        "test_id": "B602",
                        "test_name": "subprocess_popen_with_shell_equals_true",
                    },
                ],
            }
        )
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=bandit_json,
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_bandit()

        assert result.tool_name == "bandit"
        assert result.passed is False
        assert result.error_count == 2

    @patch("subprocess.run")
    def test_run_bandit_command_format(self, mock_run: MagicMock) -> None:
        """Test bandit is called with correct command format."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout='{"results": [], "errors": []}', stderr=""
        )

        runner = QARunner(project_root="/workspace")
        runner.run_bandit()

        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "bandit" in command
        assert "-r" in command
        assert "-f" in command
        assert "json" in command

    @patch("subprocess.run")
    def test_run_bandit_timeout_error(self, mock_run: MagicMock) -> None:
        """Test handling bandit timeout."""
        mock_run.side_effect = subprocess.TimeoutExpired("bandit -r src/", 60)

        runner = QARunner(project_root="/workspace")
        result = runner.run_bandit()

        assert result.tool_name == "bandit"
        assert result.passed is False
        assert result.error_count == -1


class TestRunAll:
    """Test run_all method combining all tools."""

    @patch.object(QARunner, "run_ruff")
    @patch.object(QARunner, "run_mypy")
    @patch.object(QARunner, "run_black")
    @patch.object(QARunner, "run_pytest")
    def test_run_all_success(
        self,
        mock_pytest: MagicMock,
        mock_black: MagicMock,
        mock_mypy: MagicMock,
        mock_ruff: MagicMock,
    ) -> None:
        """Test running all QA checks successfully."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=100,
        )
        mock_mypy.return_value = ToolResult(
            tool_name="mypy",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=200,
        )
        mock_black.return_value = ToolResult(
            tool_name="black",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=50,
        )
        mock_pytest.return_value = ToolResult(
            tool_name="pytest",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=1000,
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_all()

        assert result.status == "passed"
        assert len(result.tools_run) == 4
        assert result.total_errors == 0
        assert "ruff" in result.tools_run
        assert "mypy" in result.tools_run
        assert "black" in result.tools_run
        assert "pytest" in result.tools_run

    @patch.object(QARunner, "run_ruff")
    @patch.object(QARunner, "run_mypy")
    @patch.object(QARunner, "run_black")
    @patch.object(QARunner, "run_pytest")
    def test_run_all_with_failures(
        self,
        mock_pytest: MagicMock,
        mock_black: MagicMock,
        mock_mypy: MagicMock,
        mock_ruff: MagicMock,
    ) -> None:
        """Test running all checks with some failures."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=False,
            error_count=5,
            warning_count=2,
            output="errors found",
            duration_ms=100,
        )
        mock_mypy.return_value = ToolResult(
            tool_name="mypy",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=200,
        )
        mock_black.return_value = ToolResult(
            tool_name="black",
            passed=False,
            error_count=3,
            warning_count=0,
            output="would reformat",
            duration_ms=50,
        )
        mock_pytest.return_value = ToolResult(
            tool_name="pytest",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=1000,
        )

        runner = QARunner(project_root="/workspace")
        result = runner.run_all()

        assert result.status == "failed"
        assert result.total_errors == 8  # 5 + 3


class TestOutputParsing:
    """Test output parsing helper methods."""

    def test_parse_ruff_json_output(self) -> None:
        """Test parsing ruff JSON output."""
        output = json.dumps(
            [
                {"code": "F401", "message": "unused import", "filename": "a.py"},
                {"code": "E501", "message": "line too long", "filename": "b.py"},
            ]
        )
        runner = QARunner(project_root="/workspace")
        count = runner._parse_ruff_output(output)
        assert count == 2

    def test_parse_ruff_empty_output(self) -> None:
        """Test parsing empty ruff output."""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_ruff_output("[]")
        assert count == 0

    def test_parse_mypy_output_with_errors(self) -> None:
        """Test parsing mypy output with errors."""
        output = """src/a.py:10: error: Something wrong
src/b.py:20: error: Another error
Found 2 errors in 2 files
"""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_mypy_output(output)
        assert count == 2

    def test_parse_mypy_output_success(self) -> None:
        """Test parsing mypy output with no errors."""
        output = "Success: no issues found in 10 source files\n"
        runner = QARunner(project_root="/workspace")
        count = runner._parse_mypy_output(output)
        assert count == 0

    def test_parse_black_output_with_reformats(self) -> None:
        """Test parsing black output with files to reformat."""
        output = """would reformat src/a.py
would reformat src/b.py
Oh no! 2 files would be reformatted.
"""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_black_output(output)
        assert count == 2

    def test_parse_black_output_success(self) -> None:
        """Test parsing black output with no changes needed."""
        output = "All done! 10 files would be left unchanged.\n"
        runner = QARunner(project_root="/workspace")
        count = runner._parse_black_output(output)
        assert count == 0

    def test_parse_pytest_output_with_failures(self) -> None:
        """Test parsing pytest output with failures."""
        output = (
            """=========================== 3 failed, 25 passed in 2.50s ======================="""
        )
        runner = QARunner(project_root="/workspace")
        count = runner._parse_pytest_output(output)
        assert count == 3

    def test_parse_pytest_output_success(self) -> None:
        """Test parsing pytest output with all passing."""
        output = (
            """============================== 28 passed in 1.50s ==============================="""
        )
        runner = QARunner(project_root="/workspace")
        count = runner._parse_pytest_output(output)
        assert count == 0

    def test_parse_bandit_json_output(self) -> None:
        """Test parsing bandit JSON output."""
        output = json.dumps(
            {
                "results": [
                    {"test_id": "B101", "issue_text": "assert used"},
                    {"test_id": "B602", "issue_text": "shell=True"},
                ],
                "errors": [],
            }
        )
        runner = QARunner(project_root="/workspace")
        count = runner._parse_bandit_output(output)
        assert count == 2

    def test_parse_bandit_empty_output(self) -> None:
        """Test parsing bandit JSON output with no issues."""
        output = json.dumps({"results": [], "errors": []})
        runner = QARunner(project_root="/workspace")
        count = runner._parse_bandit_output(output)
        assert count == 0


class TestQAExecutionError:
    """Test QAExecutionError exception."""

    def test_qa_execution_error_creation(self) -> None:
        """Test creating QAExecutionError."""
        error = QAExecutionError("Tool execution failed")
        assert str(error) == "Tool execution failed"

    def test_qa_execution_error_inheritance(self) -> None:
        """Test QAExecutionError is an Exception."""
        error = QAExecutionError("Test error")
        assert isinstance(error, Exception)


class TestSummaryGeneration:
    """Test summary generation."""

    def test_generate_summary_passed(self) -> None:
        """Test generating summary for passed QA."""
        runner = QARunner(project_root="/workspace")
        summary = runner.generate_summary(
            total_errors=0, total_warnings=2, tools_passed=4, tools_failed=0
        )
        assert "PASSED" in summary
        assert "0" in summary  # errors
        assert "4" in summary  # tools passed

    def test_generate_summary_failed(self) -> None:
        """Test generating summary for failed QA."""
        runner = QARunner(project_root="/workspace")
        summary = runner.generate_summary(
            total_errors=12, total_warnings=5, tools_passed=2, tools_failed=2
        )
        assert "FAILED" in summary
        assert "12" in summary  # errors


class TestResultSaving:
    """Test saving results to file."""

    @patch.object(QARunner, "run_ruff")
    @patch.object(QARunner, "run_mypy")
    @patch.object(QARunner, "run_black")
    @patch.object(QARunner, "run_pytest")
    def test_save_results_to_json(
        self,
        mock_pytest: MagicMock,
        mock_black: MagicMock,
        mock_mypy: MagicMock,
        mock_ruff: MagicMock,
    ) -> None:
        """Test saving QA results to JSON file."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=100,
        )
        mock_mypy.return_value = ToolResult(
            tool_name="mypy",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=200,
        )
        mock_black.return_value = ToolResult(
            tool_name="black",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=50,
        )
        mock_pytest.return_value = ToolResult(
            tool_name="pytest",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=1000,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            runner = QARunner(project_root="/workspace", output_dir=tmpdir)
            result = runner.run_all()
            json_file = runner.save_results(result)

            assert json_file is not None
            assert json_file.exists()
            assert json_file.suffix == ".json"

            with json_file.open() as f:
                data = json.load(f)
                assert data["status"] == "passed"
                assert "ruff" in data["tools_run"]


class TestContextManager:
    """Test context manager functionality."""

    def test_qa_runner_context_manager(self) -> None:
        """Test QARunner as context manager."""
        with (
            tempfile.TemporaryDirectory() as tmpdir,
            QARunner(project_root="/workspace", output_dir=tmpdir) as runner,
        ):
            assert runner is not None
            assert runner.output_dir is not None


class TestCommandExecution:
    """Test _run_command helper method."""

    @patch("subprocess.run")
    def test_run_command_success(self, mock_run: MagicMock) -> None:
        """Test successful command execution."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="output",
            stderr="",
        )

        runner = QARunner(project_root="/workspace")
        returncode, stdout, _stderr = runner._run_command("echo test", "test command")

        assert returncode == 0
        assert stdout == "output"

    @patch("subprocess.run")
    def test_run_command_timeout(self, mock_run: MagicMock) -> None:
        """Test command timeout raises QAExecutionError."""
        mock_run.side_effect = subprocess.TimeoutExpired("command", 60)

        runner = QARunner(project_root="/workspace")

        with pytest.raises(QAExecutionError):
            runner._run_command("slow command", "test command")


class TestOutputDirectoryCreation:
    """Test output directory handling."""

    def test_output_directory_creation(self) -> None:
        """Test that output directory is created if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "qa_output"

            runner = QARunner(project_root="/workspace", output_dir=str(output_dir))
            runner._ensure_output_dir()

            assert output_dir.exists()


class TestRunCommandErrors:
    """Test _run_command error handling."""

    @patch("subprocess.run")
    def test_run_command_called_process_error(self, mock_run: MagicMock) -> None:
        """Test handling CalledProcessError."""
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="test", stderr="Error output"
        )

        runner = QARunner(project_root="/workspace")

        with pytest.raises(QAExecutionError) as exc_info:
            runner._run_command("failing command", "test command")

        assert "Command failed" in str(exc_info.value)

    @patch("subprocess.run")
    def test_run_command_generic_exception(self, mock_run: MagicMock) -> None:
        """Test handling generic exceptions."""
        mock_run.side_effect = RuntimeError("Unexpected error")

        runner = QARunner(project_root="/workspace")

        with pytest.raises(QAExecutionError) as exc_info:
            runner._run_command("failing command", "test command")

        assert "Execution error" in str(exc_info.value)


class TestRunAllWithBandit:
    """Test run_all with bandit tool included."""

    @patch.object(QARunner, "run_ruff")
    @patch.object(QARunner, "run_mypy")
    @patch.object(QARunner, "run_black")
    @patch.object(QARunner, "run_pytest")
    @patch.object(QARunner, "run_bandit")
    def test_run_all_with_bandit_tool(
        self,
        mock_bandit: MagicMock,
        mock_pytest: MagicMock,
        mock_black: MagicMock,
        mock_mypy: MagicMock,
        mock_ruff: MagicMock,
    ) -> None:
        """Test running all QA checks including bandit."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=100,
        )
        mock_mypy.return_value = ToolResult(
            tool_name="mypy",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=200,
        )
        mock_black.return_value = ToolResult(
            tool_name="black",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=50,
        )
        mock_pytest.return_value = ToolResult(
            tool_name="pytest",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=1000,
        )
        mock_bandit.return_value = ToolResult(
            tool_name="bandit",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=500,
        )

        runner = QARunner(project_root="/workspace")
        runner.tools_to_run = ["ruff", "mypy", "black", "pytest", "bandit"]
        result = runner.run_all()

        assert result.status == "passed"
        assert len(result.tools_run) == 5
        assert "bandit" in result.tools_run

    @patch.object(QARunner, "run_ruff")
    def test_run_all_with_unknown_tool(self, mock_ruff: MagicMock) -> None:
        """Test run_all skips unknown tools gracefully."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=100,
        )

        runner = QARunner(project_root="/workspace")
        runner.tools_to_run = ["ruff", "unknown_tool"]
        result = runner.run_all()

        # Should complete without error
        assert result.status == "passed"


class TestRuffOutputParsingEdgeCases:
    """Test ruff output parsing edge cases."""

    def test_parse_ruff_non_json_output(self) -> None:
        """Test parsing ruff output that is not JSON."""
        output = """module.py:10:5: F401 'os' imported but unused
module.py:20:10: E501 line too long
"""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_ruff_output(output)
        assert count == 2


class TestMypyOutputParsingEdgeCases:
    """Test mypy output parsing edge cases."""

    def test_parse_mypy_output_manual_count(self) -> None:
        """Test parsing mypy output by counting error lines manually."""
        output = """src/a.py:10: error: Something wrong
src/b.py:20: error: Another error
src/c.py:30: error: Third error
"""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_mypy_output(output)
        assert count == 3

    def test_parse_mypy_output_no_issues_lowercase(self) -> None:
        """Test parsing mypy output with lowercase 'no issues found'."""
        output = "Success: no issues found in 10 files\n"
        runner = QARunner(project_root="/workspace")
        count = runner._parse_mypy_output(output)
        assert count == 0


class TestBanditOutputParsingEdgeCases:
    """Test bandit output parsing edge cases."""

    def test_parse_bandit_non_json_output(self) -> None:
        """Test parsing bandit output that is not JSON."""
        output = """Issue: [B101:assert_used] Use of assert detected.
Issue: [B602:subprocess_shell] subprocess call with shell=True.
"""
        runner = QARunner(project_root="/workspace")
        count = runner._parse_bandit_output(output)
        assert count == 2


class TestSaveResults:
    """Test save_results method."""

    def test_save_results_none_result(self) -> None:
        """Test saving None result returns None."""
        runner = QARunner(project_root="/workspace")
        filepath = runner.save_results(None)  # type: ignore[arg-type]
        assert filepath is None

    @patch.object(Path, "open")
    def test_save_results_write_error(self, mock_open: MagicMock) -> None:
        """Test save_results handles write errors."""
        mock_open.side_effect = OSError("Write error")

        runner = QARunner(project_root="/workspace")
        result = QAResult(status="passed", tools_run=["ruff"])

        filepath = runner.save_results(result)
        assert filepath is None


class TestPrintSummary:
    """Test print_summary method."""

    @patch("builtins.print")
    @patch.object(QARunner, "run_ruff")
    def test_print_summary_with_results(self, mock_ruff: MagicMock, mock_print: MagicMock) -> None:
        """Test printing summary when results exist."""
        mock_ruff.return_value = ToolResult(
            tool_name="ruff",
            passed=True,
            error_count=0,
            warning_count=0,
            output="pass",
            duration_ms=100,
        )

        runner = QARunner(project_root="/workspace")
        runner.tools_to_run = ["ruff"]
        runner.run_all()
        runner.print_summary()

        # Should have printed something
        assert mock_print.call_count >= 1

    @patch("builtins.print")
    def test_print_summary_without_results(self, mock_print: MagicMock) -> None:
        """Test printing summary when no results exist."""
        runner = QARunner(project_root="/workspace")
        runner.print_summary()

        # Should not print if no results
        mock_print.assert_not_called()


class TestMainFunction:
    """Test main() CLI entry point."""

    @patch("sys.argv", ["runner.py", "--project-root", "/test", "--tools", "ruff,mypy"])
    @patch.object(QARunner, "run_all")
    @patch("builtins.exit")
    def test_main_success(self, mock_exit: MagicMock, mock_run_all: MagicMock) -> None:
        """Test main function with successful QA run."""
        mock_run_all.return_value = QAResult(status="passed", tools_run=["ruff", "mypy"])

        from claude_code_hooks_daemon.qa.runner import main

        main()

        mock_exit.assert_called_once_with(0)

    @patch("sys.argv", ["runner.py", "--project-root", "/test"])
    @patch.object(QARunner, "run_all")
    @patch("builtins.exit")
    def test_main_failure(self, mock_exit: MagicMock, mock_run_all: MagicMock) -> None:
        """Test main function with failed QA run."""
        mock_run_all.return_value = QAResult(status="failed", tools_run=["ruff"])

        from claude_code_hooks_daemon.qa.runner import main

        main()

        mock_exit.assert_called_once_with(1)

    @patch("sys.argv", ["runner.py", "--project-root", "/test", "--save-results"])
    @patch.object(QARunner, "run_all")
    @patch.object(QARunner, "save_results")
    @patch("builtins.exit")
    @patch("builtins.print")
    def test_main_with_save_results(
        self,
        mock_print: MagicMock,
        mock_exit: MagicMock,
        mock_save: MagicMock,
        mock_run_all: MagicMock,
    ) -> None:
        """Test main function with --save-results flag."""
        mock_run_all.return_value = QAResult(status="passed", tools_run=["ruff"])
        mock_save.return_value = Path("/tmp/qa-results.json")

        from claude_code_hooks_daemon.qa.runner import main

        main()

        mock_save.assert_called_once()
        mock_exit.assert_called_once_with(0)

    @patch("sys.argv", ["runner.py"])
    @patch.object(QARunner, "run_all")
    @patch("builtins.exit")
    def test_main_with_exception(self, mock_exit: MagicMock, mock_run_all: MagicMock) -> None:
        """Test main function handles exceptions."""
        mock_run_all.side_effect = Exception("Test error")

        from claude_code_hooks_daemon.qa.runner import main

        main()

        mock_exit.assert_called_once_with(2)

    @patch("sys.argv", ["runner.py", "--output-dir", "/custom/dir"])
    @patch.object(QARunner, "run_all")
    @patch("builtins.exit")
    def test_main_with_custom_output_dir(
        self, mock_exit: MagicMock, mock_run_all: MagicMock
    ) -> None:
        """Test main function with custom output directory."""
        mock_run_all.return_value = QAResult(status="passed", tools_run=["ruff"])

        from claude_code_hooks_daemon.qa.runner import main

        main()

        mock_exit.assert_called_once_with(0)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
