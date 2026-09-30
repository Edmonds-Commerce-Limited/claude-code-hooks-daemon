"""Release-time guard: a shipped template must not assert a superseded truth (issue #63).

A truth-changes entry records a statement that WAS true and no longer is. The
daemon also ships its own documents as templates (deployed into every client),
so a template that still asserts a recorded ``was`` is the daemon contradicting
its own manifest. That happened once: v3.67.0 recorded "six journal categories"
as superseded while ``PlanWorkflow.core.md`` still listed six.

A ``was`` is prose, matched semantically by an LLM, so it is never quotable
verbatim and a literal match of it would guard nothing. The manifest instead
lets an entry name the exact phrases the old truth had in shipped text
(``stale_phrases``). This test fails while any such phrase is still in a
template, so the class is caught at release time rather than by a client.
"""

import re
from pathlib import Path

from claude_code_hooks_daemon.install.truth_changes import (
    TruthChange,
    load_truth_changes_between,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TRUTH_CHANGES_DIR = _REPO_ROOT / "CLAUDE" / "UPGRADES" / "truth-changes"
_TEMPLATES_DIR = _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "install" / "templates"
_MKPLAN_TEMPLATE = _TEMPLATES_DIR / "mkplan.bash"
_PLAN_WORKFLOW_CORE = _TEMPLATES_DIR / "core" / "PlanWorkflow.core.md"
_ALL_VERSIONS_FROM = "0.0.0"
_ALL_VERSIONS_TO = "999.0.0"


def _normalise(text: str) -> str:
    """Collapse whitespace so a phrase matches across the template's line wraps."""
    return " ".join(text.split())


def find_stale_phrases(
    changes: list[TruthChange], template_texts: dict[str, str]
) -> list[tuple[str, str, str]]:
    """Return ``(entry, template, phrase)`` for each stale phrase still shipped."""
    normalised = {name: _normalise(text) for name, text in template_texts.items()}
    hits: list[tuple[str, str, str]] = []
    for change in changes:
        for phrase in change.stale_phrases:
            needle = _normalise(phrase)
            for name, text in normalised.items():
                if needle in text:
                    hits.append((change.id or change.was.strip()[:40], name, phrase))
    return hits


def _shipped_template_texts() -> dict[str, str]:
    return {
        str(path.relative_to(_TEMPLATES_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_TEMPLATES_DIR.rglob("*"))
        if path.is_file() and path.suffix in {".md", ".bash", ".sh", ".yaml", ".txt"}
    }


class TestFindStalePhrases:
    def test_phrase_spanning_a_line_wrap_is_found(self) -> None:
        change = TruthChange(was="w", now="n", id="x", stale_phrases=("`blocker`, `handoff`;",))
        texts = {"a.md": "one of `thought`, `blocker`,\n`handoff`; add --ref"}
        assert find_stale_phrases([change], texts) == [("x", "a.md", "`blocker`, `handoff`;")]

    def test_entry_without_phrases_never_matches(self) -> None:
        change = TruthChange(was="six categories", now="n")
        assert find_stale_phrases([change], {"a.md": "six categories"}) == []

    def test_absent_phrase_is_clean(self) -> None:
        change = TruthChange(was="w", now="n", stale_phrases=("old claim",))
        assert find_stale_phrases([change], {"a.md": "new claim"}) == []


class TestShippedTemplatesAssertNoSupersededTruth:
    def test_no_template_carries_a_recorded_stale_phrase(self) -> None:
        manifests = load_truth_changes_between(
            _ALL_VERSIONS_FROM, _ALL_VERSIONS_TO, truth_changes_dir=_TRUTH_CHANGES_DIR
        )
        changes = [change for manifest in manifests for change in manifest.changes]
        hits = find_stale_phrases(changes, _shipped_template_texts())
        assert hits == [], (
            "A shipped template still asserts a truth a truth-changes entry records as "
            f"superseded: {hits}. Update the template to the entry's NOW text."
        )

    def test_the_journal_category_entry_declares_its_stale_phrase(self) -> None:
        """The guard is only as good as the entries that feed it: pin the known case."""
        manifests = load_truth_changes_between(
            "3.66.0", "3.67.0", truth_changes_dir=_TRUTH_CHANGES_DIR
        )
        entry = next(
            change
            for manifest in manifests
            for change in manifest.changes
            if change.id == "journal-correction-entry"
        )
        assert entry.stale_phrases, "journal-correction-entry must name its stale phrase"


class TestPlanWorkflowCoreJournalCategories:
    def test_every_mkplan_category_is_listed_in_the_core_doc(self) -> None:
        """The script is the source of truth for legal categories; the doc must match."""
        declaration = re.search(r"JOURNAL_CATEGORIES=\(([^)]*)\)", _MKPLAN_TEMPLATE.read_text())
        assert declaration is not None
        categories = declaration.group(1).split()
        assert "correction" in categories
        doc = _normalise(_PLAN_WORKFLOW_CORE.read_text())
        missing = [c for c in categories if f"`{c}`" not in doc]
        assert missing == []
