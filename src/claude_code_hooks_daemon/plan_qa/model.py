"""PlanDoc — rigid parser for a single ``PLAN.md`` document.

Parsing contracts (Plan 00144, from the 31-sin audit spec):

- ``status``: the FIRST ``**Status**:`` line outside fenced code blocks; the
  value must begin with one of the :class:`PlanStatus` tokens at a word
  boundary. Anything after the token (dates, "superseded by ..." qualifiers)
  is preserved raw; a ``(YYYY-MM-DD)`` qualifier is extracted separately.
  Whether a terminal status REQUIRES a date is check-level policy, not a
  parser concern (this repo's own convention forbids completion dates).
- ``tasks``: counts of ``- [ ]`` / ``- [x]`` checkboxes and the template's
  status icons on list-item lines, plus detection of legacy ad-hoc grammars
  (``[✓]``, ``[⏳]``, ``[~]``) so sin E6 is reportable.
- ``done_marker_count``: prose completion claims ("ALL DONE",
  "all tasks complete") that power the header-body-coherence check.

All matching ignores fenced code blocks: plan documents routinely embed
template excerpts and shell snippets that would otherwise poison every count.
The parser MUST tolerate mdformat-gfm output because the daemon's
markdown_table_formatter rewrites every written markdown file.
"""

import calendar
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.plan_qa.types import DEFAULT_JOURNAL_DIR_NAME


class PlanStatus(StrEnum):
    """Allowed ``**Status**:`` tokens for a plan document."""

    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETE = "Complete"
    BLOCKED = "Blocked"
    CANCELLED = "Cancelled"
    SUPERSEDED = "Superseded"
    DORMANT = "Dormant"


# Statuses that end a plan's life: the folder must move to the archive dir.
TERMINAL_STATUSES: Final[frozenset[PlanStatus]] = frozenset(
    {PlanStatus.COMPLETE, PlanStatus.CANCELLED, PlanStatus.SUPERSEDED}
)

# Longest-first so e.g. "Not Started" can never be shadowed by a shorter token.
_STATUS_TOKENS_LONGEST_FIRST: Final[tuple[PlanStatus, ...]] = tuple(
    sorted(PlanStatus, key=lambda status: len(status.value), reverse=True)
)

_TITLE_RE: Final[re.Pattern[str]] = re.compile(r"^#\s+Plan\s+(\d{1,5})\s*:\s*(.+?)\s*$")
_STATUS_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^\*\*Status\*\*\s*:\s*(.+?)\s*$")
_CREATED_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^\*\*Created\*\*\s*:\s*(.+?)\s*$")
_OWNER_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^\*\*Owner\*\*\s*:\s*(.+?)\s*$")
_PRIORITY_LINE_RE: Final[re.Pattern[str]] = re.compile(r"^\*\*Priority\*\*\s*:\s*(.+?)\s*$")
_STATUS_DATE_RE: Final[re.Pattern[str]] = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")

_LIST_ITEM_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*+]\s+(.*)$")
_CHECKBOX_RE: Final[re.Pattern[str]] = re.compile(r"^\s*[-*+]\s+\[([ xX])\]")
_CHECKBOX_CHECKED_VALUES: Final[frozenset[str]] = frozenset({"x", "X"})

_ICON_TODO: Final[str] = "⬜"
_ICON_IN_PROGRESS: Final[str] = "🔄"
_ICON_DONE: Final[str] = "✅"
_ICON_BLOCKED: Final[str] = "🚫"
_ICON_CANCELLED: Final[str] = "❌"

# Ad-hoc progress grammars seen in the wild (sin E6): unparseable by
# icon/checkbox tooling, so their presence is surfaced as a finding.
_LEGACY_MARKERS: Final[tuple[str, ...]] = ("[✓]", "[⏳]", "[~]", r"\[ \]")

