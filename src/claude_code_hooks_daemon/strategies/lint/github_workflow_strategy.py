"""GitHub Actions workflow lint strategy (Plan 00621).

Routes a workflow file to the external ``actions-qa`` linter (the
``LongTermSupport/actions-qa-ci`` project; the executable is ``actions-qa``).
The rule set lives in that linter and is never copied here: this strategy says
WHICH files, WHICH command, and how to read the exit code. The linter's plain
output is passed through as the lint output; no JSON is asked for or parsed.

**Why it narrows by path.** It shares ``.yml``/``.yaml`` with the Ansible
strategy, and only a file DIRECTLY inside a ``.github/workflows/`` directory is
a workflow GitHub runs (a nested directory is ignored by GitHub, and
``.github/dependabot.yml`` or an action's ``action.yml`` is a different
schema). The decision is path-only, so it holds for a file not yet written.

**Why only exit 1 is a failure.** The linter documents 0 nothing to report,
1 findings, 2 a wrong command line or project record, 3 the toolchain failed,
4 no verdict reached. Only 1 is about the file. Naming the findings code,
rather than the fault codes, makes an older version (no ``--file``) or an
undocumented exit fail open.

**Why a missing tool is silent.** The linter is optional and most projects do
not have it, so "install it" on every workflow edit would be noise. Suggesting
it is the session-start advisory's job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

_LANGUAGE_NAME: Final = "GitHub Workflow"
_EXTENSIONS: Final[tuple[str, ...]] = (".yml", ".yaml")
_TOOL: Final = "actions-qa"
_DEFAULT_LINT_COMMAND: Final = f"{_TOOL} check --file {{file}}"
_FINDINGS_EXIT_CODES: Final[frozenset[int]] = frozenset({1})

#: GitHub runs only the files directly inside ``<repo>/.github/workflows/``.
_WORKFLOWS_DIR: Final = "workflows"
_GITHUB_DIR: Final = ".github"

#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR: Final = "acceptance-test-lint-github-workflow"

#: A workflow actions-qa v0.2.0 reports 0 findings for (Task 1.1). Shared with
#: the Ansible "a workflow is not claimed" probe, which this strategy also sees:
#: its ALLOW must not depend on whether the linter is installed.
CLEAN_WORKFLOW_SAMPLE: Final = (
    "name: ci\n"
    "on:\n"
    "  pull_request:\n"
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    timeout-minutes: 10\n"
    "    steps:\n"
    "      - run: echo ok\n"
)
# A job with no `runs-on` is rejected by the linter's actionlint lane.
_FAULTY_WORKFLOW: Final = (
    "name: ci\non:\n  pull_request:\njobs:\n  build:\n    steps:\n      - run: echo ok\n"
)


class GitHubWorkflowLintStrategy:
    """Lint enforcement strategy for GitHub Actions workflow files.

    Default: ``actions-qa check --file`` (optional external linter)
    Extended: none
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return None

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return COMMON_SKIP_PATHS

    @property
    def findings_exit_codes(self) -> frozenset[int]:
        """Only exit 1 is a finding; 2, 3, 4 and anything else are faults."""
        return _FINDINGS_EXIT_CODES

    @property
    def lint_tool_is_optional(self) -> bool:
        """The linter is an optional adoption, so its absence is silent."""
        return True

    def handles_file(self, file_path: str) -> bool:
        """Whether the file sits directly inside a ``.github/workflows/`` directory.

        Args:
            file_path: Path the registry matched by extension. May not exist.

        Returns:
            True for a workflow GitHub would run, False for every other YAML.
        """
        parent = Path(file_path).parent
        return parent.name == _WORKFLOWS_DIR and parent.parent.name == _GITHUB_DIR

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the GitHub workflow lint strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = acceptance_path(_FIXTURE_DIR)
        workflows = acceptance_path(_FIXTURE_DIR, _GITHUB_DIR, _WORKFLOWS_DIR)
        # actions-qa analyses only the `.github/workflows/` of the nearest
        # repository root and exits 2 for one below it (measured, Task 1.1),
        # so the fixture root must be a repository of its own.
        setup = [f"mkdir -p {workflows}", f"git init -q {fixture_root}"]
        probe_valid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, _GITHUB_DIR, _WORKFLOWS_DIR, "ok.yml"),
                "content": CLEAN_WORKFLOW_SAMPLE,
            },
        )
        probe_faulty = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(
                    _FIXTURE_DIR, _GITHUB_DIR, _WORKFLOWS_DIR, "faulty.yml"
                ),
                "content": _FAULTY_WORKFLOW,
            },
        )

        return [
            AcceptanceTest(
                title="GitHub Workflow lint - a workflow edit is never blocked by a fault",
                command=probe_valid.as_instruction(),
                tool_payload=probe_valid,
                description=(
                    "A well-formed workflow is allowed. Where actions-qa is not installed "
                    "the edit is also allowed, silently: the linter is optional."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored acceptance directory - safe. "
                    "Creates a temporary workflow file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=setup,
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="GitHub Workflow lint - a job with no runs-on is reported",
                command=probe_faulty.as_instruction(),
                tool_payload=probe_faulty,
                description=(
                    "actions-qa exits 1 (findings) for a job missing runs-on; the write "
                    "has already landed, so the denial is a failure report to repair "
                    "with Edit."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"GitHub Workflow lint FAILED", r"faulty\.yml"],
                # Optional external linter: without it the strategy is silent by
                # design, so the probe can only score where the tool exists.
                required_tools=[_TOOL],
                safety_notes=(
                    "Inside the gitignored acceptance directory - safe. "
                    "Creates a temporary faulty workflow file."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=setup,
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
