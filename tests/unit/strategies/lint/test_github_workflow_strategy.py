"""GitHub workflow lint strategy (Plan 00621 Task 2.1).

The strategy routes a `.github/workflows/*.yml` file to the external
`actions-qa` linter. The rule set lives in that linter, never here, so these
tests pin only the routing (which files), the command, and the two optional
capabilities that make the linter safe to suggest: only its findings exit code
is a failure, and its absence prints nothing.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.strategies.lint.github_workflow_strategy import (
    GitHubWorkflowLintStrategy,
)
from claude_code_hooks_daemon.strategies.lint.protocol import (
    DeclaresFindingsExitCodes,
    DeclaresOptionalTool,
    LintStrategy,
    NarrowsByPath,
)


@pytest.fixture()
def strategy() -> GitHubWorkflowLintStrategy:
    return GitHubWorkflowLintStrategy()


class TestProtocolConformance:
    def test_satisfies_the_lint_strategy_protocol(
        self, strategy: GitHubWorkflowLintStrategy
    ) -> None:
        assert isinstance(strategy, LintStrategy)

    def test_narrows_by_path_because_it_shares_the_yaml_extensions(
        self, strategy: GitHubWorkflowLintStrategy
    ) -> None:
        assert isinstance(strategy, NarrowsByPath)

    def test_declares_its_findings_exit_codes(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert isinstance(strategy, DeclaresFindingsExitCodes)
        assert strategy.findings_exit_codes == frozenset({1})

    def test_declares_its_tool_optional(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert isinstance(strategy, DeclaresOptionalTool)
        assert strategy.lint_tool_is_optional is True


class TestProperties:
    def test_language_name(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert strategy.language_name == "GitHub Workflow"

    def test_handles_both_yaml_extensions(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert strategy.extensions == (".yml", ".yaml")

    def test_default_command_is_actions_qa_check_file(
        self, strategy: GitHubWorkflowLintStrategy
    ) -> None:
        """The executable is `actions-qa`, not the project name `actions-qa-ci`."""
        assert shlex.split(strategy.default_lint_command) == [
            "actions-qa",
            "check",
            "--file",
            "{file}",
        ]

    def test_no_extended_command(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert strategy.extended_lint_command is None

    def test_no_json_output_is_requested(self, strategy: GitHubWorkflowLintStrategy) -> None:
        """The daemon passes the linter's plain output through and parses nothing."""
        assert "--format" not in strategy.default_lint_command

    def test_skip_paths_are_the_common_ones(self, strategy: GitHubWorkflowLintStrategy) -> None:
        assert "node_modules/" in strategy.skip_paths


class TestHandlesFile:
    @pytest.mark.parametrize(
        "path",
        [
            "/repo/.github/workflows/ci.yml",
            "/repo/.github/workflows/release.yaml",
            "/repo/sub/project/.github/workflows/x.yml",
        ],
    )
    def test_accepts_a_file_directly_inside_github_workflows(
        self, strategy: GitHubWorkflowLintStrategy, path: str
    ) -> None:
        assert strategy.handles_file(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/repo/.github/workflows/sub/x.yml",
            "/repo/.github/dependabot.yml",
            "/repo/config.yml",
            "/repo/workflows/ci.yml",
            "/repo/github/workflows/ci.yml",
            "/repo/.github/actions/setup/action.yml",
        ],
    )
    def test_declines_everything_else(
        self, strategy: GitHubWorkflowLintStrategy, path: str
    ) -> None:
        assert strategy.handles_file(path) is False

    def test_decides_from_the_path_alone(
        self, strategy: GitHubWorkflowLintStrategy, tmp_path: Path
    ) -> None:
        """The file may not exist yet (a Bash-predicted target)."""
        missing = tmp_path / ".github" / "workflows" / "absent.yml"
        assert strategy.handles_file(str(missing)) is True


class TestAcceptanceTests:
    def test_provides_acceptance_tests(self, strategy: GitHubWorkflowLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1

    def test_the_blocking_test_names_the_language_and_requires_the_tool(
        self, strategy: GitHubWorkflowLintStrategy
    ) -> None:
        """A machine without the optional linter must skip, not fail, the probe."""
        blocking = [
            t for t in strategy.get_acceptance_tests() if t.expected_decision == Decision.DENY
        ]
        assert blocking, "the strategy must prove a finding is reported"
        for test in blocking:
            assert test.required_tools == ["actions-qa"]
            assert any("GitHub Workflow" in pattern for pattern in test.expected_message_patterns)

    def test_probe_paths_are_workflow_paths(self, strategy: GitHubWorkflowLintStrategy) -> None:
        for test in strategy.get_acceptance_tests():
            assert test.tool_payload is not None
            file_path = test.tool_payload.tool_input["file_path"]
            assert strategy.handles_file(file_path), file_path

    def test_each_probe_fixture_root_is_its_own_repository(
        self, strategy: GitHubWorkflowLintStrategy
    ) -> None:
        """Task 1.1, measured against actions-qa v0.2.0: the linter analyses only the
        `.github/workflows/` of the nearest repository root, and exits 2 ("no lane
        analyses") for one anywhere below it. Inside a project the acceptance root is
        a subdirectory, so without its own `.git` the DENY probe is ALLOWED unchecked.
        """
        for test in strategy.get_acceptance_tests():
            assert test.tool_payload is not None
            fixture_root = Path(test.tool_payload.tool_input["file_path"]).parent.parent.parent
            assert f"git init -q {fixture_root}" in test.setup_commands, test.title


_REAL_LINTER = shutil.which("actions-qa")


@pytest.mark.skipif(_REAL_LINTER is None, reason="actions-qa is not installed (optional linter)")
class TestProbesAgainstTheRealLinter:
    """Each probe's content gives the exit code its expected decision assumes."""

    def test_probe_content_gives_the_expected_exit_code(
        self, strategy: GitHubWorkflowLintStrategy, tmp_path: Path
    ) -> None:
        assert _REAL_LINTER is not None
        expected_exit = {Decision.ALLOW: 0, Decision.DENY: 1}
        for test in strategy.get_acceptance_tests():
            assert test.tool_payload is not None
            name = Path(test.tool_payload.tool_input["file_path"]).name
            repo = tmp_path / name
            target = repo / ".github" / "workflows" / name
            target.parent.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            target.write_text(test.tool_payload.tool_input["content"], encoding="utf-8")
            result = subprocess.run(
                [_REAL_LINTER, "check", "--file", str(target)],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert result.returncode == expected_exit[test.expected_decision], (
                test.title,
                result.stdout,
                result.stderr,
            )
