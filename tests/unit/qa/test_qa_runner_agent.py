"""The qa-runner agent definition pins its scope-deciding contract (Plan 00475 Task 2.2)."""

from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[3] / ".claude" / "agents" / "qa-runner.md"


@pytest.fixture(scope="module")
def agent_text() -> str:
    """The agent definition text."""
    return AGENT_PATH.read_text()


def test_frontmatter_names_the_agent_and_keeps_tools_read_only(agent_text: str) -> None:
    """The agent stays a read-only runner: no Edit or Write tool."""
    frontmatter = agent_text.split("---")[1]
    assert "name: qa-runner" in frontmatter
    tools_line = next(ln for ln in frontmatter.splitlines() if ln.startswith("tools:"))
    assert "Edit" not in tools_line
    assert "Write" not in tools_line


@pytest.mark.parametrize("field", ["VERDICT", "SCOPE", "REASONING", "FAILURES"])
def test_report_names_each_fixed_field(agent_text: str, field: str) -> None:
    """The fixed report shape names every field."""
    assert field in agent_text


def test_reads_the_change_set(agent_text: str) -> None:
    """The agent derives scope from the diff against the merge base or a range."""
    assert "git diff --name-only" in agent_text
    assert "--range" in agent_text
    assert "--base" in agent_text


def test_points_at_qa_md_for_the_rules(agent_text: str) -> None:
    """The scope rules live in CLAUDE/QA.md; the agent points there."""
    assert "CLAUDE/QA.md" in agent_text


def test_routes_docs_only_and_code_changes(agent_text: str) -> None:
    """Docs-only changes get the docs tier; code gets the changed tier."""
    assert "docs-only" in agent_text
    assert "llm_qa.py changed" in agent_text


def test_markdown_change_still_runs_the_mapped_tests(agent_text: str) -> None:
    """A document tests read is not docs-only: mapped tests run, and `changed` is the fallback."""
    assert "changed_tests" in agent_text
    assert "superset" in agent_text
    assert "when in doubt" in agent_text.lower()


def test_never_runs_the_full_suite(agent_text: str) -> None:
    """The full suite stays a release step for the main thread."""
    assert "NEVER" in agent_text
    assert "llm_qa.py all" in agent_text.replace("--read-only all", "")  # named only as forbidden
    assert "release step" in agent_text


def test_reports_but_never_fixes(agent_text: str) -> None:
    """Fixing belongs to qa-fixer."""
    assert "qa-fixer" in agent_text
