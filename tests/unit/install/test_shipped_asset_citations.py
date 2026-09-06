"""No SHIPPED asset may cite a client document that does not exist (Plan 00334).

The durable half of Decision 4. ``test_core_doc_deployment.py`` pins a
hand-maintained list of documents guidance names — which is useful, and is also
the very shape of the root cause: *a guidance string naming a client path is
written by hand, with nothing connecting it to the deploy*. A list someone has
to remember to extend cannot catch the citation nobody remembered.

This module scans instead. It found 21 citations across 16 files that the hand
list had missed entirely.

Scope: the trees whose contents are COPIED into a client project —
``install/templates/`` and ``skills/``. Those files are read by an agent
standing in the CLIENT's root, where a bare ``CLAUDE/X.md`` resolves against
the client's own tree and finds nothing.

Deliberately NOT the whole package. A docstring in ``constants/priority.py`` is
read inside the daemon's own checkout, where ``CLAUDE/HANDLER_DEVELOPMENT.md``
resolves correctly relative to the daemon root. Widening the scan to those
would report a defect that does not exist, and a check that cries wolf is
turned off.

A citation is acceptable in exactly three ways:

1. the document is one the daemon DEPLOYS (``CORE_DOC_NAMES``, plus
   ``PlanJournalling.md`` which the plan-workflow bootstrap seeds);
2. it is QUALIFIED as living in the daemon's clone, which is the remedy for a
   document deliberately out of the roster (Decision 6);
3. it is already written as an explicit vendored path.

Qualifying in prose rather than spelling ``.claude/hooks-daemon/CLAUDE/X.md``
is not laziness — that literal path is WRONG in self-install mode, where the
daemon root IS the project root, and ``utils/cli_command`` records what a
confidently-wrong shipped path costs: agents concluded the package was broken
and tried to "repair" working installations.

What this scanner does NOT cover
--------------------------------

It treats a deployed document as present, full stop. Each one is actually
deployed under its OWN gate, so the exact invariant is *the citing file's gate
implies the cited document's gate* — which needs a gate recorded for every
shipped skill, agent and template, not just for the documents.

Enforcing the cruder approximation (a conditionally-deployed document needs a
conditionally-worded citation) was tried and reverted: it fired on SEVEN
legitimate citations — a plan-workflow asset naming ``PlanJournalling``, a core
document naming its own override — all of which share the gate of the thing
they cite. A check that cries wolf gets switched off, which would cost more
than the gap.

The gap is real and has been paid twice, both found by hand:
``hooks-daemon-docs-qa.md`` is gated on ``agents.docs_qa.enabled`` — a THIRD
switch, independent of the plan workflow and the documentation subsystem — and
cited ``CLAUDE/PlanWorkflow.md``, which deploys only with the plan workflow on.
``skills/docs-qa/SKILL.md`` deploys unconditionally and cited
``CLAUDE/DocumentationStrategy.md`` the same way. Both now state the condition
in prose.

**A CROSS-SUBSYSTEM citation is the shape to check by hand** until the gate
model exists: a file deployed under one switch naming a document deployed
under another.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.core_docs import CORE_DOC_NAMES

_PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "src" / "claude_code_hooks_daemon"

#: The trees copied into a client project verbatim.
_SHIPPED_TREES: tuple[Path, ...] = (
    _PACKAGE_ROOT / "install" / "templates",
    _PACKAGE_ROOT / "skills",
)

#: Any ``CLAUDE/<Name>.md`` reference. The capture is the base name.
_CITATION = re.compile(r"CLAUDE/([A-Za-z0-9_-]+)\.md")

#: Documents an install produces in the client's own tree. ``PlanJournalling``
#: is seeded by the plan-workflow bootstrap rather than the core-doc mechanism,
#: so it is named here rather than derived.
_DEPLOYED: frozenset[str] = frozenset(CORE_DOC_NAMES) | {"PlanJournalling"}


#: Phrases that place the document in the daemon's own clone. Matched against a
#: window around the citation, because these banners wrap across lines and the
#: qualifier routinely lands on the line ABOVE the path.
_QUALIFIERS: tuple[str, ...] = ("daemon clone", "daemon repo", ".claude/hooks-daemon/CLAUDE/")

#: How far either side of a citation to look for its qualifier. Two lines
#: covers every wrapped banner in the shipped set; a larger window would start
#: crediting a qualifier belonging to a different sentence.
_WINDOW = 2

#: This repository's own agent-docs tree. A name with no document here is a
#: PLACEHOLDER in an example, not a citation -- ``CLAUDE/SomeDoc.md`` in the
#: ``ssot-quote`` syntax illustration names nothing that could be shipped or
#: not shipped. Deriving that from the filesystem rather than listing the
#: placeholders keeps the check from needing maintenance every time an example
#: is reworded, which is the failure mode this scanner exists to replace.
_OUR_DOCS_DIR = Path(__file__).resolve().parents[3] / "CLAUDE"


def _names_a_real_document(name: str) -> bool:
    return (_OUR_DOCS_DIR / f"{name}.md").is_file()


#: Suffixes of shipped files that are not text a reader follows citations in.
#: An allowlist was the first spelling and it silently excluded the
#: EXTENSIONLESS ``templates/hooks-daemon`` wrapper — a real shipped file that
#: happens to carry no citation today. A denylist fails the safe way: a new
#: shipped file type is scanned by default rather than skipped in silence.
_NON_TEXT_SUFFIXES: frozenset[str] = frozenset({".pyc", ".png", ".jpg", ".gif", ".ico", ".zip"})


def _shipped_files() -> list[Path]:
    return sorted(
        path
        for tree in _SHIPPED_TREES
        for path in tree.rglob("*")
        if path.is_file() and path.suffix not in _NON_TEXT_SUFFIXES
    )


def _unqualified_citations(path: Path) -> list[tuple[int, str]]:
    """Citations in ``path`` that are neither deployed nor qualified."""
    lines = path.read_text(encoding="utf-8").splitlines()
    offences: list[tuple[int, str]] = []

    for index, line in enumerate(lines):
        for match in _CITATION.finditer(line):
            name = match.group(1)
            if name in _DEPLOYED or not _names_a_real_document(name):
                continue
            # Whitespace-normalised: these banners wrap mid-phrase, so "the
            # daemon\nclone's CLAUDE/..." must read as qualified. Matching the
            # raw window would report the wrap as a defect.
            window = " ".join(
                " ".join(lines[max(0, index - _WINDOW) : index + _WINDOW + 1]).split()
            )
            if any(qualifier in window for qualifier in _QUALIFIERS):
                continue
            offences.append((index + 1, line.strip()))

    return offences


class TestShippedAssetsCiteOnlyReachableDocuments:
    @pytest.mark.parametrize("path", _shipped_files(), ids=lambda p: p.name)
    def test_no_unqualified_client_citation(self, path: Path) -> None:
        offences = _unqualified_citations(path)

        assert not offences, (
            f"{path.relative_to(_PACKAGE_ROOT)} is deployed into client "
            "projects and cites a CLAUDE/ document the client does not have:\n"
            + "\n".join(f"  line {line}: {text}" for line, text in offences)
            + "\n\nEither add the document to CORE_DOC_NAMES so the daemon "
            "deploys it, or qualify the citation as the daemon clone's (do NOT "
            "write .claude/hooks-daemon/... literally — that path is wrong in "
            "self-install mode)."
        )


class TestTheScanCanActuallyFail:
    """A scanner that can only pass is a scanner nobody can trust.

    Cheap to write, and the alternative is a green check that would stay green
    if the regex silently stopped matching — which is how this whole plan's
    defect survived so long in the first place.
    """

    def test_an_unqualified_citation_is_caught(self, tmp_path: Path) -> None:
        offender = tmp_path / "offender.md"
        offender.write_text("See CLAUDE/HANDLER_DEVELOPMENT.md for more.\n", encoding="utf-8")

        assert _unqualified_citations(offender)

    def test_a_qualified_citation_is_accepted(self, tmp_path: Path) -> None:
        fine = tmp_path / "fine.md"
        fine.write_text(
            "See the daemon clone's CLAUDE/HANDLER_DEVELOPMENT.md for more.\n", encoding="utf-8"
        )

        assert not _unqualified_citations(fine)

    def test_a_qualifier_on_the_previous_line_is_accepted(self, tmp_path: Path) -> None:
        """The banners wrap; the qualifier routinely sits on the line above."""
        wrapped = tmp_path / "wrapped.md"
        wrapped.write_text(
            "changes are discarded. See the daemon clone's\nCLAUDE/LLM-INSTALL.md, section two.\n",
            encoding="utf-8",
        )

        assert not _unqualified_citations(wrapped)

    def test_a_deployed_document_needs_no_qualifier(self, tmp_path: Path) -> None:
        deployed = tmp_path / "deployed.md"
        deployed.write_text("See CLAUDE/PlanWorkflow.md for the workflow.\n", encoding="utf-8")

        assert not _unqualified_citations(deployed)

    def test_a_placeholder_name_is_not_a_citation(self, tmp_path: Path) -> None:
        """``CLAUDE/SomeDoc.md`` in a syntax illustration names nothing that
        could be shipped or not shipped, so it cannot be an unkept promise."""
        example = tmp_path / "example.md"
        example.write_text("<!-- ssot-quote: CLAUDE/SomeDoc.md#anchor -->\n", encoding="utf-8")

        assert not _unqualified_citations(example)

    def test_a_real_document_is_still_judged(self, tmp_path: Path) -> None:
        """The placeholder rule must not become a blanket amnesty: a name that
        IS one of this repo's documents is held to the qualifier requirement."""
        real = tmp_path / "real.md"
        real.write_text("See CLAUDE/PROJECT_HANDLERS.md for the guide.\n", encoding="utf-8")

        assert _unqualified_citations(real)
