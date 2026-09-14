"""The GitHub issue form and the generator must ask for the same things.

Plan 00403 Task 5.1. There are two routes into this tracker and only one of
them runs any checks. `hooks-daemon issue-report` refuses a report that skips
them; a web reporter meets the form instead, which can refuse nothing and can
only ASK. That asymmetry is fine — what is not fine is the two drifting apart,
because then a maintainer reading an issue cannot tell which questions were put
to the reporter at all.

So the field set is asserted against :class:`ReportFields` rather than against a
list written here. A field added to the generator and forgotten in the form
fails this test, which is the only thing that would notice: nothing else reads
`.github/`, and `rg` skips it by default.

The redaction wording is asserted too. It is the ONLY place the rule reaches
someone filing from a browser, who has no daemon to run the checks for them.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from claude_code_hooks_daemon.issue_report.assemble import ReportFields

_TEMPLATE_DIR: Final[Path] = Path(__file__).parent.parent.parent / ".github" / "ISSUE_TEMPLATE"
_DEFECT_FORM: Final[Path] = _TEMPLATE_DIR / "1-defect.yml"
_OTHER_FORM: Final[Path] = _TEMPLATE_DIR / "2-other.yml"
_CONFIG: Final[Path] = _TEMPLATE_DIR / "config.yml"

#: Fields the form deliberately does not ask for, each with the reason. A bare
#: exemption list would hide exactly the drift this file exists to catch, so
#: every entry has to say why the form is right not to ask.
_NOT_ASKED: Final[dict[str, str]] = {
    "generated_at": (
        "GitHub stamps the creation date on the issue itself. Asking a reporter "
        "to type today's date collects a fact that is already recorded, and "
        "invites a wrong one"
    ),
}


def _load(path: Path) -> dict[str, Any]:
    parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), f"{path.name} must be a mapping"
    return parsed


def _field_ids(form: dict[str, Any]) -> set[str]:
    return {block["id"] for block in form["body"] if "id" in block}


def _all_text(form: dict[str, Any]) -> str:
    """Every string anywhere in the form, for asserting on its wording."""
    chunks: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            chunks.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(form)
    return "\n".join(chunks).lower()


class TestTheFormMirrorsTheGenerator:
    def test_every_generator_field_is_asked_for(self) -> None:
        asked = _field_ids(_load(_DEFECT_FORM))
        expected = {f.name for f in dataclasses.fields(ReportFields)} - set(_NOT_ASKED)

        missing = sorted(expected - asked)

        assert not missing, (
            f"The defect form does not ask for: {missing}.\n\n"
            "`ReportFields` is the generator's whole input surface. A field it "
            "collects and the form does not is a question only half of your "
            "reporters are ever asked. Add an input with that `id`, or add it to "
            "_NOT_ASKED above with the reason the form is right not to ask."
        )

    def test_nothing_is_exempted_without_a_reason(self) -> None:
        """The vacuity guard: an empty reason would silence the test above."""
        for name, reason in _NOT_ASKED.items():
            assert reason.strip(), f"{name} is exempted with no reason"

    def test_no_exemption_names_a_field_that_no_longer_exists(self) -> None:
        real = {f.name for f in dataclasses.fields(ReportFields)}

        stale = sorted(set(_NOT_ASKED) - real)

        assert not stale, f"_NOT_ASKED names fields ReportFields no longer has: {stale}"

    @pytest.mark.parametrize(
        "field_id",
        ["summary", "expected", "observed", "reproduction", "config_considered", "source_citation"],
    )
    def test_the_load_bearing_fields_are_required(self, field_id: str) -> None:
        """The four the generator refuses without, plus the two gates.

        `handler` is deliberately optional in both — not every defect belongs to
        one, and the daemon has a CLI, an installer and a config loader.
        """
        blocks = {b["id"]: b for b in _load(_DEFECT_FORM)["body"] if "id" in b}

        assert blocks[field_id].get("validations", {}).get("required") is True

    def test_the_handler_field_is_optional(self) -> None:
        blocks = {b["id"]: b for b in _load(_DEFECT_FORM)["body"] if "id" in b}

        assert not blocks["handler"].get("validations", {}).get("required")


class TestTheRedactionRuleReachesAWebReporter:
    @pytest.mark.parametrize("term", ["public", "cannot be retracted", "logs", "credential"])
    def test_the_defect_form_states_the_rule(self, term: str) -> None:
        assert term in _all_text(_load(_DEFECT_FORM))

    def test_the_catch_all_form_states_it_too(self) -> None:
        """The escape hatch must not also be an escape from the rule."""
        text = _all_text(_load(_OTHER_FORM))

        assert "public" in text and "cannot be retracted" in text

    def test_the_defect_form_points_at_the_generator(self) -> None:
        assert "issue-report" in _all_text(_load(_DEFECT_FORM))

    def test_the_defect_form_keeps_exactly_two_required_acknowledgements(self) -> None:
        """Five documents promise this, and nothing else checks it.

        `issue_filing_gate` allows `--web` — a deliberate hole — and the reason
        given for it, in the handler source, its deny message, its CLAUDE.md
        guidance, `BUG_REPORTING.md`, the bundled skill and the release
        callout, is that a human meets two acknowledgements before anything is
        published. Delete a checkbox here and every one of those becomes a
        false promise about a PUBLIC tracker, silently.

        The count is asserted exactly rather than as "at least one": a third
        acknowledgement is not a free improvement either, because the same
        documents say two.
        """
        required = [
            option
            for element in _load(_DEFECT_FORM)["body"]
            if element.get("type") == "checkboxes"
            for option in element["attributes"]["options"]
            if option.get("required") is True
        ]

        assert len(required) == 2

    def test_the_catch_all_form_carries_the_rule_without_checkboxes(self) -> None:
        """Deliberate, and the reason the prose elsewhere had to be made precise.

        A free-text form asks for no structure — that is the whole point of it,
        and adding ticks would recreate the barrier it exists to remove. So the
        "two acknowledgements" promise is true of the DEFECT form only, and
        every document making it now says which form it means.
        """
        has_checkboxes = any(
            element.get("type") == "checkboxes" for element in _load(_OTHER_FORM)["body"]
        )

        assert has_checkboxes is False


class TestRouting:
    def test_blank_issues_are_off(self) -> None:
        """A blank issue is a route past every warning the forms carry."""
        assert _load(_CONFIG)["blank_issues_enabled"] is False

    def test_something_else_exists_so_nothing_is_unfileable(self) -> None:
        """Turning blank issues off must not turn a question into a dead end."""
        assert _OTHER_FORM.exists()
        assert not _field_ids(_load(_OTHER_FORM)) - {"body"}

    def test_the_contact_links_point_at_the_sop(self) -> None:
        urls = " ".join(link["url"] for link in _load(_CONFIG)["contact_links"])

        assert "BUG_REPORTING.md" in urls

    def test_every_contact_link_names_this_repository(self) -> None:
        """A link to a fork or an old name sends a reporter somewhere we do not read."""
        for link in _load(_CONFIG)["contact_links"]:
            assert "Edmonds-Commerce-Limited/claude-code-hooks-daemon" in link["url"]