# Inline-code spans, stripped before the legacy-marker test so a plan that
# QUOTES a marker is not read as one that uses it.
_INLINE_CODE_RE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]*`")

_DONE_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\ball\s+done\b|\ball\s+tasks?\s+complete\b",
    re.IGNORECASE,
)

_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class TaskCounts:
    """Checkbox / status-icon / legacy-grammar counts for one plan document."""

    unchecked: int
    checked: int
    icons_todo: int
    icons_in_progress: int
    icons_done: int
    icons_blocked: int
    icons_cancelled: int
    legacy_marker_lines: int

    @property
    def total_checkboxes(self) -> int:
        """Total template-grammar checkboxes (checked + unchecked)."""
        return self.unchecked + self.checked

    @property
    def all_checked(self) -> bool:
        """True when the document has checkboxes and every one is ticked."""
        return self.total_checkboxes > 0 and self.unchecked == 0


@dataclass(frozen=True)
class PlanDoc:
    """Parsed view of a single PLAN.md document."""

    plan_number: int | None
    title: str | None
    status_line_present: bool
    status: PlanStatus | None
    status_raw: str | None
    status_date: str | None
    created: str | None
    owner: str | None
    priority: str | None
    tasks: TaskCounts
    done_marker_count: int

    @property
    def is_terminal(self) -> bool:
        """True when the parsed status is a terminal (archive-worthy) state."""
        return self.status is not None and self.status in TERMINAL_STATUSES

    @classmethod
    def parse(cls, text: str) -> "PlanDoc":
        """Parse ``text`` (full PLAN.md content) into a :class:`PlanDoc`."""
        lines = lines_outside_fences(text)

        plan_number, title = _parse_title(lines)
        status_raw = _first_field_value(lines, _STATUS_LINE_RE)
        status, status_date = _parse_status_value(status_raw)

        return cls(
            plan_number=plan_number,
            title=title,
            status_line_present=status_raw is not None,
            status=status,
            status_raw=status_raw,
            status_date=status_date,
            created=_first_field_value(lines, _CREATED_LINE_RE),
            owner=_first_field_value(lines, _OWNER_LINE_RE),
            priority=_first_field_value(lines, _PRIORITY_LINE_RE),
            tasks=_count_tasks(lines),
            done_marker_count=_count_done_markers(lines),
        )


def lines_outside_fences(text: str) -> list[str]:
    """Split ``text`` into lines, dropping everything inside fenced blocks.

    Fence delimiter lines themselves are also dropped. Unclosed fences swallow
    the remainder of the document — the safe failure mode for counting.
    """
    result: list[str] = []
    in_fence = False
    fence_marker: str | None = None
    for line in text.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            continue
        if not in_fence:
            result.append(line)
    return result


def _parse_title(lines: list[str]) -> tuple[int | None, str | None]:
    """Extract (plan_number, title) from the first ``# Plan NNNNN:`` heading."""
    for line in lines:
        match = _TITLE_RE.match(line)
        if match:
            return int(match.group(1)), match.group(2)
    return None, None


def _first_field_value(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    """Value of the FIRST line matching a ``**Field**: value`` pattern."""
    for line in lines:
        match = pattern.match(line)
        if match:
            return match.group(1)
    return None


def _parse_status_value(status_raw: str | None) -> tuple[PlanStatus | None, str | None]:
    """Resolve the raw status value to (token, extracted-date).

    The value must BEGIN with an allowed token at a word boundary —
    ``Complete (2026-06-30)`` parses, ``Completed`` (trailing letter) and
    ``Doneish`` do not. The date is any ``(YYYY-MM-DD)`` qualifier after
    the token.
    """
    if status_raw is None:
        return None, None
    for token in _STATUS_TOKENS_LONGEST_FIRST:
        value = token.value
        if status_raw == value:
            return token, None
        if status_raw.startswith(value) and not status_raw[len(value)].isalnum():
            date_match = _STATUS_DATE_RE.search(status_raw[len(value) :])
            return token, date_match.group(1) if date_match else None
    return None, None


def _count_tasks(lines: list[str]) -> TaskCounts:
    """Count checkboxes, template status icons, and legacy-grammar lines.

    Icons and legacy markers are only counted on list-item lines so prose,
    tables, and headings cannot poison the counts.
    """
    unchecked = 0
    checked = 0
    icons = {
        _ICON_TODO: 0,
        _ICON_IN_PROGRESS: 0,
        _ICON_DONE: 0,
        _ICON_BLOCKED: 0,
        _ICON_CANCELLED: 0,
    }
    legacy_marker_lines = 0

    for line in lines:
        list_match = _LIST_ITEM_RE.match(line)
        if not list_match:
            continue
        item_text = list_match.group(1)

        checkbox_match = _CHECKBOX_RE.match(line)
        if checkbox_match:
            if checkbox_match.group(1) in _CHECKBOX_CHECKED_VALUES:
                checked += 1
            else:
                unchecked += 1

        for icon in icons:
            if icon in item_text:
                icons[icon] += 1

        # A marker inside inline code is being NAMED, not used — a plan that
        # documents the legacy grammar, or records having removed it, quotes
        # the markers. A marker actually in use never appears in backticks.
        prose = _INLINE_CODE_RE.sub("", item_text)
        if any(marker in prose for marker in _LEGACY_MARKERS):
            legacy_marker_lines += 1

    return TaskCounts(
        unchecked=unchecked,
        checked=checked,
        icons_todo=icons[_ICON_TODO],
        icons_in_progress=icons[_ICON_IN_PROGRESS],
        icons_done=icons[_ICON_DONE],
        icons_blocked=icons[_ICON_BLOCKED],
        icons_cancelled=icons[_ICON_CANCELLED],
        legacy_marker_lines=legacy_marker_lines,
    )


def _count_done_markers(lines: list[str]) -> int:
    """Count prose completion claims ("ALL DONE", "all tasks complete")."""
    return sum(len(_DONE_MARKER_RE.findall(line)) for line in lines)


class PlanLocation(StrEnum):
    """Where a plan folder physically sits relative to the plan root."""

    ROOT = "root"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    # Inside some other organisational subdirectory — a structural finding:
    # plans belong in the root (active) or a configured archive dir.
    OTHER = "other"


DEFAULT_COMPLETED_DIR: Final[str] = "Completed"
DEFAULT_CANCELLED_DIR: Final[str] = "Cancelled"

PLAN_DOC_FILENAME: Final[str] = "PLAN.md"
README_FILENAME: Final[str] = "README.md"

# Same folder grammar as handlers/utils/plan_numbering.py: 1-5 digits, then a
# hyphen and a LETTER (so date-named dirs like 2026-01-12 are never plans).
_PLAN_FOLDER_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,5})-[a-zA-Z]")

# Journal day-file grammar (Plan 00163): ``NNNNN-Journal-YY-MM-DD.md``. The
# two-digit year is deliberate (Decision 1) — the journal filename parser owns
# its own pattern rather than reusing plan_qa's 4-digit date regex.
_JOURNAL_DAYFILE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{1,5})-Journal-(\d{2})-(\d{2})-(\d{2})\.md$"
)
_JOURNAL_YEAR_BASE: Final[int] = 2000

_HIDDEN_PREFIX: Final[str] = "."

# Non-plan files that legitimately live at the plan root; anything else is a
# stray (sin-adjacent: orphan notes files invisible to the index).
_EXPECTED_ROOT_FILES: Final[frozenset[str]] = frozenset(
    {
        README_FILENAME,
        "CLAUDE.md",
        "mkplan.bash",
        "_TEMPLATE_.md",
        "_JOURNAL_TEMPLATE_.md",  # Plan 00163: per-plan journalling scaffold template.
        # Plan 00213 Phase 2: sourced planlib operator-script safety library,
        # daemon-deployed like mkplan.bash when plan_workflow.scripts.enabled
        # is true. Built in (not left to `extra_root_files`) because it is a
        # DAEMON-owned asset -- a client should not have to hand-configure an
        # allowlist entry for a file the daemon itself decided to ship.
        "_planlib.inc.bash",
    }
)


_MONTHS_IN_YEAR: Final[int] = 12


def _is_valid_calendar_date(year: int, month: int, day: int) -> bool:
    """True when (year, month, day) is a real calendar date — never raises.

    ``calendar.monthrange`` is leap-aware but raises on an out-of-range month,
    so the month is range-checked first (precondition, not catch-and-swallow).
    """
    if not 1 <= month <= _MONTHS_IN_YEAR:
        return False
    _, days_in_month = calendar.monthrange(year, month)
    return 1 <= day <= days_in_month


@dataclass(frozen=True)
class JournalDayfileName:
    """The parts parsed from a ``NNNNN-Journal-YY-MM-DD.md`` name (Plan 00163)."""

    number: int
    year: int
    month: int
    day: int

    @property
    def is_valid_date(self) -> bool:
        """Whether the YY-MM-DD components form a real calendar date."""
        return _is_valid_calendar_date(self.year, self.month, self.day)

    @property
    def date(self) -> date:
        """The calendar date — only meaningful when :attr:`is_valid_date`."""
        return date(self.year, self.month, self.day)


def parse_journal_dayfile_name(filename: str) -> JournalDayfileName | None:
    """Parse ``NNNNN-Journal-YY-MM-DD.md`` into its parts, or ``None``.

    Filename parse only (Plan 00163) — journals may be large and are never
    read for the model. ``None`` means the name does not match the day-file
    grammar at all (a classification, not an error); calendar validity of the
    parsed components is a separate question answered by
    :attr:`JournalDayfileName.is_valid_date`.
    """
    match = _JOURNAL_DAYFILE_RE.match(filename)
    if match is None:
        return None
    number, yy, mm, dd = match.groups()
    return JournalDayfileName(
        number=int(number),
        year=_JOURNAL_YEAR_BASE + int(yy),
        month=int(mm),
        day=int(dd),
    )


def _scan_journal(plan_folder: Path, journal_dir_name: str) -> tuple[bool, date | None]:
    """Return ``(has_journal, latest_journal_date)`` for one plan folder.

    ``has_journal`` is True when the journal directory exists at all;
    ``latest_journal_date`` is the newest well-formed day-file date, or
    ``None`` when the directory is empty or holds only malformed names.
    """
    journal_dir = plan_folder / journal_dir_name
    if not journal_dir.is_dir():
        return False, None
    dates = [
        parsed.date
        for entry in journal_dir.iterdir()
        if (parsed := parse_journal_dayfile_name(entry.name)) is not None and parsed.is_valid_date
    ]
    return True, (max(dates) if dates else None)


@dataclass(frozen=True)
class PlanFolder:
    """One ``NNNNN-name/`` plan folder discovered by :meth:`PlanTree.scan`."""

    path: Path
    name: str
    number: int
    location: PlanLocation
    has_plan_md: bool
    doc: PlanDoc | None
    has_journal: bool = False
    latest_journal_date: date | None = None


@dataclass(frozen=True)
class PlanTree:
    """Structural scan of a plan directory (root + archive subdirectories)."""

    root: Path
    completed_dir_name: str
    cancelled_dir_name: str | None
    folders: tuple[PlanFolder, ...]
    stray_files: tuple[Path, ...]
    has_readme: bool
    has_completed_dir: bool
    has_cancelled_dir: bool

    @classmethod
    def scan(
        cls,
        root: Path,
        completed_dir: str = DEFAULT_COMPLETED_DIR,
        cancelled_dir: str | None = DEFAULT_CANCELLED_DIR,
        extra_root_files: Sequence[str] = (),
        journal_dir_name: str = DEFAULT_JOURNAL_DIR_NAME,
    ) -> "PlanTree":
        """Scan ``root`` for plan folders, archive dirs, and stray files.

        ``extra_root_files`` (Plan 00153) is an ADDITIVE allowlist layered on top
        of the built-in :data:`_EXPECTED_ROOT_FILES`: a client can permit a
        legitimately-placed non-plan file of their OWN (a bespoke sourced
        helper script, say) at the plan root so it is not reported as stray.
        Default empty = today's behaviour. ``_planlib.inc.bash`` -- the
        motivating example for this option before the daemon shipped it -- is
        now itself a member of :data:`_EXPECTED_ROOT_FILES` (Plan 00213 Phase
        2), so a project no longer needs this allowlist for it specifically.

        Raises:
            FileNotFoundError: when ``root`` is not a directory (FAIL FAST —
                a missing plan dir is a structural finding the caller must
                surface, not silently treat as empty).
        """
        if not root.is_dir():
            raise FileNotFoundError(f"Plan directory does not exist: {root}")

        accepted_root_files = _EXPECTED_ROOT_FILES | frozenset(extra_root_files)
        folders: list[PlanFolder] = []
        stray_files: list[Path] = []

        for entry in sorted(root.iterdir()):
            if entry.name.startswith(_HIDDEN_PREFIX):
                continue
            if not entry.is_dir():
                if entry.name not in accepted_root_files:
                    stray_files.append(entry)
                continue
            if _PLAN_FOLDER_RE.match(entry.name):
                folders.append(_load_plan_folder(entry, PlanLocation.ROOT, journal_dir_name))
            elif entry.name == completed_dir:
                _collect_plan_folders(entry, PlanLocation.COMPLETED, folders, journal_dir_name)
            elif cancelled_dir is not None and entry.name == cancelled_dir:
                _collect_plan_folders(entry, PlanLocation.CANCELLED, folders, journal_dir_name)
            else:
                _collect_plan_folders(entry, PlanLocation.OTHER, folders, journal_dir_name)

        return cls(
            root=root,
            completed_dir_name=completed_dir,
            cancelled_dir_name=cancelled_dir,
            folders=tuple(folders),
            stray_files=tuple(stray_files),
            has_readme=(root / README_FILENAME).is_file(),
            has_completed_dir=(root / completed_dir).is_dir(),
            has_cancelled_dir=(cancelled_dir is not None and (root / cancelled_dir).is_dir()),
        )

    def collisions(self) -> dict[int, list[PlanFolder]]:
        """Plan numbers claimed by more than one folder (sin D1)."""
        by_number: dict[int, list[PlanFolder]] = defaultdict(list)
        for folder in self.folders:
            by_number[folder.number].append(folder)
        return {number: claimants for number, claimants in by_number.items() if len(claimants) > 1}


def _load_plan_folder(
    path: Path,
    location: PlanLocation,
    journal_dir_name: str = DEFAULT_JOURNAL_DIR_NAME,
) -> PlanFolder:
    """Build a :class:`PlanFolder`, parsing its PLAN.md when present."""
    match = _PLAN_FOLDER_RE.match(path.name)
    if match is None:  # pragma: no cover - callers pre-filter on the pattern
        raise ValueError(f"Not a plan folder name: {path.name}")
    plan_md = path / PLAN_DOC_FILENAME
    has_plan_md = plan_md.is_file()
    has_journal, latest_journal_date = _scan_journal(path, journal_dir_name)
    return PlanFolder(
        path=path,
        name=path.name,
        number=int(match.group(1)),
        location=location,
        has_plan_md=has_plan_md,
        doc=PlanDoc.parse(plan_md.read_text()) if has_plan_md else None,
        has_journal=has_journal,
        latest_journal_date=latest_journal_date,
    )


def _collect_plan_folders(
    directory: Path,
    location: PlanLocation,
    accumulator: list[PlanFolder],
    journal_dir_name: str = DEFAULT_JOURNAL_DIR_NAME,
) -> None:
    """Recursively collect plan folders under an organisational directory.

    Numbered children are plans (not recursed into); non-numbered, non-hidden
    children are organisational and recursed — mirroring the scan semantics of
    ``handlers/utils/plan_numbering.py`` so QA and numbering agree on what
    counts as a plan.
    """
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith(_HIDDEN_PREFIX):
            continue
        if _PLAN_FOLDER_RE.match(entry.name):
            accumulator.append(_load_plan_folder(entry, location, journal_dir_name))
        else:
            _collect_plan_folders(entry, location, accumulator, journal_dir_name)
