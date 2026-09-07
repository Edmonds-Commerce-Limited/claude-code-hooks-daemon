"""Shipped documents must agree on where a report or scratch file goes.

A field report found this release shipping two contradictory instructions.
``src/CLAUDE.md`` said a bug report must go to ``untracked/scratch/`` because
"a path outside the repository is refused by ``project_containment``";
``BUG_REPORTING.md`` still told the reader to write to ``/tmp`` in three
places. Neither was quite right — the reporter ran the documented ``/tmp``
command verbatim and it was NOT denied, because ``project_containment`` judges
redirects and destination-bearing constructs, not a path handed to a script as
an ordinary argument.

Two separate failures, and the second is the worse one. Contradictory guidance
costs a reader some time; guidance that promises a containment guarantee the
handler does not provide teaches them to rely on a backstop that is not there.

These tests pin both: the guidance must point inside the repository, and the
claim about the handler must stay within what it actually covers.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Documents that tell a reader or agent where to put a report/scratch file.
_GUIDANCE_DOCS = (
    REPO_ROOT / "BUG_REPORTING.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "src" / "CLAUDE.md",
    REPO_ROOT / "tests" / "CLAUDE.md",
    REPO_ROOT / "CLAUDE" / "LLM-INSTALL.md",
    REPO_ROOT / "CLAUDE" / "LLM-UPDATE.md",
)

#: A report destination under ``/tmp`` — the diagnostic script being told to
#: WRITE there. Scoped to this construct on purpose: these documents also
#: contain deliberate ``/tmp`` uses that are not this defect, namely the
#: pre-install bootstrap fetch (``curl -o /tmp/upgrade.sh``, which runs before
#: a repo or a daemon exists) and the runtime socket-path fallback. Widening
#: the pattern to any ``/tmp`` path would flag those and say nothing true.
_TMP_REPORT_DESTINATION = re.compile(
    r"debug_info\.py\s+/tmp/[A-Za-z0-9_.-]+|/tmp/[A-Za-z0-9_.-]*(?:bug_report|report)\.md"
)

#: The overstatement: an unqualified claim that the handler refuses anything
#: outside the repository.
_ABSOLUTE_REFUSAL_CLAIM = re.compile(
    r"path outside the repository is\s+\*{0,2}refused\*{0,2}\s+by\s+`?project_containment`?",
    re.IGNORECASE,
)


class TestScratchGuidancePointsInsideTheRepository:
    def test_no_guidance_document_hands_the_reader_a_tmp_destination(self) -> None:
        """``/tmp`` is wiped on container restart and is not the documented home."""
        offenders: list[str] = []
        for doc in _GUIDANCE_DOCS:
            if not doc.exists():
                continue
            text = doc.read_text()
            for match in _TMP_REPORT_DESTINATION.finditer(text):
                line_number = text[: match.start()].count("\n") + 1
                offenders.append(f"{doc.relative_to(REPO_ROOT)}:{line_number}: {match.group(0)}")

        assert not offenders, (
            "These documents tell the reader to write to /tmp. Use "
            "untracked/scratch/ — inside the working tree, gitignored, and it "
            "survives a container restart:\n  " + "\n  ".join(offenders)
        )

    def test_bug_reporting_names_the_in_repo_scratch_directory(self) -> None:
        """Removing ``/tmp`` is only half of it — the replacement must be named."""
        text = (REPO_ROOT / "BUG_REPORTING.md").read_text()

        assert "untracked/scratch/" in text, (
            "BUG_REPORTING.md must name untracked/scratch/ as the place to write " "a debug report."
        )


class TestTheContainmentClaimStaysWithinWhatTheHandlerCovers:
    def test_no_document_claims_every_outside_path_is_refused(self) -> None:
        """``project_containment`` does not cover a plain script argument.

        It judges redirects and destination-bearing constructs (``curl -o``,
        ``wget -O``, archive-creating ``tar``, ``mkdir``, ``rsync``/``scp``).
        ``script.py /tmp/out.md`` passes a path as an ordinary argument and is
        allowed, which the field report demonstrated with exit 0.
        """
        offenders: list[str] = []
        for doc in _GUIDANCE_DOCS:
            if not doc.exists():
                continue
            text = doc.read_text()
            # Newlines are normalised so a claim wrapped across lines by the
            # markdown formatter is still matched.
            flattened = " ".join(text.split())
            if _ABSOLUTE_REFUSAL_CLAIM.search(flattened):
                offenders.append(str(doc.relative_to(REPO_ROOT)))

        assert not offenders, (
            "These documents claim project_containment refuses ANY path outside "
            "the repository. It judges redirects and destination-bearing "
            "constructs, not a path passed to a script as a plain argument — "
            f"describe it as a backstop instead: {offenders}"
        )
