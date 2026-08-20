"""`validate_eslint_on_write` sees TypeScript a Bash command AUTHORED.

Plan 00260 Task 3.5, the sibling of `test_lint_on_edit_bash_writes.py`. This
handler is the stricter of the two — it DENIES on an ESLint timeout and on any
failure to run ESLint at all — so the conservative boundaries matter more here,
not less.

**Test function names avoid `node_modules`, `dist`, `coverage`, `.build` and
`test-results` on purpose.** pytest builds `tmp_path` from the function name and
`SKIP_PATHS` is a naive substring test over the whole path, so a name containing
one of those words silently puts the fixture out of scope and the test asserts
nothing. That is not hypothetical: two tests in the main suite were doing
exactly that, and only passed because `handle()` skipped the filter `matches()`
applies.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
    ValidateEslintOnWriteHandler,
)


@pytest.fixture(autouse=True)
def mock_project_context():
    """Mock ProjectContext, which the handler resolves at construction time."""
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as mock:
        mock.return_value = Path("/tmp/test")
        yield mock


@pytest.fixture(autouse=True)
def mock_llm_commands_detection():
    """Force enforcement mode; advisory mode is covered in the main suite."""
    with patch(
        "claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write"
        ".has_llm_commands_in_package_json",
        return_value=True,
    ) as mock:
        yield mock


def _bash(command: str, cwd: Path) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestAuthoredTypeScriptIsInScope:
    def test_a_heredoc_authoring_ts_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.ts"
        target.write_text("const x = 1;\n")
        command = f"cat > {target} <<'EOF'\nconst x = 1;\nEOF"

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(command, tmp_path)) is True

    def test_a_redirect_authoring_tsx_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.tsx"
        target.write_text("const x = 1;\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(f"echo x > {target}", tmp_path)) is True


class TestOutOfScopeBashWrites:
    def test_a_copy_does_not_match(self, tmp_path: Path) -> None:
        source = tmp_path / "source.ts"
        destination = tmp_path / "copy.ts"
        source.write_text("const x = 1;\n")
        destination.write_text("const x = 1;\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(f"cp {source} {destination}", tmp_path)) is False

    def test_a_non_typescript_target_does_not_match(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.py"
        target.write_text("import os\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(f"echo x > {target}", tmp_path)) is False

    def test_a_predicted_target_that_does_not_exist_does_not_match(self, tmp_path: Path) -> None:
        missing = tmp_path / "never-written.ts"

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(f"echo x > {missing}", tmp_path)) is False

    def test_a_build_output_path_stays_skipped(self, tmp_path: Path) -> None:
        """The existing SKIP_PATHS contract still applies to the new route."""
        skipped_dir = tmp_path / "build-out" / "dist"
        skipped_dir.mkdir(parents=True)
        target = skipped_dir / "authored.ts"
        target.write_text("const x = 1;\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.matches(_bash(f"echo x > {target}", tmp_path)) is False


class TestTheOptOut:
    def test_disabling_bash_checking_stops_matching_bash(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.ts"
        target.write_text("const x = 1;\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        handler._check_bash_writes = False

        assert handler.matches(_bash(f"echo x > {target}", tmp_path)) is False

    def test_disabling_bash_checking_leaves_write_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "authored.ts"
        target.write_text("const x = 1;\n")

        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        handler._check_bash_writes = False

        payload = {"tool_name": "Write", "tool_input": {"file_path": str(target)}}
        assert handler.matches(payload) is True
