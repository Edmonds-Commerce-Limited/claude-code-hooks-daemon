"""The ``docs-optimise`` skill: shipped source shape and deployment to clients.

Plan 00532 Phase 4. The skill is a shim (R7b): invocation mechanics in
``SKILL.md``, the procedure body in a bundled reference, and the rules cited by
pointer to the core document and the loading-rules contract.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.skills import deploy_skills

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_DIR = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "docs-optimise"
SKILL_MD = SKILL_DIR / "SKILL.md"
PROCEDURE_MD = SKILL_DIR / "references" / "procedure.md"

#: A shim stays short; the procedure lives beside it.
MAX_SKILL_LINES = 80


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must open with YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


class TestSkillSource:
    """The shipped source tree."""

    def test_skill_and_procedure_exist(self) -> None:
        assert SKILL_MD.is_file()
        assert PROCEDURE_MD.is_file()

    def test_frontmatter_names_the_skill(self) -> None:
        fields = _frontmatter(SKILL_MD.read_text())
        assert fields["name"] == "docs-optimise"
        assert fields["description"]
        assert fields["user-invocable"] == "true"

    def test_skill_is_a_shim(self) -> None:
        assert len(SKILL_MD.read_text().splitlines()) <= MAX_SKILL_LINES

    def test_skill_points_rather_than_restates(self) -> None:
        text = SKILL_MD.read_text()
        assert "docs-qa --footprint --json" in text
        assert "DocumentationStrategy" in text
        assert "contracts/claude-code-instructions" in text
        assert "references/procedure.md" in text

    def test_skill_states_the_proposal_only_contract(self) -> None:
        text = SKILL_MD.read_text()
        assert "untracked/scratch/docs-optimise/" in text
        assert "never" in text.lower()

    def test_skill_closes_with_both_handoffs(self) -> None:
        text = SKILL_MD.read_text() + PROCEDURE_MD.read_text()
        assert "/docs-qa" in text
        assert "/doctor prompt-audit" in text


class TestProcedure:
    """The procedure body the shim points at."""

    @pytest.fixture
    def procedure(self) -> str:
        return PROCEDURE_MD.read_text()

    def test_classifies_into_the_four_classes(self, procedure: str) -> None:
        for klass in ("resident", "path-scopable", "nested-module", "on-demand"):
            assert klass in procedure

    def test_names_both_rulesets(self, procedure: str) -> None:
        assert "documentation.enabled" in procedure
        assert "R6" in procedure and "R7a" in procedure and "R7d" in procedure

    def test_report_opens_by_stating_the_ruleset(self, procedure: str) -> None:
        assert "first lines" in procedure

    def test_never_touches_tracked_files_or_allowlists(self, procedure: str) -> None:
        assert "resident_at_imports" in procedure
        assert "grandfather_allowlist" in procedure
        assert "tracked" in procedure

    def test_counts_but_never_proposes_unproposable_files(self, procedure: str) -> None:
        for name in ("hooksdaemon", "CLAUDE.local.md", "~/.claude"):
            assert name in procedure

    def test_writes_a_unified_patch(self, procedure: str) -> None:
        assert "unified patch" in procedure
        assert "proposal.patch" in procedure


class TestDeployment:
    """``deploy_skills`` ships it to every client with no config gate."""

    def test_deploy_skills_deploys_docs_optimise(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()

        deploy_skills(REPO_ROOT, project)

        deployed = project / ".claude" / "skills" / "docs-optimise"
        assert (deployed / "SKILL.md").read_bytes() == SKILL_MD.read_bytes()
        assert (deployed / "references" / "procedure.md").is_file()
