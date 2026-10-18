"""Instruction-file footprint measurement (Plan 00532 Phase 3).

Resolves, per the instruction-loading contract
(``contracts/claude-code-instructions/``), which agent instruction files Claude
Code loads at session start and which only on demand, and totals their lines
and bytes. The ``docs-optimise`` skill reads this measurement instead of
re-deriving it, so the number a proposal is judged against is deterministic.

Files that are counted but never proposed for edits (Plan 00532 Q9): the
daemon-injected ``<hooksdaemon>`` block, daemon-deployed artefacts,
``CLAUDE.local.md``, ancestor-directory files and user-scope files.

Not modelled (the contract's ``unmodelled`` list, printed with every report):
``claudeMdExcludes``, ``AGENTS.md`` selection, ``--add-dir`` and subagent
``omitClaudeMd``. A project using them gets an overcount.
"""

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from claude_code_hooks_daemon.docs_qa.instructions_contract import InstructionsContract
from claude_code_hooks_daemon.utils.authored_paths import authored_path
from claude_code_hooks_daemon.utils.path_containment import path_is_relative_to, path_relative_to

#: Fact G4-01: the per-CLAUDE.md-file size target, in lines.
CLAUDE_MD_LINE_TARGET: Final[int] = 200
#: Fact G4-03: a file over this many bytes is skipped by Claude Code.
FILE_SKIP_BYTES: Final[int] = 4 * 1024 * 1024
#: Fact G2-03: imports nest to this many hops from the file that starts them.
MAX_IMPORT_HOPS: Final[int] = 4

Loads = Literal["launch", "on-demand"]

_CLAUDE_MD: Final[str] = "CLAUDE.md"
_LOCAL_MD: Final[str] = "CLAUDE.local.md"
_DOT_CLAUDE: Final[str] = ".claude"
_RULES_DIR: Final[str] = "rules"
_DAEMON_DEPLOYED_FILE: Final[str] = ".claude/HOOKS-DAEMON.md"
_DAEMON_DEPLOYED_DIR: Final[str] = ".claude/hooks-daemon/"
#: Directories never walked for nested CLAUDE.md files (dot-directories are skipped too).
_UNWALKED_DIRS: Final[frozenset[str]] = frozenset({"node_modules", "untracked"})

