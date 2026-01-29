"""Fast QA runner - executes Python quality checks and provides summary.

Uses Python tools: ruff, mypy, black, pytest, bandit (optional).
"""

import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field

from claude_code_hooks_daemon.constants import Timeout
from datetime import datetime
from pathlib import Path
from typing import Any


class QAExecutionError(Exception):
    """Exception raised when QA execution fails."""

    pass


@dataclass
class ToolResult:
    """Result from a single QA tool execution."""

    tool_name: str
    passed: bool
    error_count: int
    warning_count: int
    output: str
    duration_ms: int = 0
    files_affected: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return asdict(self)


@dataclass
class QAResult:
    """Overall QA execution result."""

    status: str  # "passed" or "failed"
    tools_run: list[str] = field(default_factory=list)
    total_errors: int = 0
    total_warnings: int = 0
    timestamp: str = ""
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def __post_init__(self) -> None:
        """Set default timestamp if not provided."""
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert result to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


class QARunner:
    """Fast QA runner - executes Python quality checks and collects results."""

    def __init__(
        self,
        project_root: str = "/workspace",
        output_dir: str | None = None,
    ):
        """Initialize QA runner.

        Args:
            project_root: Root directory of project (where pyproject.toml is)
            output_dir: Directory for storing QA results (default: ./var/qa/)
        """
        self.project_root = Path(project_root)
        self.output_dir = Path(output_dir) if output_dir else (self.project_root / "var" / "qa")
        self.results: QAResult | None = None

        # Python tools to run (can be configured)
        self.tools_to_run = ["ruff", "mypy", "black", "pytest"]

        # Ensure output directory exists
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        """Ensure output directory exists."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def __enter__(self) -> "QARunner":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Context manager exit."""
        pass

    def _run_command(
        self,
        command: str,
        description: str,
        timeout: int = 60,
    ) -> tuple[int, str, str]:
        """Run a shell command and capture output.

        Args:
            command: Command to run
            description: Description for logging
            timeout: Timeout in seconds

        Returns:
            Tuple of (return_code, stdout, stderr)

        Raises:
            QAExecutionError: If command fails unexpectedly
        """
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired as e:
            raise QAExecutionError(f"Command timeout: {description}") from e
        except subprocess.CalledProcessError as e:
            raise QAExecutionError(f"Command failed: {description}\n{e.stderr}") from e
        except Exception as e:
            raise QAExecutionError(f"Execution error: {description}\n{e!s}") from e

    def run_ruff(self) -> ToolResult:
        """Run ruff linting.

        Returns:
            ToolResult with ruff execution results
        """
        start = time.time()

        try:
            returncode, stdout, stderr = self._run_command(
                "ruff check src/ tests/ --output-format=json 2>/dev/null || "
                "ruff check src/ --output-format=json",
                "ruff linting",
            )
        except QAExecutionError as e:
            return ToolResult(
                tool_name="ruff",
                passed=False,
                error_count=-1,
                warning_count=0,
                output=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

        error_count = self._parse_ruff_output(stdout)
        duration_ms = int((time.time() - start) * 1000)

        return ToolResult(
            tool_name="ruff",
            passed=returncode == 0,
            error_count=error_count,
            warning_count=0,
            output=stdout + stderr,
            duration_ms=duration_ms,
        )

    def run_mypy(self) -> ToolResult:
        """Run mypy type checking.

        Returns:
            ToolResult with mypy execution results
        """
        start = time.time()

        try:
            returncode, stdout, stderr = self._run_command(
                "mypy src/",
                "mypy type checking",
                timeout=Timeout.QA_TEST_TIMEOUT,  # mypy can be slow
            )
        except QAExecutionError as e:
            return ToolResult(
                tool_name="mypy",
                passed=False,
                error_count=-1,
                warning_count=0,
                output=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

        error_count = self._parse_mypy_output(stdout + stderr)
        duration_ms = int((time.time() - start) * 1000)

        return ToolResult(
            tool_name="mypy",
            passed=returncode == 0,
            error_count=error_count,
            warning_count=0,
            output=stdout + stderr,
            duration_ms=duration_ms,
        )

    def run_black(self) -> ToolResult:
        """Run black format checking.

        Returns:
            ToolResult with black execution results
        """
        start = time.time()

        try:
            returncode, stdout, stderr = self._run_command(
                "black --check src/ tests/ 2>&1 || black --check src/",
                "black format check",
            )
        except QAExecutionError as e:
            return ToolResult(
                tool_name="black",
                passed=False,
                error_count=-1,
                warning_count=0,
                output=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

        # Black outputs to stderr
        combined_output = stdout + stderr
        error_count = self._parse_black_output(combined_output)
        duration_ms = int((time.time() - start) * 1000)

        return ToolResult(
            tool_name="black",
            passed=returncode == 0,
            error_count=error_count,
            warning_count=0,
            output=combined_output,
            duration_ms=duration_ms,
        )

    def run_pytest(self) -> ToolResult:
        """Run pytest with coverage.

        Returns:
            ToolResult with pytest execution results
        """
        start = time.time()

        try:
            returncode, stdout, stderr = self._run_command(
                "pytest --tb=short -q",
                "pytest tests",
                timeout=Timeout.QA_LONG_TIMEOUT,  # tests can take a while
            )
        except QAExecutionError as e:
            return ToolResult(
                tool_name="pytest",
                passed=False,
                error_count=-1,
                warning_count=0,
                output=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

        error_count = self._parse_pytest_output(stdout + stderr)
        duration_ms = int((time.time() - start) * 1000)

        return ToolResult(
            tool_name="pytest",
            passed=returncode == 0,
            error_count=error_count,
            warning_count=0,
            output=stdout + stderr,
            duration_ms=duration_ms,
        )

    def run_bandit(self) -> ToolResult:
        """Run bandit security linting.

        Returns:
            ToolResult with bandit execution results
        """
        start = time.time()

        try:
            returncode, stdout, stderr = self._run_command(
                "bandit -r src/ -f json",
                "bandit security linting",
            )
        except QAExecutionError as e:
            return ToolResult(
                tool_name="bandit",
                passed=False,
                error_count=-1,
                warning_count=0,
                output=str(e),
                duration_ms=int((time.time() - start) * 1000),
            )

        error_count = self._parse_bandit_output(stdout)
        duration_ms = int((time.time() - start) * 1000)

        return ToolResult(
            tool_name="bandit",
            passed=returncode == 0 or error_count == 0,
            error_count=error_count,
            warning_count=0,
            output=stdout + stderr,
            duration_ms=duration_ms,
        )

    def run_all(self) -> QAResult:
        """Run all configured QA checks.

        Returns:
            QAResult with overall status and all tool results
        """
        tool_results: list[dict[str, Any]] = []
        total_errors = 0
        total_warnings = 0
        all_passed = True

        # Run each tool
        for tool in self.tools_to_run:
            if tool == "ruff":
                result = self.run_ruff()
            elif tool == "mypy":
                result = self.run_mypy()
            elif tool == "black":
                result = self.run_black()
            elif tool == "pytest":
                result = self.run_pytest()
            elif tool == "bandit":
                result = self.run_bandit()
            else:
                continue

            tool_results.append(result.to_dict())
            total_errors += result.error_count if result.error_count >= 0 else 0
            total_warnings += result.warning_count

            if not result.passed:
                all_passed = False

        # Create overall result
        status = "passed" if all_passed else "failed"
        summary = self.generate_summary(
            total_errors=total_errors,
            total_warnings=total_warnings,
            tools_passed=sum(1 for r in tool_results if r["passed"]),
            tools_failed=sum(1 for r in tool_results if not r["passed"]),
        )

        self.results = QAResult(
            status=status,
            tools_run=self.tools_to_run,
            total_errors=total_errors,
            total_warnings=total_warnings,
            tool_results=tool_results,
            summary=summary,
        )

        return self.results

    @staticmethod
    def _parse_ruff_output(output: str) -> int:
        """Parse ruff JSON output to count errors.

        Args:
            output: ruff command output (JSON array)

        Returns:
            Error count
        """
        try:
            issues = json.loads(output)
            return len(issues)
        except json.JSONDecodeError:
            # If not valid JSON, count lines that look like errors
            return len(re.findall(r"^\w+\.py:\d+:\d+:", output, re.MULTILINE))

    @staticmethod
    def _parse_mypy_output(output: str) -> int:
        """Parse mypy output to count errors.

        Args:
            output: mypy command output

        Returns:
            Error count
        """
        # Try to find "Found X errors" at the end
        match = re.search(r"Found (\d+) errors?", output)
        if match:
            return int(match.group(1))

        # Check for success message
        if "Success:" in output or "no issues found" in output.lower():
            return 0

        # Count error lines manually
        return len(re.findall(r":\d+: error:", output))

    @staticmethod
    def _parse_black_output(output: str) -> int:
        """Parse black output to count files needing reformatting.

        Args:
            output: black command output

        Returns:
            Count of files that would be reformatted
        """
        # Count "would reformat" lines
        reformat_count = len(re.findall(r"would reformat", output))
        return reformat_count

    @staticmethod
    def _parse_pytest_output(output: str) -> int:
        """Parse pytest output to count failures.

        Args:
            output: pytest command output

        Returns:
            Failure count
        """
        # Look for "X failed" pattern
        match = re.search(r"(\d+) failed", output)
        if match:
            return int(match.group(1))

        # No failures found
        return 0

    @staticmethod
    def _parse_bandit_output(output: str) -> int:
        """Parse bandit JSON output to count security issues.

        Args:
            output: bandit command output (JSON)

        Returns:
            Issue count
        """
        try:
            data = json.loads(output)
            results = data.get("results", [])
            return len(results)
        except json.JSONDecodeError:
            # Fallback: count issue references
            return len(re.findall(r"Issue:", output))

    def generate_summary(
        self,
        total_errors: int,
        total_warnings: int,
        tools_passed: int,
        tools_failed: int,
    ) -> str:
        """Generate human-readable QA summary.

        Args:
            total_errors: Total errors found
            total_warnings: Total warnings found
            tools_passed: Number of tools passed
            tools_failed: Number of tools failed

        Returns:
            Summary string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("QA SUMMARY (Python Tools)")
        lines.append("=" * 70)
        lines.append(f"Total Errors: {total_errors}")
        lines.append(f"Total Warnings: {total_warnings}")
        lines.append(f"Tools Passed: {tools_passed}")
        lines.append(f"Tools Failed: {tools_failed}")

        if tools_failed == 0:
            lines.append("\nStatus: PASSED")
        else:
            lines.append("\nStatus: FAILED")

        lines.append("=" * 70)
        return "\n".join(lines)

    def save_results(self, result: QAResult) -> Path | None:
        """Save QA results to JSON file.

        Args:
            result: QAResult to save

        Returns:
            Path to saved JSON file, or None if save failed
        """
        if result is None:
            return None

        try:
            timestamp = result.timestamp.replace(":", "-").replace("Z", "")
            filename = f"qa-results-{timestamp}.json"
            filepath = self.output_dir / filename

            with filepath.open("w") as f:
                f.write(result.to_json())

            return filepath
        except Exception as e:
            print(f"Error saving results: {e}")
            return None

    def print_summary(self) -> None:
        """Print QA summary to console."""
        if self.results:
            print(self.results.summary)
            print(f"\nResults saved to: {self.output_dir}")


def main() -> None:
    """Command-line entry point for QA runner."""
    import argparse

    parser = argparse.ArgumentParser(description="Fast QA runner for Python quality checks")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for results",
    )
    parser.add_argument(
        "--tools",
        default="ruff,mypy,black,pytest",
        help="Comma-separated list of tools to run",
    )
    parser.add_argument(
        "--save-results",
        action="store_true",
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    runner = QARunner(
        project_root=args.project_root,
        output_dir=args.output_dir,
    )
    runner.tools_to_run = [t.strip() for t in args.tools.split(",")]

    try:
        result = runner.run_all()
        runner.print_summary()

        if args.save_results:
            filepath = runner.save_results(result)
            if filepath:
                print(f"Results saved to: {filepath}")

        # Exit with appropriate code
        exit(0 if result.status == "passed" else 1)
    except Exception as e:
        print(f"QA execution error: {e}")
        exit(2)


if __name__ == "__main__":
    main()
