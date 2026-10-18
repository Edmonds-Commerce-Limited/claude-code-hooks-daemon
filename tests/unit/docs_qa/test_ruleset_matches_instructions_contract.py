"""The R7a wording agrees with the instructions contract (Plan 00532, Task 1.4)."""

from pathlib import Path

import pytest

from claude_code_hooks_daemon.docs_qa.instructions_contract import (
    CONTRACT_DIR_RELATIVE,
    load_contract,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CORE_DOC_COPIES = (
    "CLAUDE/core/DocumentationStrategy.core.md",
    "src/claude_code_hooks_daemon/install/templates/core/DocumentationStrategy.core.md",
)
_R7A_HEADING = "#### R7a"
_R7B_HEADING = "#### R7b"


def _r7a_section(relative: str) -> str:
    text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
    start = text.index(_R7A_HEADING)
    return text[start : text.index(_R7B_HEADING, start)]


class TestR7aFrontmatterWording:
    @pytest.mark.parametrize("relative", _CORE_DOC_COPIES)
    def test_r7a_does_not_prescribe_a_description_field(self, relative: str) -> None:
        """Claude Code ignores every rules frontmatter field but `paths` (G3-03)."""
        assert "`description`" not in _r7a_section(relative)

    @pytest.mark.parametrize("relative", _CORE_DOC_COPIES)
    def test_r7a_names_paths_as_the_only_frontmatter_field(self, relative: str) -> None:
        assert "`paths:` only" in _r7a_section(relative)

    def test_the_contract_still_pins_the_paths_only_fact(self) -> None:
        contract = load_contract(_REPO_ROOT / CONTRACT_DIR_RELATIVE)
        fact = next(f for f in contract.facts if f.id == "G3-03")
        assert "`paths` is the only frontmatter field" in fact.statement

    def test_the_two_core_doc_copies_are_identical(self) -> None:
        first, second = (
            (_REPO_ROOT / relative).read_text(encoding="utf-8") for relative in _CORE_DOC_COPIES
        )
        assert first == second
