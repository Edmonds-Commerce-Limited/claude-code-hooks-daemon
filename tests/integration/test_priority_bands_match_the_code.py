"""The documented priority bands must agree with the constants they cite.

Plan 00435, from ledger 00422 N5 rows (a) and (d).
``CLAUDE/HANDLER_DEVELOPMENT.md`` carries the single documented statement of
the priority bands and names ``PriorityRange`` as the source they derive from.
Nothing compared the two, and by the time this was written they disagreed in
two places at once — while ``quote_drift`` kept both quoting copies perfectly
in step with the wrong table.

The 0-9 row is the one that costs something. ``auto_continue_stop`` is
terminal, matches nearly every ordinary stop and is overridden to priority 10
here, so the Stop-family handlers below it are below it deliberately; an author
who reads "no built-in handlers ship here" and places a Stop handler at 10+
gets one that never fires.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.priority import Priority, PriorityRange

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SSOT_DOC: Final[Path] = _REPO_ROOT / "CLAUDE" / "HANDLER_DEVELOPMENT.md"

#: A band row: `| 0-9  | Test | ... |` or `| 100+ | Logging | ... |`.
_BAND_ROW: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*(?P<low>\d+)(?:-(?P<high>\d+)|(?P<open>\+))\s*\|\s*(?P<label>[^|]+?)\s*\|"
)

#: The band boundaries the code declares, keyed by the documented label.
_DECLARED_BANDS: Final[dict[str, tuple[int, int]]] = {
    "Test": (PriorityRange.TEST_MIN, PriorityRange.TEST_MAX),
    "Safety": (PriorityRange.SAFETY_MIN, PriorityRange.SAFETY_MAX),
    "Code Quality": (PriorityRange.QUALITY_MIN, PriorityRange.QUALITY_MAX),
    "Workflow": (PriorityRange.WORKFLOW_MIN, PriorityRange.WORKFLOW_MAX),
    "Advisory": (PriorityRange.ADVISORY_MIN, PriorityRange.ADVISORY_MAX),
    "Logging": (PriorityRange.LOGGING_MIN, PriorityRange.LOGGING_MAX),
}

#: Status-line SEGMENT order shares the `Priority` class but is not a handler
#: priority — segments render left to right, they do not run in a hook chain.
#: Named individually rather than filtered by a range, because a range would
#: also swallow a real handler that landed on the same number.
_SEGMENT_CONSTANTS: Final[frozenset[str]] = frozenset(
    {
        "MULTITHREAD_INDICATOR",
        "GIT_REPO_NAME",
        "ENVIRONMENT_INDICATOR",
        "ACCOUNT_DISPLAY",
        "HOST_HOSTNAME",
        "MODEL_CONTEXT",
        "DOWNGRADE_INDICATOR",
        "CONTEXT_SIDECAR",
        "SUPERVISOR_INDICATOR",
        "CURRENT_TIME",
        "WORKING_DIRECTORY",
        "STARTUP_CLEANUP",
        "DEFAULT",
    }
)


def _band_rows() -> list[tuple[str, int, int, str]]:
    """Every band row in the SSoT table: (label, low, high, raw line)."""
    rows: list[tuple[str, int, int, str]] = []
    for line in _SSOT_DOC.read_text().splitlines():
        match = _BAND_ROW.match(line)
        if match is None:
            continue
        high_group = match.group("high")
        high = PriorityRange.LOGGING_MAX if high_group is None else int(high_group)
        rows.append((match.group("label"), int(match.group("low")), high, line))
    return rows


def _documented_bands() -> dict[str, tuple[int, int]]:
    return {label: (low, high) for label, low, high, _line in _band_rows()}


def _handler_priorities() -> dict[str, int]:
    """Shipped handler priority constants, excluding status-line segments."""
    return {
        name: value
        for name, value in vars(Priority).items()
        if not name.startswith("_") and isinstance(value, int) and name not in _SEGMENT_CONSTANTS
    }


class TestTheTableMatchesPriorityRange:
    def test_every_documented_band_matches_the_declared_range(self) -> None:
        documented = _documented_bands()
        mismatches = [
            f"{label}: documented {documented[label]}, PriorityRange says {declared}"
            for label, declared in _DECLARED_BANDS.items()
            if label in documented and documented[label] != declared
        ]
        assert not mismatches, (
            "the priority band table disagrees with the constants it names as its "
            f"source: {mismatches}"
        )

    def test_every_declared_band_appears_in_the_table(self) -> None:
        documented = _documented_bands()
        missing = sorted(set(_DECLARED_BANDS) - set(documented))
        assert not missing, f"bands declared in PriorityRange but not documented: {missing}"

    def test_the_parser_found_the_table(self) -> None:
        """Control: a parser matching nothing would pass both tests above."""
        documented = _documented_bands()
        assert len(documented) == len(_DECLARED_BANDS), (
            f"expected {len(_DECLARED_BANDS)} band rows in {_SSOT_DOC.name}, "
            f"parsed {len(documented)}: {sorted(documented)}"
        )


class TestEveryShippedPriorityFallsInADocumentedBand:
    def test_no_handler_priority_falls_outside_every_band(self) -> None:
        spans = tuple(_DECLARED_BANDS.values())
        orphans = sorted(
            (value, name)
            for name, value in _handler_priorities().items()
            if not any(low <= value <= high for low, high in spans)
        )
        assert not orphans, (
            "these shipped handler priorities fall in no documented band — either "
            f"the band table or the constant is wrong: {orphans}"
        )

    def test_the_zero_to_nine_row_names_what_ships_there(self) -> None:
        """The band is not empty, and the row must say so.

        Naming them is the point: they are below the terminal Stop catch-all
        because anything above it is unreachable on an ordinary stop, and an
        author told the band is empty will not go looking for that.
        """
        low, high = _DECLARED_BANDS["Test"]
        shipped = sorted(
            name
            for name, value in _handler_priorities().items()
            if low <= value <= high and name != "TEST_HANDLER"
        )
        assert shipped, "no handler ships in 0-9; this test's premise has changed"

        rows = [line for label, _low, _high, line in _band_rows() if label == "Test"]
        assert len(rows) == 1, f"expected exactly one 0-9 band row, found {len(rows)}"
        row = rows[0].lower()
        missing = [name for name in shipped if name.lower() not in row]
        assert (
            not missing
        ), f"the 0-9 band row does not name what ships there: {missing}. Row: {rows[0]}"

    def test_the_segment_exclusion_is_not_hiding_a_handler(self) -> None:
        """Control: every excluded name must still exist on the class.

        A typo in the exclusion set would silently widen it and could hide a
        real handler from the orphan check above.
        """
        attributes = {name for name in vars(Priority) if not name.startswith("_")}
        unknown = sorted(_SEGMENT_CONSTANTS - attributes)
        assert not unknown, f"excluded names that are not Priority constants: {unknown}"
