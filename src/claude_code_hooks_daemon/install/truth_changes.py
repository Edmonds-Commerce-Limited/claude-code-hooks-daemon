"""Truth-changes manifest loading and reconciliation guidance (Plan 00118).

A *truth-change* records a statement that **was true** about how to work in a
project but became false in a release — replaced by a **new truth**, or retired
entirely. At upgrade time the project LLM is handed the truth-changes for the
version range it crossed and instructed to scan the project's own docs for each
``was`` statement and update it to ``now`` (or remove all reference when ``now``
is empty).

Manifest files live at:
  {project_root}/CLAUDE/UPGRADES/truth-changes/v{X.Y.Z}.yaml

The schema (``was`` / ``now``, plus an optional ``id`` naming the truth) and the
consumption flow are documented in ``CLAUDE/UPGRADES/truth-changes/README.md``.
This module mirrors the proven ``config_migrations`` range-loader pattern, minus
the user-config comparison — truth-changes are guidance, not compared against
anything.

A truth revised in several releases is surfaced ONCE, as its highest-version
entry: entries sharing an ``id`` across manifests form a supersession chain and
only the last link is emitted, with a "revised in" trail naming the releases it
replaces. Un-keyed entries are never collapsed. An agent handed every link of
the chain would assert a claim into the project's docs and then contradict it.

The report is then OFFLOADED (Plan 00329): the full text and one file per
topic chunk go under a report directory, and stdout carries a summary bounded
by ``report_offload.SUMMARY_MAX_BYTES``. A Bash result that exits 1 — which
this command does whenever there is work — is delivered head-and-tail with the
middle dropped past roughly 10,000 characters, so an unbounded report loses
most of its entries before the agent sees them. Chunks are keyed by the
entry's ``topic`` (falling back to its ``id``), are built AFTER collapsing so
no two chunks carry contradictory instructions, and are meant to be delegated
one per subagent that returns what it CHANGED, not what it read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.install.install_stamp import is_branch_install
from claude_code_hooks_daemon.install.report_offload import (
    SUMMARY_MAX_BYTES,
    bound_summary,
    write_offloaded_report,
)
from claude_code_hooks_daemon.install.version_parse import parse_version_tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRUTH_CHANGES_SUBPATH = Path("CLAUDE") / "UPGRADES" / "truth-changes"
_UNRELEASED_DIRNAME = "UNRELEASED"
_MANIFEST_PREFIX = "v"
_MANIFEST_SUFFIX = ".yaml"
_VERSION_SEPARATOR = "."
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")

_FIELD_VERSION = "version"
_FIELD_TRUTH_CHANGES = "truth_changes"
_FIELD_WAS = "was"
_FIELD_NOW = "now"
_FIELD_ID = "id"
_FIELD_TOPIC = "topic"

_FORMAT_TEXT = "text"

UNASSIGNED_CHUNK_KEY = "unassigned"
_REPORT_FILENAME = "REPORT.md"
_CHUNK_FILENAME_PREFIX = "chunk-"
_CHUNK_FILENAME_SUFFIX = ".md"
_LABEL_SEQUENTIAL = "SEQUENTIAL"
_LABEL_CHUNK_HEADER = "Truth-Changes chunk"

_LABEL_NO_CHANGES = "✅ No truth-changes in this range"
_LABEL_HEADER = "Truth-Changes to reconcile"
_LABEL_REVISED_IN = "revised in"
_REMOVAL_INSTRUCTION = "remove all reference to it (no replacement)"
_TRAIL_INSTRUCTION = (
    "An entry marked '{label}' is the CURRENT form of a truth that also changed in "
    "the releases it lists; those earlier forms are deliberately not shown. Reconcile "
    "any earlier form of that statement in the docs to the same NOW."
)
_RULES_INSTRUCTION = (
    "For each entry below, scan the PROJECT'S OWN docs (CLAUDE/, docs/, README*, "
    "AGENTS* — never .claude/hooks-daemon/ internals) for the 'was' statement and "
    "reconcile it. Minimal edits."
)
_SEQUENTIAL_CHUNK_INSTRUCTION = (
    f"This chunk is {_LABEL_SEQUENTIAL}: its entries carry no topic, so the documents "
    "they touch are unknown. Run it alone, after every topic chunk has returned — "
    "never in parallel with them."
)
_RETURN_CONTRACT = (
    "When you finish, return ONLY the files you changed, one line each "
    "(path — what changed), plus one line saying which entries no project doc "
    "asserted — not the entries you read. The coordinator holds paths and "
    "counts, never the report."
)
_DISPATCH_INSTRUCTION = (
    "Each subagent reads its chunk file, reconciles the project's own docs, and "
    "returns ONLY the files it changed (one line each) — not the entries it read."
)
_CHUNKS_HEADING = (
    "Chunks — dispatch each as its own subagent, in parallel; the documents one "
    "chunk touches are disjoint from every other chunk's:"
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TruthChange:
    """A single statement that changed truth in a release.

    Attributes:
        was: Natural-language statement that used to be true. Matched
            semantically against the project's own docs by the LLM.
        now: The replacement truth, or None to mean "remove all reference;
            there is no replacement".
        id: Optional stable slug naming the TRUTH (not the release). Entries
            sharing an id across manifests are one truth revised repeatedly;
            only the highest-version link is surfaced. None means "stands
            alone; never collapsed".
        topic: Optional slug naming the DOCUMENT AREA the truth lives in.
            Entries sharing a topic are chunked together for delegation;
            two truths that could edit the same document must share one.
            Never collapses anything. None means "no area declared".
    """

    was: str
    now: str | None
    id: str | None = None
    topic: str | None = None

    @property
    def is_removal(self) -> bool:
        """Return True when this entry retires a truth with no replacement."""
        # now is str | None; an empty/whitespace-only string also means removal.
        return self.now is None or not self.now.strip()


@dataclass
class TruthChangeManifest:
    """All truth-changes for a single daemon version.

    Attributes:
        version: Version string where these truths changed, e.g. '3.16.0'.
        changes: The list of was/now entries for this version.
    """

    version: str
    changes: list[TruthChange]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TruthChangeManifest:
        """Parse a manifest from a YAML-loaded dictionary.

        Args:
            data: Dictionary loaded from a truth-changes YAML file.

        Returns:
            Parsed TruthChangeManifest.

        Raises:
            KeyError: If a required field (version, or an entry's was) is missing.
            ValueError: If an entry's id or topic is blank, or two entries in
                this one manifest share an id — one release cannot revise a
                truth twice.
        """
        version = str(data[_FIELD_VERSION])
        entries = data.get(_FIELD_TRUTH_CHANGES) or []
        changes: list[TruthChange] = []
        seen_ids: set[str] = set()
        for entry in entries:
            change_id = _parse_entry_slug(entry.get(_FIELD_ID), version, _FIELD_ID)
            if change_id is not None:
                if change_id in seen_ids:
                    raise ValueError(
                        f"truth-changes v{version}: id {change_id!r} appears twice in one "
                        "manifest; a release revises a truth at most once"
                    )
                seen_ids.add(change_id)
            changes.append(
                TruthChange(
                    was=entry[_FIELD_WAS],
                    now=entry.get(_FIELD_NOW),
                    id=change_id,
                    topic=_parse_entry_slug(entry.get(_FIELD_TOPIC), version, _FIELD_TOPIC),
                )
            )
        return cls(version=version, changes=changes)


def _parse_entry_slug(raw: Any, version: str, field: str) -> str | None:
    """Return the entry's ``field`` slug, or None when the entry carries none.

    Raises:
        ValueError: If the key is present but blank — an un-keyed entry must be
            written as an absent key, never as an empty one, so that "stands
            alone" / "no area declared" is always a deliberate, visible choice.
    """
    if raw is None:
        return None
    slug = str(raw).strip()
    if not slug:
        raise ValueError(
            f"truth-changes v{version}: an entry's {field} is blank; omit the key instead"
        )
    return slug


@dataclass
class SurfacedTruthChange:
    """One entry of the collapsed report: the current link of a truth's chain.

    Attributes:
        version: The manifest version the surfaced entry came from.
        change: The entry itself (highest-version link for a keyed truth).
        superseded_versions: Earlier manifest versions, oldest first, whose
            entry for the same id this one replaces. Empty for an un-keyed
            entry or a keyed entry that changed only once in the range.
    """

    version: str
    change: TruthChange
    superseded_versions: list[str]

    @property
    def chunk_key(self) -> str:
        """The chunk this entry belongs to: its topic, else its id, else unassigned."""
        if self.change.topic is not None:
            return self.change.topic
        if self.change.id is not None:
            return self.change.id
        return UNASSIGNED_CHUNK_KEY


@dataclass
class ReportChunk:
    """One delegable unit of reconciliation work.

    Attributes:
        key: The topic (or bare id) every entry in the chunk shares.
        entries: The surfaced entries, in version order.
        sequential: True for the chunk of entries with no topic and no id —
            the documents it touches are unknown, so it must run alone after
            the topic chunks return, never in parallel with them.
    """

    key: str
    entries: list[SurfacedTruthChange]
    sequential: bool


@dataclass
class TruthChangesReportFiles:
    """Where an offloaded report was written.

    Attributes:
        report_path: The full report (the same text the inline form prints).
        chunk_paths: Each chunk with the file holding its subagent brief.
    """

    report_path: Path
    chunk_paths: list[tuple[ReportChunk, Path]]


# ---------------------------------------------------------------------------
# Version utilities + path resolution
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse '3.16.0' or 'v3.16.0' into a sortable tuple (shared parser)."""
    return parse_version_tuple(version)


def _default_truth_changes_dir() -> Path:
    """Return the default truth-changes directory under the project root.

    Resolves relative to this module file: 3 levels up = src/, 4 = project root,
    then CLAUDE/UPGRADES/truth-changes/. Works in both self-install and normal
    installations (same convention as config_migrations).
    """
    # install/ -> claude_code_hooks_daemon/ -> src/ -> project_root
    project_root = Path(__file__).parent.parent.parent.parent
    return project_root / _TRUTH_CHANGES_SUBPATH


def _manifest_files(base_dir: Path, include_unreleased: bool | None) -> list[tuple[str, Path]]:
    """Every ``v{X.Y.Z}.yaml`` in the released directory, plus staging when due.

    Plan 00291 Task 2.3: ``include_unreleased`` left as ``None`` means "ask the
    install stamp" -- a branch install is ahead of the last release, so the
    truths it is ahead on are the staged ones under
    ``<base_dir>/../UNRELEASED/<name>``. A release install never sees them.
    """
    if include_unreleased is None:
        include_unreleased = is_branch_install()
    directories = [base_dir]
    if include_unreleased:
        directories.append(base_dir.parent / _UNRELEASED_DIRNAME / base_dir.name)

    found: list[tuple[str, Path]] = []
    for directory in directories:
        if not directory.exists():
            continue
        for yaml_file in directory.glob(f"{_MANIFEST_PREFIX}*{_MANIFEST_SUFFIX}"):
            version_str = yaml_file.stem[len(_MANIFEST_PREFIX) :]
            if not _VERSION_PATTERN.match(version_str):
                continue
            found.append((version_str, yaml_file))
    return found


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_truth_changes_between(
    from_version: str,
    to_version: str,
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[TruthChangeManifest]:
    """Load all truth-changes manifests in the range (from_version, to_version].

    from_version is excluded, to_version is included — matching the upgrade
    semantics (you already had from_version's truth; you are adopting up to and
    including to_version).

    Args:
        from_version: Version being upgraded from (excluded).
        to_version: Version being upgraded to (included).
        truth_changes_dir: Override the manifest directory (for testing).
        include_unreleased: Also read the UNRELEASED staging directory. ``None``
            (the default) includes it exactly when the running install is a
            branch install.

    Returns:
        Manifests sorted by version, oldest first.

    Raises:
        ValueError: If from_version > to_version, or a version is unparseable.
    """
    from_v = _parse_version(from_version)
    to_v = _parse_version(to_version)

    if from_v > to_v:
        raise ValueError(f"from_version ({from_version}) must be <= to_version ({to_version})")

    if from_v == to_v:
        return []

    base_dir = truth_changes_dir if truth_changes_dir is not None else _default_truth_changes_dir()

    manifests: list[TruthChangeManifest] = []
    for version_str, yaml_file in _manifest_files(base_dir, include_unreleased):
        v = _parse_version(version_str)
        if from_v < v <= to_v:
            with yaml_file.open() as f:
                data: dict[str, Any] = yaml.safe_load(f)
            manifests.append(TruthChangeManifest.from_dict(data))

    manifests.sort(key=lambda m: _parse_version(m.version))
    return manifests


def list_known_truth_change_versions(
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
) -> list[str]:
    """Return sorted versions that have a truth-changes manifest file.

    ``include_unreleased`` follows :func:`load_truth_changes_between`.
    """
    base_dir = truth_changes_dir if truth_changes_dir is not None else _default_truth_changes_dir()

    versions = [version for version, _ in _manifest_files(base_dir, include_unreleased)]
    versions.sort(key=_parse_version)
    return versions


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_truth_changes_for_llm(
    manifests: list[TruthChangeManifest],
    from_version: str,
    to_version: str,
) -> str:
    """Format truth-changes as reconciliation instructions for an LLM.

    Args:
        manifests: Manifests for the range (as returned by load_truth_changes_between).
        from_version: Range start (for the header).
        to_version: Range end (for the header).

    Returns:
        Multi-line string instructing the LLM to reconcile project docs.
    """
    lines: list[str] = [f"{_LABEL_HEADER}: v{from_version} → v{to_version}", ""]

    surfaced = collapse_superseded(manifests)
    if not surfaced:
        lines.append(_LABEL_NO_CHANGES)
        lines.append("")
        lines.append("No project-doc reconciliation is needed for this version range.")
        return "\n".join(lines)

    lines.extend(_rules_lines(surfaced))
    lines.append("")
    lines.extend(_entry_lines(surfaced))

    return "\n".join(lines).rstrip() + "\n"


def _rules_lines(surfaced: list[SurfacedTruthChange]) -> list[str]:
    """The reconciliation rules, plus the trail rule when any entry collapsed."""
    lines = [_RULES_INSTRUCTION]
    if any(item.superseded_versions for item in surfaced):
        lines.append(_TRAIL_INSTRUCTION.format(label=_LABEL_REVISED_IN))
    return lines


def _entry_lines(surfaced: list[SurfacedTruthChange]) -> list[str]:
    """Render each surfaced entry as a WAS/NOW bullet followed by a blank line."""
    lines: list[str] = []
    for item in surfaced:
        lines.append(f"• {_format_origin(item)} WAS: {item.change.was.strip()}")
        if item.change.is_removal:
            lines.append(f"  NOW: {_REMOVAL_INSTRUCTION}")
        else:
            now_text = (item.change.now or "").strip()
            lines.append(f"  NOW: {now_text}")
        lines.append("")
    return lines


def _format_origin(item: SurfacedTruthChange) -> str:
    """Render the bracketed origin of a surfaced entry: version, trail, and id."""
    origin = f"v{item.version}"
    if item.superseded_versions:
        trail = ", ".join(f"v{v}" for v in item.superseded_versions)
        origin = f"{origin}, {_LABEL_REVISED_IN} {trail}"
    origin = f"({origin})"
    if item.change.id is not None:
        origin = f"{origin} [{item.change.id}]"
    return origin


def collapse_superseded(manifests: list[TruthChangeManifest]) -> list[SurfacedTruthChange]:
    """Collapse each keyed truth to its highest-version entry, keeping version order.

    Manifests are walked oldest first (the order ``load_truth_changes_between``
    returns). A later entry with the same id displaces the earlier one and
    inherits its trail, so the surfaced entry sits at the position of the
    release that last revised it. Un-keyed entries pass through untouched.

    Args:
        manifests: Manifests for the range, sorted oldest first.

    Returns:
        One entry per un-keyed change plus one per distinct id.
    """
    ordered = sorted(manifests, key=lambda m: _parse_version(m.version))
    surfaced: list[SurfacedTruthChange] = []
    position_by_id: dict[str, int] = {}
    for manifest in ordered:
        for change in manifest.changes:
            trail: list[str] = []
            if change.id is not None and change.id in position_by_id:
                removed_at = position_by_id.pop(change.id)
                earlier = surfaced.pop(removed_at)
                trail = [*earlier.superseded_versions, earlier.version]
                for key, idx in position_by_id.items():
                    if idx > removed_at:
                        position_by_id[key] = idx - 1
            surfaced.append(
                SurfacedTruthChange(
                    version=manifest.version, change=change, superseded_versions=trail
                )
            )
            if change.id is not None:
                position_by_id[change.id] = len(surfaced) - 1
    return surfaced


# ---------------------------------------------------------------------------
# Topic chunks and file offload (Plan 00329)
# ---------------------------------------------------------------------------


def chunk_by_topic(surfaced: list[SurfacedTruthChange]) -> list[ReportChunk]:
    """Partition the collapsed entries into chunks keyed by topic.

    Must be fed the output of ``collapse_superseded``: chunking an uncollapsed
    report would let two chunks carry contradictory instructions about one
    document, and parallel subagents would then race for it.

    Chunks appear in first-appearance order (which is version order), except
    the unassigned chunk — entries with neither topic nor id — which is always
    last and marked sequential.

    Args:
        surfaced: Collapsed entries, oldest first.

    Returns:
        One chunk per distinct key; every entry lands in exactly one chunk.
    """
    by_key: dict[str, list[SurfacedTruthChange]] = {}
    for item in surfaced:
        by_key.setdefault(item.chunk_key, []).append(item)
    unassigned = by_key.pop(UNASSIGNED_CHUNK_KEY, None)
    chunks = [
        ReportChunk(key=key, entries=items, sequential=False) for key, items in by_key.items()
    ]
    if unassigned:
        chunks.append(ReportChunk(key=UNASSIGNED_CHUNK_KEY, entries=unassigned, sequential=True))
    return chunks


def format_chunk_for_subagent(chunk: ReportChunk, from_version: str, to_version: str) -> str:
    """Render one chunk as a self-contained brief for a subagent.

    Carries the same reconciliation rules as the full report, this chunk's
    entries only, and the return contract — the subagent reports what it
    changed, never the entries it read, or the coordinator re-accumulates
    the bulk the chunking removed.
    """
    lines: list[str] = [
        f"{_LABEL_CHUNK_HEADER} [{chunk.key}]: v{from_version} → v{to_version} "
        f"({len(chunk.entries)} {_plural(len(chunk.entries), 'truth')})",
        "",
    ]
    lines.extend(_rules_lines(chunk.entries))
    if chunk.sequential:
        lines.append(_SEQUENTIAL_CHUNK_INSTRUCTION)
    lines.append("")
    lines.extend(_entry_lines(chunk.entries))
    lines.append(_RETURN_CONTRACT)
    return "\n".join(lines).rstrip() + "\n"


def write_truth_changes_report(
    manifests: list[TruthChangeManifest],
    from_version: str,
    to_version: str,
    report_dir: Path,
) -> TruthChangesReportFiles:
    """Write the full report and one file per chunk under ``report_dir``.

    Files go in ``report_dir/v{from}-to-v{to}/``: ``REPORT.md`` (a chunk index
    followed by the same text the inline form prints) and
    ``chunk-NN-<key>.md``. Chunk files left by an earlier run over the same
    range are removed first, so the directory never lists a chunk that the
    current corpus does not produce.

    Raises:
        OSError: If the directory or a file cannot be written.
    """
    target = report_dir / _range_dirname(from_version, to_version)
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob(f"{_CHUNK_FILENAME_PREFIX}*{_CHUNK_FILENAME_SUFFIX}"):
        stale.unlink()

    chunks = chunk_by_topic(collapse_superseded(manifests))
    chunk_paths: list[tuple[ReportChunk, Path]] = []
    for number, chunk in enumerate(chunks, start=1):
        name = f"{_CHUNK_FILENAME_PREFIX}{number:02d}-{chunk.key}{_CHUNK_FILENAME_SUFFIX}"
        path = write_offloaded_report(
            target, name, format_chunk_for_subagent(chunk, from_version, to_version)
        )
        chunk_paths.append((chunk, path))

    index_lines = [
        f"# Truth-changes report: v{from_version} → v{to_version}",
        "",
        "Chunk files (one subagent brief each; dispatch rules are in the command's summary):",
    ]
    index_lines.extend(_chunk_index_line(chunk, path) for chunk, path in chunk_paths)
    index_lines.append("")
    full_text = (
        "\n".join(index_lines)
        + "\n"
        + format_truth_changes_for_llm(manifests, from_version, to_version)
    )
    report_path = write_offloaded_report(target, _REPORT_FILENAME, full_text)
    return TruthChangesReportFiles(report_path=report_path, chunk_paths=chunk_paths)


def format_bounded_summary(
    manifests: list[TruthChangeManifest],
    from_version: str,
    to_version: str,
    files: TruthChangesReportFiles,
) -> str:
    """The stdout form: counts, the report path, the chunk list — never an entry.

    Bounded by ``SUMMARY_MAX_BYTES``; when the chunk list would breach it, the
    tail of the list is replaced by a line naming how many more chunks
    ``REPORT.md`` indexes.
    """
    surfaced = collapse_superseded(manifests)
    raw_count = sum(len(manifest.changes) for manifest in manifests)
    collapsed = raw_count - len(surfaced)
    head = [
        f"{_LABEL_HEADER}: v{from_version} → v{to_version}",
        "",
        f"{len(surfaced)} {_plural(len(surfaced), 'truth')} to reconcile "
        f"({raw_count} {_plural(raw_count, 'entry', 'entries')} across "
        f"{len(manifests)} {_plural(len(manifests), 'release')}; "
        f"{collapsed} superseded {_plural(collapsed, 'link')} collapsed).",
        f"Full report: {files.report_path}",
        _CHUNKS_HEADING,
    ]
    items = [
        f"  {number}. {_chunk_summary_line(chunk, path)}"
        for number, (chunk, path) in enumerate(files.chunk_paths, start=1)
    ]
    tail = [_DISPATCH_INSTRUCTION]
    return bound_summary(
        head=head,
        items=items,
        tail=tail,
        max_bytes=SUMMARY_MAX_BYTES,
        overflow=lambda n: f"  ... {n} more chunks, all indexed in {files.report_path.name}",
    )


def _chunk_summary_line(chunk: ReportChunk, path: Path) -> str:
    count = f"{len(chunk.entries)} {_plural(len(chunk.entries), 'truth')}"
    if chunk.sequential:
        return (
            f"{chunk.key} — {count} — {_LABEL_SEQUENTIAL}: run alone, after the others "
            f"return — {path}"
        )
    return f"{chunk.key} — {count} — {path}"


def _chunk_index_line(chunk: ReportChunk, path: Path) -> str:
    marker = f" ({_LABEL_SEQUENTIAL})" if chunk.sequential else ""
    return f"- {path.name}{marker} — {len(chunk.entries)} {_plural(len(chunk.entries), 'entry', 'entries')} — {path}"


def _range_dirname(from_version: str, to_version: str) -> str:
    return f"v{from_version.lstrip('v')}-to-v{to_version.lstrip('v')}"


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return singular
    return plural if plural is not None else f"{singular}s"


# ---------------------------------------------------------------------------
# Run-function (CLI entrypoint)
# ---------------------------------------------------------------------------


def run_check_truth_changes(
    from_version: str,
    to_version: str,
    output_format: str = _FORMAT_TEXT,
    truth_changes_dir: Path | None = None,
    include_unreleased: bool | None = None,
    report_dir: Path | None = None,
) -> dict[str, Any]:
    """Load and format truth-changes for a version range.

    Args:
        from_version: Version being upgraded from (excluded from range).
        to_version: Version being upgraded to (included in range).
        output_format: 'text' for LLM-readable instructions, 'json' for machine.
        truth_changes_dir: Override the manifest directory (for testing).
        include_unreleased: Passed through to :func:`load_truth_changes_between`.
        report_dir: When given and there are changes, the full report and the
            chunk files are written under it and the text form is the bounded
            summary. None keeps the whole report inline (``--full``).

    Returns:
        JSON-serialisable dict. Keys: from_version, to_version, has_changes,
        changes (list of {version, was, now, is_removal, id, topic,
        superseded_versions} — superseded links of a keyed truth are collapsed
        here too, so both formats surface the same set), report_path and
        chunks (each {key, path, entry_count, sequential}; None / empty when
        nothing was offloaded), and (text format) text.

    Raises:
        ValueError: If from_version > to_version.
        OSError: If report_dir was given and cannot be written.
    """
    manifests = load_truth_changes_between(
        from_version,
        to_version,
        truth_changes_dir=truth_changes_dir,
        include_unreleased=include_unreleased,
    )

    changes: list[dict[str, Any]] = [
        {
            "version": item.version,
            "was": item.change.was,
            "now": item.change.now,
            "is_removal": item.change.is_removal,
            "id": item.change.id,
            "topic": item.change.topic,
            "superseded_versions": item.superseded_versions,
        }
        for item in collapse_superseded(manifests)
    ]

    result: dict[str, Any] = {
        "from_version": from_version,
        "to_version": to_version,
        "has_changes": bool(changes),
        "changes": changes,
        "report_path": None,
        "chunks": [],
    }

    files: TruthChangesReportFiles | None = None
    if changes and report_dir is not None:
        files = write_truth_changes_report(manifests, from_version, to_version, report_dir)
        result["report_path"] = str(files.report_path)
        result["chunks"] = [
            {
                "key": chunk.key,
                "path": str(path),
                "entry_count": len(chunk.entries),
                "sequential": chunk.sequential,
            }
            for chunk, path in files.chunk_paths
        ]

    if output_format == _FORMAT_TEXT:
        if files is not None:
            result["text"] = format_bounded_summary(manifests, from_version, to_version, files)
        else:
            result["text"] = format_truth_changes_for_llm(manifests, from_version, to_version)

    return result
