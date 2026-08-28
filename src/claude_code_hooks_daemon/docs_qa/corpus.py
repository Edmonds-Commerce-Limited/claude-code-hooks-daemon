"""Doc corpus: inventory + link graph over the two documentation trees (Plan 00284).

This slice (Task 3.1a) only needs doc inventory and outbound plain-markdown
links — the piece :mod:`checks.pointer_resolves` consumes at the SWEEP
stage. A reverse index (source -> quoters, target -> linkers) is future
work for the ``quote-drift``/``quote-source-stale`` checks (DESIGN
§2.1/§2.4) and is deliberately not built here.

The index is cached at a caller-supplied JSON path (the CLI/handler
resolves ``untracked/docs-qa/index.json`` via the daemon's untracked-dir
convention), invalidated per file by mtime+size (the ``lint_on_edit`` cache
pattern), and written with an atomic tmp-file + ``Path.replace`` (same
directory, so the replace stays on one filesystem). The index
is always built EXPLICITLY (:func:`build_and_save_corpus`, called from
SessionStart/CLI) — never lazily inside a cheap PreToolUse budget, which
instead calls :func:`load_or_cold_corpus` and gets a ``cold=True`` empty
corpus when no cache exists yet (Cold/stale-index rule, DESIGN §2.1).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.plan_qa.model import lines_outside_fences

_MARKDOWN_SUFFIX: Final[str] = ".md"
_CHANGELOG_FILENAME: Final[str] = "CHANGELOG.md"
_RELEASES_DIR_NAME: Final[str] = "RELEASES"
_PLAN_SUBDIR_NAME: Final[str] = "Plan"
_PLAN_COMPLETED_DIR_NAME: Final[str] = "Completed"
_PLAN_CANCELLED_DIR_NAME: Final[str] = "Cancelled"
_CLAUDE_DIR_NAME: Final[str] = ".claude"
_SATELLITE_DIR_NAMES: Final[tuple[str, ...]] = ("rules", "skills", "agents")

# ``[text](target "optional title")`` — target is any run of non-space,
# non-')' characters (an optional quoted title may follow).
_MD_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

_INDEX_TMP_SUFFIX: Final[str] = ".tmp"


def extract_link_targets(text: str) -> list[str]:
    """Every plain markdown link target in ``text``, outside fenced code blocks.

    Backticked prose paths (``\\`src/foo.py\\```) are not markdown link
    syntax and are never matched — no special-casing needed.
    """
    targets: list[str] = []
    for line in lines_outside_fences(text):
        targets.extend(match.group(1) for match in _MD_LINK_RE.finditer(line))
    return targets


def _is_excluded(rel_parts: tuple[str, ...], policy: DocumentationPolicy) -> bool:
    """Corpus SCOPE exclusions (DESIGN §2.1): changelog, releases, plan archives."""
    if len(rel_parts) == 1 and rel_parts[0] == _CHANGELOG_FILENAME:
        return True
    if rel_parts and rel_parts[0] == _RELEASES_DIR_NAME:
        return True
    plan_completed = (policy.trees.agent, _PLAN_SUBDIR_NAME, _PLAN_COMPLETED_DIR_NAME)
    plan_cancelled = (policy.trees.agent, _PLAN_SUBDIR_NAME, _PLAN_CANCELLED_DIR_NAME)
    if rel_parts[: len(plan_completed)] == plan_completed:
        return True
    if rel_parts[: len(plan_cancelled)] == plan_cancelled:
        return True
    return False


def is_in_scope(path: Path, project_root: Path, policy: DocumentationPolicy) -> bool:
    """Whether ``path`` is a documentation file the corpus tracks.

    In scope: a ``.md`` file directly at the project root, anywhere under
    either configured tree (``trees.agent``/``trees.human``), or under
    ``.claude/rules``, ``.claude/skills``, ``.claude/agents`` — minus the
    corpus SCOPE exclusions (changelog, releases, plan archive dirs).
    """
    if path.suffix.lower() != _MARKDOWN_SUFFIX:
        return False
    try:
        rel_parts = path.resolve().relative_to(project_root.resolve()).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    if _is_excluded(rel_parts, policy):
        return False
    if len(rel_parts) == 1:
        return True  # root-level .md
    top = rel_parts[0]
    if top in (policy.trees.agent, policy.trees.human):
        return True
    if top == _CLAUDE_DIR_NAME and len(rel_parts) >= 2 and rel_parts[1] in _SATELLITE_DIR_NAMES:
        return True
    return False


def iter_corpus_paths(project_root: Path, policy: DocumentationPolicy) -> list[Path]:
    """Every in-scope documentation file under ``project_root``, sorted."""
    candidates: set[Path] = set()
    for entry in project_root.glob("*.md"):
        if entry.is_file():
            candidates.add(entry)
    for tree_name in (policy.trees.agent, policy.trees.human):
        tree_dir = project_root / tree_name
        if tree_dir.is_dir():
            candidates.update(p for p in tree_dir.rglob("*.md") if p.is_file())
    for satellite in _SATELLITE_DIR_NAMES:
        satellite_dir = project_root / _CLAUDE_DIR_NAME / satellite
        if satellite_dir.is_dir():
            candidates.update(p for p in satellite_dir.rglob("*.md") if p.is_file())
    return sorted(p for p in candidates if is_in_scope(p, project_root, policy))


@dataclass(frozen=True)
class DocRecord:
    """One indexed document: identity + its outbound plain-markdown links."""

    rel_path: str
    mtime_ns: int
    size: int
    links: tuple[str, ...]


@dataclass(frozen=True)
class DocCorpus:
    """The doc inventory + link graph.

    ``cold`` is True when this corpus was NOT loaded from a valid on-disk
    cache (no cache file yet, or it failed to parse) — see the module
    docstring's cold/stale-index rule. A freshly BUILT corpus
    (:func:`build_and_save_corpus`) is never cold: it just did the real
    work and wrote a fresh cache.
    """

    project_root: Path
    documents: dict[str, DocRecord] = field(default_factory=dict)
    cold: bool = False

    def document_paths(self) -> tuple[str, ...]:
        """Every indexed relative path, sorted."""
        return tuple(sorted(self.documents))


def load_cached_corpus(project_root: Path, index_path: Path) -> DocCorpus | None:
    """Load a persisted corpus index, or ``None`` if absent/corrupt.

    A corrupt or unreadable cache is treated as absent rather than raised —
    the caller (typically :func:`build_and_save_corpus`) falls back to a
    full rebuild, and :func:`load_or_cold_corpus` reports it as cold.
    """
    if not index_path.is_file():
        return None
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_documents = payload.get("documents", {})
    if not isinstance(raw_documents, dict):
        return None
    documents: dict[str, DocRecord] = {}
    try:
        for rel_path, entry in raw_documents.items():
            documents[rel_path] = DocRecord(
                rel_path=rel_path,
                mtime_ns=int(entry["mtime_ns"]),
                size=int(entry["size"]),
                links=tuple(entry["links"]),
            )
    except (KeyError, TypeError, ValueError):
        return None
    return DocCorpus(project_root=project_root, documents=documents, cold=False)


def load_or_cold_corpus(project_root: Path, index_path: Path) -> DocCorpus:
    """Load the cached corpus, or an empty ``cold=True`` corpus if unavailable.

    For cheap consumers (a future EDIT-stage handler) that must never
    trigger a filesystem scan inside a PreToolUse budget.
    """
    cached = load_cached_corpus(project_root, index_path)
    if cached is None:
        return DocCorpus(project_root=project_root, documents={}, cold=True)
    return cached


def _save_corpus(corpus: DocCorpus, index_path: Path) -> None:
    """Atomic-replace write: tmp file in the same directory, then ``os.replace``."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "documents": {
            rel: {"mtime_ns": record.mtime_ns, "size": record.size, "links": list(record.links)}
            for rel, record in corpus.documents.items()
        }
    }
    tmp_path = index_path.with_suffix(index_path.suffix + _INDEX_TMP_SUFFIX)
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(index_path)