_FRONTMATTER_RE: Final[re.Pattern[str]] = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_DAEMON_BLOCK_RE: Final[re.Pattern[str]] = re.compile(r"<hooksdaemon>.*?</hooksdaemon>", re.DOTALL)
_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
_CODE_SPAN_RE: Final[re.Pattern[str]] = re.compile(r"`[^`\n]*`")
_IMPORT_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w@])@([^\s`<>()\[\]\"']+)")
_IMPORT_TRAILING: Final[str] = ".,;:!?"


@dataclass(frozen=True)
class FootprintEntry:
    """One instruction file Claude Code loads."""

    path: str
    role: str
    loads: Loads
    lines: int
    size_bytes: int
    proposable: bool
    not_proposable_reason: str
    daemon_block_lines: int
    over_line_target: bool
    skipped: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "path": self.path,
            "role": self.role,
            "loads": self.loads,
            "lines": self.lines,
            "bytes": self.size_bytes,
            "proposable": self.proposable,
            "not_proposable_reason": self.not_proposable_reason,
            "daemon_block_lines": self.daemon_block_lines,
            "over_line_target": self.over_line_target,
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class FootprintTotals:
    """Line and byte totals; skipped files (over the size limit) are not counted."""

    launch_files: int
    launch_lines: int
    launch_bytes: int
    launch_daemon_block_lines: int
    launch_proposable_lines: int
    on_demand_files: int
    on_demand_lines: int
    on_demand_bytes: int

    def to_dict(self) -> dict[str, int]:
        """JSON-ready form."""
        return asdict(self)


@dataclass(frozen=True)
class Footprint:
    """The measured footprint of a project's instruction files."""

    audited_version: str
    installed_version: str | None
    documentation_enabled: bool
    unmodelled: tuple[str, ...]
    unmodelled_descriptions: tuple[str, ...]
    entries: tuple[FootprintEntry, ...]
    totals: FootprintTotals

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "audited_version": self.audited_version,
            "installed_version": self.installed_version,
            "documentation_enabled": self.documentation_enabled,
            "line_target": CLAUDE_MD_LINE_TARGET,
            "unmodelled": list(self.unmodelled),
            "totals": self.totals.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


def _display(path: Path, project_root: Path) -> str:
    if path_is_relative_to(path, project_root):
        return path_relative_to(path, project_root).as_posix()
    return str(path)


def _file_in(directory: Path, relative: str) -> Path | None:
    """The file ``relative`` names under ``directory``, lexically normalised, or None."""
    candidate = authored_path(directory, relative)
    return candidate if candidate.is_file() else None


def _is_scoped_rule(text: str) -> bool:
    """True when the frontmatter holds a non-empty ``paths`` (facts G3-04, G3-05, G3-06)."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return False
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and bool(data.get("paths"))


def _import_targets(text: str, source: Path, home_dir: Path) -> list[Path]:
    """Existing files ``text`` imports with ``@path`` (facts G2-01, G2-02, G2-04)."""
    prose = _CODE_SPAN_RE.sub("", _FENCE_RE.sub("", text))
    targets: list[Path] = []
    for raw in _IMPORT_RE.findall(prose):
        candidate = raw.rstrip(_IMPORT_TRAILING)
        base, relative = (
            (home_dir, candidate[2:])
            if candidate.startswith("~/")
            else (
                source.parent,
                candidate,
            )
        )
        found = _file_in(base, relative)
        if found is not None:
            targets.append(found.resolve())
    return targets


class _Collector:
    """Accumulates entries, one per resolved file."""

    def __init__(self, project_root: Path, home_dir: Path) -> None:
        self.project_root = project_root
        self.home_dir = home_dir
        self.entries: list[FootprintEntry] = []
        self._seen: set[Path] = set()
        #: Launch files whose text is parsed for imports, with their hop depth.
        self.import_sources: list[tuple[Path, str, int]] = []

    def add(
        self,
        path: Path,
        role: str,
        loads: Loads,
        hop: int = 0,
        forced_reason: str = "",
        is_claude_md: bool = False,
    ) -> None:
        """Record ``path`` once; queue its imports when it loads at launch."""
        resolved = path.resolve()
        if resolved in self._seen:
            return
        self._seen.add(resolved)
        display = _display(resolved, self.project_root)
        reason = forced_reason or self._reason_for(display)
        size = resolved.stat().st_size
        skipped = size > FILE_SKIP_BYTES
        text = "" if skipped else resolved.read_text(encoding="utf-8", errors="replace")
        lines = len(text.splitlines())
        block = _DAEMON_BLOCK_RE.search(text)
        self.entries.append(
            FootprintEntry(
                path=display,
                role=role,
                loads=loads,
                lines=lines,
                size_bytes=size,
                proposable=not reason,
                not_proposable_reason=reason,
                daemon_block_lines=block.group(0).count("\n") + 1 if block else 0,
                over_line_target=is_claude_md and lines > CLAUDE_MD_LINE_TARGET,
                skipped=skipped,
            )
        )
        if loads == "launch" and not skipped and hop < MAX_IMPORT_HOPS:
            for target in _import_targets(text, resolved, self.home_dir):
                self.add(target, "import", "launch", hop + 1)

    def _reason_for(self, display: str) -> str:
        if display.startswith("/"):
            return "outside the repository"
        if display == _DAEMON_DEPLOYED_FILE or display.startswith(_DAEMON_DEPLOYED_DIR):
            return "daemon-deployed artefact"
        return ""


def _rule_files(rules_dir: Path) -> list[Path]:
    return sorted(rules_dir.rglob("*.md")) if rules_dir.is_dir() else []


def _nested_claude_mds(project_root: Path) -> list[Path]:
    found: list[Path] = []
    for directory, subdirs, files in os.walk(project_root):
        subdirs[:] = sorted(
            name for name in subdirs if not name.startswith(".") and name not in _UNWALKED_DIRS
        )
        if _CLAUDE_MD in files and Path(directory) != project_root:
            found.append(Path(directory) / _CLAUDE_MD)
    return found


def _totals(entries: list[FootprintEntry]) -> FootprintTotals:
    counted = [entry for entry in entries if not entry.skipped]
    launch = [entry for entry in counted if entry.loads == "launch"]
    on_demand = [entry for entry in counted if entry.loads == "on-demand"]
    return FootprintTotals(
        launch_files=len(launch),
        launch_lines=sum(entry.lines for entry in launch),
        launch_bytes=sum(entry.size_bytes for entry in launch),
        launch_daemon_block_lines=sum(entry.daemon_block_lines for entry in launch),
        launch_proposable_lines=sum(
            entry.lines - entry.daemon_block_lines for entry in launch if entry.proposable
        ),
        on_demand_files=len(on_demand),
        on_demand_lines=sum(entry.lines for entry in on_demand),
        on_demand_bytes=sum(entry.size_bytes for entry in on_demand),
    )


def measure_footprint(
    project_root: Path,
    contract: InstructionsContract,
    installed_version: str | None,
    home_dir: Path,
    documentation_enabled: bool,
) -> Footprint:
    """Measure what loads at session start and what loads on demand.

    Args:
        project_root: The project's working directory.
        contract: The loaded instruction-loading contract.
        installed_version: The installed Claude Code version, or None when unknown.
        home_dir: The user's home directory (user-scope files live under ``.claude/``).
        documentation_enabled: Whether the project opted into the daemon's
            documentation ruleset; carried through so the report states which
            ruleset a proposal falls under (Plan 00532 Q6).

    Returns:
        The footprint, entries ordered launch-first then by path.
    """
    root = project_root.resolve()
    collector = _Collector(root, home_dir.resolve())

    for ancestor in sorted(root.parents, key=lambda p: len(p.parts)):
        for name in (_CLAUDE_MD, _LOCAL_MD):
            found = _file_in(ancestor, name)
            if found is not None:
                collector.add(found, "ancestor", "launch", is_claude_md=True)

    for relative in (_CLAUDE_MD, f"{_DOT_CLAUDE}/{_CLAUDE_MD}"):
        found = _file_in(root, relative)
        if found is not None:
            collector.add(found, "claude-md", "launch", is_claude_md=True)
    local = _file_in(root, _LOCAL_MD)
    if local is not None:
        collector.add(
            local,
            "local",
            "launch",
            forced_reason="personal CLAUDE.local.md, counted but never proposed",
            is_claude_md=True,
        )

    for rule in _rule_files(root / _DOT_CLAUDE / _RULES_DIR):
        scoped = _is_scoped_rule(rule.read_text(encoding="utf-8", errors="replace"))
        collector.add(
            rule, "scoped-rule" if scoped else "rule", "on-demand" if scoped else "launch"
        )

    user_reason = "user-scope file outside the repository"
    user_claude = _file_in(home_dir, f"{_DOT_CLAUDE}/{_CLAUDE_MD}")
    if user_claude is not None:
        collector.add(user_claude, "user-claude-md", "launch", forced_reason=user_reason)
    for rule in _rule_files(home_dir / _DOT_CLAUDE / _RULES_DIR):
        collector.add(rule, "user-rule", "launch", forced_reason=user_reason)

    for nested in _nested_claude_mds(root):
        collector.add(nested, "nested-claude-md", "on-demand", is_claude_md=True)

    entries = sorted(collector.entries, key=lambda entry: (entry.loads != "launch",))
    return Footprint(
        audited_version=contract.meta.last_audited_claude_code_version,
        installed_version=installed_version,
        documentation_enabled=documentation_enabled,
        unmodelled=tuple(item.id for item in contract.unmodelled),
        unmodelled_descriptions=tuple(item.description for item in contract.unmodelled),
        entries=tuple(entries),
        totals=_totals(entries),
    )


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def _version_line(footprint: Footprint) -> str:
    audited = footprint.audited_version
    installed = footprint.installed_version
    if installed is None:
        return f"Claude Code: installed version unknown; loading rules audited at v{audited}"
    line = f"Claude Code: installed v{installed}; loading rules audited at v{audited}"
    if _version_tuple(installed) > _version_tuple(audited):
        line += " (installed is newer: the contract is due a re-audit, counts may drift)"
    return line


def _entry_line(entry: FootprintEntry) -> str:
    notes: list[str] = []
    if entry.over_line_target:
        notes.append(f"over the {CLAUDE_MD_LINE_TARGET}-line target")
    if entry.skipped:
        notes.append("over 4 MiB, skipped by Claude Code")
    if entry.daemon_block_lines:
        notes.append(f"{entry.daemon_block_lines} lines are the daemon-owned block")
    if not entry.proposable:
        notes.append(f"never proposed: {entry.not_proposable_reason}")
    suffix = f"  [{'; '.join(notes)}]" if notes else ""
    return f"  {entry.path}  ({entry.role}, {entry.lines} lines, {entry.size_bytes} bytes){suffix}"


def format_footprint(footprint: Footprint) -> str:
    """Render ``footprint`` as the plain-text report."""
    totals = footprint.totals
    ruleset = (
        "daemon documentation ruleset"
        if footprint.documentation_enabled
        else ("Claude Code's own guidance")
    )
    lines = [
        _version_line(footprint),
        f"Governing ruleset for proposals: {ruleset}",
        "",
        f"Loaded at session start: {totals.launch_files} files, {totals.launch_lines} lines, "
        f"{totals.launch_bytes} bytes "
        f"({totals.launch_daemon_block_lines} lines are the daemon-owned block, "
        f"{totals.launch_proposable_lines} lines are proposable)",
    ]
    lines += [_entry_line(entry) for entry in footprint.entries if entry.loads == "launch"]
    lines += [
        "",
        f"Loaded on demand: {totals.on_demand_files} files, {totals.on_demand_lines} lines, "
        f"{totals.on_demand_bytes} bytes",
    ]
    lines += [_entry_line(entry) for entry in footprint.entries if entry.loads == "on-demand"]
    lines += ["", "Not modelled (the counts above may be high):"]
    lines += [
        f"  {name}: {text}"
        for name, text in zip(footprint.unmodelled, footprint.unmodelled_descriptions, strict=True)
    ]
    return "\n".join(lines)
