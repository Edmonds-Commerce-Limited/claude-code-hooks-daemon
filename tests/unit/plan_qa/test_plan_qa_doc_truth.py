"""The plan workflow doc describes plan QA without restating its catalogue.

Plan 00466 N18. ``PlanWorkflow.core.md`` said the plan index was "linted
against one rule". That was already false once ``index-no-log`` existed, and
``plan-stats-arithmetic`` made it staler. A hand-kept count drifts every time a
check is added, so the page points at ``plan-qa --list-checks``, which lists
the registry, and these pins keep it that way in both copies of the deployed
template pair.
"""

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.plan_qa.checks import all_checks

_REPO_ROOT = Path(__file__).resolve().parents[3]
_COPIES = (
    _REPO_ROOT / "CLAUDE" / "core" / "PlanWorkflow.core.md",
    _REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "install"
    / "templates"
    / "core"
    / "PlanWorkflow.core.md",
)
_SECTION_START = "## Plan QA (automated enforcement)"
_NEXT_TOP_LEVEL_SECTION = re.compile(r"^## ", re.MULTILINE)
_LIST_COMMAND = "plan-qa --list-checks"
#: "one rule", "two checks", "3 rules" -- a count of the catalogue. "One check
#: catalogue" is a statement that there is a single catalogue, not a count.
_COUNTED_RULES = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(?:rules?|checks?)\b"
    r"(?!\s+catalogue)",
    re.IGNORECASE,
)
#: A backticked kebab-case token with at least one hyphen: how the page names a check.
_NAMED_CHECK = re.compile(r"`([a-z]+(?:-[a-z]+)+)`")


def _plan_qa_section(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index(_SECTION_START)
    rest = text[start + len(_SECTION_START) :]
    following = _NEXT_TOP_LEVEL_SECTION.search(rest)
    return rest if following is None else rest[: following.start()]


@pytest.mark.parametrize("path", _COPIES, ids=["deployed", "template"])
def test_the_section_states_no_count_of_rules(path: Path) -> None:
    counted = _COUNTED_RULES.findall(_plan_qa_section(path))
    assert counted == [], f"{path.name} counts the catalogue ({counted}); point at {_LIST_COMMAND}"


@pytest.mark.parametrize("path", _COPIES, ids=["deployed", "template"])
def test_the_section_points_at_the_registry_listing(path: Path) -> None:
    assert _LIST_COMMAND in _plan_qa_section(path)


@pytest.mark.parametrize("path", _COPIES, ids=["deployed", "template"])
def test_every_check_the_section_names_is_registered(path: Path) -> None:
    registered = {spec.check_id for spec in all_checks()}
    cli_flags = {"check-staged", "list-checks"}
    named = set(_NAMED_CHECK.findall(_plan_qa_section(path))) - cli_flags
    assert named - registered == set(), f"{path.name} names unregistered checks"


def test_the_two_copies_agree() -> None:
    deployed, template = (_plan_qa_section(path) for path in _COPIES)
    assert deployed == template
