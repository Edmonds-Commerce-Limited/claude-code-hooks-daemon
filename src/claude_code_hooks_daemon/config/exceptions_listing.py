"""The record listing: what exempts something from a guard, and why (Plan 00484 G12).

``hooks-daemon exceptions`` reads four kinds of source and reports each entry
with the reason it carries, or ``None`` where the source has nowhere to write
one. The listing answers "what is exempt, and does anyone say why?" in one
place instead of five.

- **Config exceptions**: ``exclude_paths`` / ``extra_whitelist`` entries, whose
  reasoned form (``{pattern, reason}``) is reduced to a bare pattern at config
  load. So this reads the RAW file, not the loaded ``Config``.
- **Switched-off and downgraded handlers**: ``enabled: false`` and
  ``options.mode: warn``. Neither has a reason field today.
- **In-file hatches**: ``MUST_EXCEED_COMMENT_SIZE_BECAUSE`` and
  ``MUST_EXCEED_PLAN_SIZE_BECAUSE`` declarations in tracked files.
- **QA exception files**: the fixed set of files the QA scripts read their
  exceptions from, named here because no other record names them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.exception_entries import EXCEPTION_OPTION_KEYS
from claude_code_hooks_daemon.config.models import handler_options

SOURCE_CONFIG_EXCEPTION: Final[str] = "config-exception"
SOURCE_DISABLED_HANDLER: Final[str] = "disabled-handler"
SOURCE_DOWNGRADED_HANDLER: Final[str] = "downgraded-handler"
SOURCE_IN_FILE_HATCH: Final[str] = "in-file-hatch"
SOURCE_QA_EXCEPTION_FILE: Final[str] = "qa-exception-file"

#: The files the QA scripts read their exceptions from, relative to the project
#: root. Each is a hard-coded path in one script, so nothing else lists them.
#: Pinned by a test that every one exists in this repository.
QA_EXCEPTION_FILES: Final[tuple[str, ...]] = (
    "scripts/qa/error_hiding_exclusions.json",
    "scripts/qa/contract_allowlist.py",
    "contracts/claude-code-hooks/ALLOWLIST.yaml",
    "contracts/claude-code-hooks/INPUT-ALLOWLIST.yaml",
    "scripts/qa/fail-open-boundaries.yaml",
    "scripts/qa/security-downgrade-inventory.yaml",
)

_HATCH_RE: Final[re.Pattern[str]] = re.compile(
    r"(?P<token>MUST_EXCEED_(?:COMMENT|PLAN)_SIZE_BECAUSE)\s*[:=]\s*(?P<reason>.*)"
)
#: What may precede the token on a declaring line: indentation and a comment
#: opener only. A token after a quote, a backtick or prose is a MENTION of the
#: hatch (a docstring, a test fixture, a document explaining it), not a use.
_COMMENT_LEAD_RE: Final[re.Pattern[str]] = re.compile(r"\s*(?:#+|//+|/\*+|\*+|<!--|--)?\s*")
_COMMENT_CLOSERS: Final[tuple[str, ...]] = ("-->", "*/")
_MODE_WARN: Final[str] = "warn"

#: A tracked file larger than this is not scanned for hatches: a hatch lives in
#: source or a document, and the cap keeps one vendored blob from dominating.
_MAX_SCAN_BYTES: Final[int] = 1_048_576


@dataclass(frozen=True)
class ExceptionRecord:
    """One exception: its kind, where it is written, what it exempts, and why."""

    source: str
    location: str
    value: str
    reason: str | None

    def as_dict(self) -> dict[str, str | None]:
        """The record as a JSON-ready mapping."""
        return asdict(self)


def _entry_parts(entry: object) -> tuple[str, str | None]:
    """``(pattern, reason)`` of one raw entry, whichever form it is written in."""
    if isinstance(entry, Mapping):
        reason = entry.get("reason")
        return str(entry.get("pattern", "")), reason if isinstance(reason, str) else None
    return str(entry), None


def _exception_records(location: str, value: object) -> list[ExceptionRecord]:
    if not isinstance(value, list):
        return []
    records = []
    for entry in value:
        pattern, reason = _entry_parts(entry)
        records.append(ExceptionRecord(SOURCE_CONFIG_EXCEPTION, location, pattern, reason))
    return records


def collect_config_exceptions(config: Mapping[str, Any]) -> list[ExceptionRecord]:
    """The exceptions written in a raw config mapping, in file order."""
    records: list[ExceptionRecord] = []
    daemon = config.get("daemon")
    if isinstance(daemon, Mapping):
        records.extend(_exception_records("daemon.exclude_paths", daemon.get("exclude_paths")))
    handlers = config.get("handlers")
    for event, block in handlers.items() if isinstance(handlers, Mapping) else ():
        for name, spec in block.items() if isinstance(block, Mapping) else ():
            if not isinstance(spec, Mapping):
                continue
            where = f"handlers.{event}.{name}"
            if spec.get("enabled") is False:
                records.append(ExceptionRecord(SOURCE_DISABLED_HANDLER, where, "enabled: false", None))
            options = handler_options(spec)
            if options.get("mode") == _MODE_WARN:
                records.append(
                    ExceptionRecord(SOURCE_DOWNGRADED_HANDLER, where, f"mode: {_MODE_WARN}", None)
                )
            for key in EXCEPTION_OPTION_KEYS:
                records.extend(_exception_records(f"{where}.options.{key}", options.get(key)))
    return records


def _hatch_reason(raw: str) -> str:
    """A hatch's reason with any trailing comment closer removed."""
    reason = raw.strip()
    for closer in _COMMENT_CLOSERS:
        if reason.endswith(closer):
            reason = reason[: -len(closer)].rstrip()
    return reason


def collect_in_file_hatches(root: Path, files: Iterable[Path]) -> list[ExceptionRecord]:
    """The ``MUST_EXCEED_*_BECAUSE`` declarations in ``files`` (relative to ``root``).

    A line whose reason is the ``<reason>`` placeholder is documentation naming
    the hatch, not a declaration. A file that is not UTF-8 text is skipped.
    """
    records: list[ExceptionRecord] = []
    for relative in files:
        path = root / relative
        if not path.is_file() or path.stat().st_size > _MAX_SCAN_BYTES:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(lines, start=1):
            match = _HATCH_RE.search(line)
            if match is None or not _COMMENT_LEAD_RE.fullmatch(line[: match.start()]):
                continue
            reason = _hatch_reason(match.group("reason"))
            if reason.startswith("<"):
                continue
            records.append(
                ExceptionRecord(
                    SOURCE_IN_FILE_HATCH, f"{relative}:{number}", match.group("token"), reason
                )
            )
    return records


def collect_qa_exception_files(root: Path) -> list[ExceptionRecord]:
    """The declared QA exception files that exist under ``root``."""
    return [
        ExceptionRecord(SOURCE_QA_EXCEPTION_FILE, path, "read by the QA scripts", None)
        for path in QA_EXCEPTION_FILES
        if (root / path).is_file()
    ]
