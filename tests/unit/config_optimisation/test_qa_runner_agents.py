"""Detecting a dedicated full-QA runner agent for the optimise review (Plan 00518).

A project that runs its full QA gate through a dedicated agent must be told to
enable ``subagent_full_qa_blocker`` WITH ``exempt_agent_types`` naming that
agent, not to leave the handler off.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config_optimisation.checklist import (
    build_checklist,
    render_report,
    report_as_json,
)
from claude_code_hooks_daemon.config_optimisation.qa_runner_agents import (
    find_full_qa_runner_agents,
)
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.relevance import RelevanceContext

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BLOCKER_PATH = "handlers.pre_tool_use.subagent_full_qa_blocker"


@pytest.fixture(autouse=True)
def _project_context() -> None:
    ProjectContext.initialize(_REPO_ROOT / ".claude" / "hooks-daemon.yaml")


def _agent(root: Path, file_stem: str, description: str, name: str | None = None) -> None:
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / f"{file_stem}.md").write_text(
        f"---\nname: {name or file_stem}\ndescription: {description}\ntools: Bash\n---\n\nBody\n"
    )


def _disabled_blocker_config() -> dict[str, Any]:
    return {"handlers": {"pre_tool_use": {"subagent_full_qa_blocker": {"enabled": False}}}}


class TestFindFullQaRunnerAgents:
    def test_no_agents_directory_finds_nothing(self, tmp_path: Path) -> None:
        assert find_full_qa_runner_agents(tmp_path) == ()

    def test_this_repos_full_runner_is_found(self) -> None:
        assert "qa-full-runner" in find_full_qa_runner_agents(_REPO_ROOT)

    def test_php_qa_ci_style_pipeline_runner_is_found(self, tmp_path: Path) -> None:
        _agent(tmp_path, "php-qa-ci_full-pipeline-runner", "Runs the pipeline")
        assert find_full_qa_runner_agents(tmp_path) == ("php-qa-ci_full-pipeline-runner",)

    def test_frontmatter_name_wins_over_file_stem(self, tmp_path: Path) -> None:
        _agent(tmp_path, "whatever", "Runs it", name="full-gate-runner")
        assert find_full_qa_runner_agents(tmp_path) == ("full-gate-runner",)

    def test_targeted_only_runner_is_not_proposed(self, tmp_path: Path) -> None:
        _agent(tmp_path, "qa-runner", "Targeted QA; never runs the full suite")
        assert find_full_qa_runner_agents(tmp_path) == ()

    def test_full_without_runner_is_not_proposed(self, tmp_path: Path) -> None:
        _agent(tmp_path, "full-qa-fixer", "Fixes things after a full run")
        assert find_full_qa_runner_agents(tmp_path) == ()

    def test_result_is_sorted_and_unique(self, tmp_path: Path) -> None:
        _agent(tmp_path, "z-full-qa-runner", "x")
        _agent(tmp_path, "a-full-qa-runner", "x")
        _agent(tmp_path, "other-file", "x", name="a-full-qa-runner")
        assert find_full_qa_runner_agents(tmp_path) == ("a-full-qa-runner", "z-full-qa-runner")

    def test_full_runner_without_a_qa_scope_is_not_proposed(self, tmp_path: Path) -> None:
        _agent(tmp_path, "full-runner", "x")
        assert find_full_qa_runner_agents(tmp_path) == ()

    def test_file_without_frontmatter_falls_back_to_stem(self, tmp_path: Path) -> None:
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "full-qa-runner.md").write_text("no frontmatter here\n")
        assert find_full_qa_runner_agents(tmp_path) == ("full-qa-runner",)


class TestRecommendation:
    def _blocker(self, root: Path) -> Any:
        items = build_checklist(
            _disabled_blocker_config(),
            RelevanceContext(project_root=root, languages=frozenset()),
        )
        return next(item for item in items if item.config_path == _BLOCKER_PATH)

    def test_found_agent_is_named_in_the_recommendation(self, tmp_path: Path) -> None:
        _agent(tmp_path, "php-qa-ci_full-pipeline-runner", "Runs the pipeline")
        item = self._blocker(tmp_path)
        assert item.exempt_agent_types == ("php-qa-ci_full-pipeline-runner",)
        report = render_report([item])
        assert "exempt_agent_types: [php-qa-ci_full-pipeline-runner]" in report

    def test_no_agent_leaves_the_recommendation_unchanged(self, tmp_path: Path) -> None:
        item = self._blocker(tmp_path)
        assert item.exempt_agent_types == ()
        assert "exempt_agent_types" not in render_report([item])

    def test_targeted_only_agent_is_not_proposed(self, tmp_path: Path) -> None:
        _agent(tmp_path, "qa-runner", "Targeted QA; never runs the full suite")
        item = self._blocker(tmp_path)
        assert item.exempt_agent_types == ()
        assert "exempt_agent_types" not in render_report([item])

    def test_other_handlers_never_carry_a_proposal(self, tmp_path: Path) -> None:
        _agent(tmp_path, "qa-full-runner", "x")
        items = build_checklist({}, RelevanceContext(project_root=tmp_path, languages=frozenset()))
        carrying = [i.config_path for i in items if i.exempt_agent_types]
        assert carrying == [_BLOCKER_PATH]

    def test_json_carries_the_proposal(self, tmp_path: Path) -> None:
        _agent(tmp_path, "qa-full-runner", "x")
        data = report_as_json([self._blocker(tmp_path)])
        assert data["items"][0]["exempt_agent_types"] == ["qa-full-runner"]
