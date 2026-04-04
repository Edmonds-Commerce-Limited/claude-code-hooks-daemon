"""Tests for the skill-reference QA checker.

Ensures agent-facing messages use 'Use the hooks-daemon skill to...'
instead of bare 'python -m claude_code_hooks_daemon' or '/hooks-daemon' slash syntax.
"""

import json
import subprocess  # nosec B404 - subprocess used for running QA checker only
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[3] / "scripts" / "qa"
CHECKER = SCRIPT_DIR / "check_skill_references.py"
PYTHON = Path(__file__).resolve().parents[3] / "untracked" / "venv" / "bin" / "python"


def _run_checker(*args: str) -> dict[str, Any]:
    """Run the checker with --json and return parsed output."""
    subprocess.run(  # nosec B603 B607 - trusted checker script
        [str(PYTHON), str(CHECKER), "--json", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    qa_json = Path(__file__).resolve().parents[3] / "untracked" / "qa" / "skill_references.json"
    assert qa_json.exists(), f"Expected JSON output at {qa_json}"
    return json.loads(qa_json.read_text())


class TestBarePythonModule:
    """Detect bare 'python -m claude_code_hooks_daemon' in agent-facing strings."""

    def test_flags_bare_python_m_in_string(self, tmp_path: Path) -> None:
        """Bare python -m reference in a string literal should be flagged."""
        source = tmp_path / "bad.py"
        source.write_text('msg = "Run python -m claude_code_hooks_daemon.daemon.cli restart"\n')
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]
        assert data["summary"]["total_violations"] > 0
        violations = data["violations"]
        assert any("python -m" in v["message"] for v in violations)

    def test_ignores_python_m_in_comments(self, tmp_path: Path) -> None:
        """Comments with python -m should not be flagged (not agent-facing)."""
        source = tmp_path / "ok.py"
        source.write_text("# Run python -m claude_code_hooks_daemon.daemon.cli restart\n" "x = 1\n")
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]

    def test_ignores_python_m_in_non_daemon_modules(self, tmp_path: Path) -> None:
        """python -m for other modules should not be flagged."""
        source = tmp_path / "ok.py"
        source.write_text('msg = "Run python -m pytest tests/"\n')
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestSlashCommandSyntax:
    """Detect '/hooks-daemon' slash-command syntax in agent-facing strings."""

    def test_flags_slash_hooks_daemon_in_string(self, tmp_path: Path) -> None:
        """'/hooks-daemon restart' in a string should be flagged."""
        source = tmp_path / "bad.py"
        source.write_text('msg = "Run /hooks-daemon restart to fix"\n')
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]
        violations = data["violations"]
        assert any("/hooks-daemon" in v["message"] for v in violations)

    def test_flags_run_hooks_daemon_pattern(self, tmp_path: Path) -> None:
        """'run /hooks-daemon' in a string should be flagged."""
        source = tmp_path / "bad.py"
        source.write_text('msg = "run /hooks-daemon health"\n')
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]

    def test_ignores_slash_in_file_paths(self, tmp_path: Path) -> None:
        """File paths like '/hooks-daemon/' directory refs should not be flagged."""
        source = tmp_path / "ok.py"
        source.write_text('path = ".claude/hooks-daemon/untracked/"\n')
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]

    def test_ignores_slash_in_comments(self, tmp_path: Path) -> None:
        """Comments with /hooks-daemon should not be flagged."""
        source = tmp_path / "ok.py"
        source.write_text("# Use /hooks-daemon restart\nx = 1\n")
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestCorrectPatterns:
    """Verify correct patterns are not flagged."""

    def test_skill_tool_reference_not_flagged(self, tmp_path: Path) -> None:
        """Correct skill-based reference should pass."""
        source = tmp_path / "ok.py"
        source.write_text(
            'msg = "Use the hooks-daemon skill to restart '
            '(Skill tool: skill=hooks-daemon, args=restart)"\n'
        )
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]

    def test_no_python_files_passes(self, tmp_path: Path) -> None:
        """Directory with no Python files should pass."""
        (tmp_path / "readme.txt").write_text("hello")
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestBashScripts:
    """Detect violations in bash scripts too."""

    def test_flags_python_m_in_bash_string(self, tmp_path: Path) -> None:
        """Bare python -m in bash echo/printf should be flagged."""
        source = tmp_path / "bad.sh"
        source.write_text(
            "#!/bin/bash\n" 'echo "Run python -m claude_code_hooks_daemon.daemon.cli restart"\n'
        )
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]

    def test_flags_slash_hooks_daemon_in_bash(self, tmp_path: Path) -> None:
        """'/hooks-daemon health' in bash should be flagged."""
        source = tmp_path / "bad.sh"
        source.write_text("#!/bin/bash\n" 'echo "Run /hooks-daemon health"\n')
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]

    def test_ignores_bash_comments(self, tmp_path: Path) -> None:
        """Bash comments should not be flagged."""
        source = tmp_path / "ok.sh"
        source.write_text(
            "#!/bin/bash\n"
            "# Run python -m claude_code_hooks_daemon.daemon.cli restart\n"
            'echo "hello"\n'
        )
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestMarkdownFiles:
    """Detect violations in markdown files (which contain agent-facing instructions)."""

    def test_flags_python_m_in_markdown_text(self, tmp_path: Path) -> None:
        """Bare python -m in markdown prose should be flagged."""
        source = tmp_path / "bad.md"
        source.write_text(
            "# Troubleshooting\n\n"
            "Run `python -m claude_code_hooks_daemon.daemon.cli restart` to fix.\n"
        )
        data = _run_checker("--path", str(tmp_path))
        assert not data["summary"]["passed"]

    def test_ignores_markdown_code_blocks(self, tmp_path: Path) -> None:
        """Code blocks in markdown are documentation, not agent instructions."""
        source = tmp_path / "ok.md"
        source.write_text(
            "# Architecture\n\n"
            "```bash\n"
            "python -m claude_code_hooks_daemon.daemon.cli restart\n"
            "```\n"
        )
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestExclusions:
    """Verify certain files/dirs are excluded from scanning."""

    def test_excludes_checker_itself(self) -> None:
        """The checker script itself should be excluded."""
        # When scanning the real project, the checker shouldn't flag itself
        data = _run_checker("--path", str(SCRIPT_DIR), "--include", "check_skill_references.py")
        assert data["summary"]["passed"]

    def test_excludes_test_files(self, tmp_path: Path) -> None:
        """Test files should be excluded (they test the patterns)."""
        source = tmp_path / "test_something.py"
        source.write_text('msg = "Run python -m claude_code_hooks_daemon.daemon.cli restart"\n')
        data = _run_checker("--path", str(tmp_path))
        assert data["summary"]["passed"]


class TestJsonOutput:
    """Verify JSON output format matches QA conventions."""

    def test_json_has_required_fields(self, tmp_path: Path) -> None:
        """JSON output must have tool, summary, and violations keys."""
        (tmp_path / "empty.py").write_text("x = 1\n")
        data = _run_checker("--path", str(tmp_path))
        assert "tool" in data
        assert data["tool"] == "skill_references"
        assert "summary" in data
        assert "passed" in data["summary"]
        assert "total_violations" in data["summary"]
        assert "violations" in data

    def test_violation_has_required_fields(self, tmp_path: Path) -> None:
        """Each violation must have file, line, rule, and message."""
        source = tmp_path / "bad.py"
        source.write_text('msg = "Run /hooks-daemon restart"\n')
        data = _run_checker("--path", str(tmp_path))
        assert len(data["violations"]) > 0
        v = data["violations"][0]
        assert "file" in v
        assert "line" in v
        assert "rule" in v
        assert "message" in v
        assert v["rule"] in ("bare-python-module", "slash-command-syntax")