def build_and_save_corpus(
    project_root: Path,
    policy: DocumentationPolicy,
    index_path: Path,
) -> DocCorpus:
    """Rebuild the corpus from disk and persist it — the explicit-build entry point.

    Reuses a previous cache entry when a file's mtime+size are unchanged
    (skips re-parsing its links); re-parses anything new or modified;
    drops anything no longer on disk or no longer in scope. Called from
    SessionStart/CLI only, never from a cheap per-edit path.
    """
    previous = load_cached_corpus(project_root, index_path)
    previous_documents = previous.documents if previous is not None else {}

    documents: dict[str, DocRecord] = {}
    for abs_path in iter_corpus_paths(project_root, policy):
        rel_path = str(abs_path.relative_to(project_root))
        stat = abs_path.stat()
        cached = previous_documents.get(rel_path)
        if (
            cached is not None
            and cached.mtime_ns == stat.st_mtime_ns
            and cached.size == stat.st_size
        ):
            documents[rel_path] = cached
            continue
        try:
            text = abs_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            documents[rel_path] = DocRecord(
                rel_path=rel_path, mtime_ns=stat.st_mtime_ns, size=stat.st_size, links=()
            )
            continue
        documents[rel_path] = DocRecord(
            rel_path=rel_path,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            links=tuple(extract_link_targets(text)),
        )

    corpus = DocCorpus(project_root=project_root, documents=documents, cold=False)
    _save_corpus(corpus, index_path)
    return corpus
