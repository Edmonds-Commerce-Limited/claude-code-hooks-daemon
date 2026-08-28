"""Doc corpus: inventory, link graph and quote refs (Plan 00284).

Per-document inventory (outbound plain-markdown links, :mod:`checks.pointer_resolves`
at SWEEP) plus a lightweight quote reference list (source_path, anchor) per
document — the REVERSE half of the ``ssot-quote`` mechanism
(:mod:`checks.quote_drift`, :mod:`checks.quote_source_stale`, DESIGN
§2.4): given a SOURCE file+anchor being edited, :meth:`DocCorpus.quoters_of`
answers "which documents quote this section" without re-scanning the whole
tree. The index deliberately does NOT store quote BODY text — only the
reference — so `quote-drift` verification always re-reads the quoting
file's actual content (EDIT: already in hand; SWEEP: read fresh from disk),
never a possibly-stale cached body.

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

from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.quotes import parse_quote_blocks
from claude_code_hooks_daemon.docs_qa.structured_blocks import (
    BlockLocation,
    extract_structured_block_locations,
)
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

# Bumped whenever DocRecord gains/changes fields that a mtime+size-keyed
# reuse would otherwise silently carry forward empty from an older cache
# (Task 3.1h: 3.1e/3.1f added ``quotes``/``block_hashes`` with no version
# gate, so a warm cache from an older daemon reused stale records with both
# fields empty and every check depending on them reported clean). A missing
# or mismatched ``schema_version`` in the on-disk payload is treated the
# same as a corrupt cache: discard it and rebuild the whole index.
# v2 (Task 3.3 T1): added ``block_locations`` (line spans alongside
# ``block_hashes``) -- same reuse-carries-forward-empty hazard 3.1h fixed.
_CACHE_SCHEMA_VERSION: Final[int] = 2

# Task 3.3 T2: transient agent-worktree checkouts contain full copies of the
# tracked doc tree. Indexing them made sweep counts fluctuate with how many
# agents were live and drowned real findings in duplicate scans of the same
# 9 tracked files (54 of 61 module-doc-budget findings in the first dogfood
# audit run -- AUDIT-dogfood-run-1.md T2). Excluded the same way vendored
# content is excluded elsewhere in this codebase: by rel-path prefix.
_WORKTREE_ROOT_PREFIXES: Final[tuple[str, ...]] = (
    ProjectPath.CLAUDE_WORKTREES_DIR,
    ProjectPath.WORKTREES_DIR,
)

# Task 3.6: a CLIENT project's vendored daemon install (``.claude/hooks-daemon/``)
# contains a full copy of the daemon's own tracked docs. Scanning it reports the
# daemon's own module docs as the client's findings -- a client cannot act on
# vendored files. Empty/absent in self-install mode (see the constant's own
# docstring), so the exclusion is inert in this repo.
_HOOKS_DAEMON_INSTALL_PREFIX: Final[str] = ProjectPath.HOOKS_DAEMON_INSTALL_DIR

_CLAUDE_MD_FILENAME: Final[str] = "CLAUDE.md"

# F3 (Plan 00287): common vendored-dependency/build-output directory names.
# A client's configured `trees.human` (default ``docs/``) can be a
# Docusaurus/site root with its OWN `node_modules/`, `build/`, `.next/` --
# scanning those indexes and dead-link-scans every package README on the
# first corpus build. Shared with checks.module_doc_budget, which does its
# OWN rglob walk (Task 3.3 T2 note) rather than using this corpus, so the
# exclusion set has to be shared, not just the outcome.
COMMON_VENDORED_BUILD_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        ".venv",
        ".next",
        "third_party",
    }
)


def is_module_doc_path(rel_path: str, agent_tree: str) -> bool:
    """True for any ``CLAUDE.md`` that is NOT a canonical root (repo or
    agent-tree). Deliberately WIDER than :func:`is_in_scope`'s tracked-corpus
    scope (``module-doc-budget``'s own contract, RULESET section 2 — a
    module doc like ``src/CLAUDE.md`` or ``.claude/ccy/CLAUDE.md`` sits
    outside every tree ``is_in_scope`` recognises, yet is squarely what the
    budget check exists to police)."""
    parts = rel_path.split("/")
    if parts[-1] != _CLAUDE_MD_FILENAME:
        return False
    if len(parts) == 1:
        return False  # repo-root CLAUDE.md
    agent_tree_norm = agent_tree.strip("/")
    if len(parts) == 2 and parts[0] == agent_tree_norm:
        return False  # {trees.agent}/CLAUDE.md
    return True


def extract_link_targets(text: str) -> list[str]:
    """Every plain markdown link target in ``text``, outside fenced code blocks.

    Backticked prose paths (``\\`src/foo.py\\```) are not markdown link
    syntax and are never matched — no special-casing needed.
    """
    targets: list[str] = []
    for line in lines_outside_fences(text):
        targets.extend(match.group(1) for match in _MD_LINK_RE.finditer(line))
    return targets


def _is_worktree_path(rel_parts: tuple[str, ...]) -> bool:
    """True for anything under a transient agent-worktree root (Task 3.3 T2).

    Both worktree roots are two path segments (``.claude/worktrees`` and
    ``untracked/worktrees``), so this compares the first two ``rel_parts``
    against each configured prefix rather than assuming a fixed depth.
    """
    rel_path = "/".join(rel_parts)
    return any(
        rel_path == prefix or rel_path.startswith(prefix + "/")
        for prefix in _WORKTREE_ROOT_PREFIXES
    )


def is_vendored_daemon_install_path(rel_parts: tuple[str, ...]) -> bool:
    """True for anything under the vendored daemon install dir (Task 3.6).

    Exported for reuse by :mod:`checks.module_doc_budget`, which does its
    OWN rglob walk rather than using this corpus (Task 3.3 T2 note) -- so the
    exclusion primitive has to be shared, not just the outcome.
    """
    rel_path = "/".join(rel_parts)
    return rel_path == _HOOKS_DAEMON_INSTALL_PREFIX or rel_path.startswith(
        _HOOKS_DAEMON_INSTALL_PREFIX + "/"
    )


def _is_excluded(rel_parts: tuple[str, ...], policy: DocumentationPolicy) -> bool:
    """Corpus SCOPE exclusions (DESIGN §2.1): changelog, releases, plan
    archives, (Task 3.3 T2) transient agent-worktree checkouts, (Task 3.6) a
    vendored daemon install, and (F3, Plan 00287) common vendored-dependency
    or build-output directories inside the configured trees."""
    if len(rel_parts) == 1 and rel_parts[0] == _CHANGELOG_FILENAME:
        return True
    if rel_parts and rel_parts[0] == _RELEASES_DIR_NAME:
        return True
    if _is_worktree_path(rel_parts):
        return True
    if is_vendored_daemon_install_path(rel_parts):
        return True
    if any(part in COMMON_VENDORED_BUILD_DIR_NAMES for part in rel_parts[:-1]):
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


def is_lintable_path(
    rel_path: str, path: Path, project_root: Path, policy: DocumentationPolicy
) -> bool:
    """Whether ``path`` is a file the docs QA EDIT stage will lint.

    Single source of truth for the scope union both surfaces that run the
    EDIT stage need to agree on: :class:`handlers.pre_tool_use.docs_qa_edit.
    DocsQaEditHandler` (Plan 00284 Task 3.4) and the ``docs-qa --lint`` CLI.
    Before this helper existed the two independently re-derived the same
    three-way union and drifted -- the CLI's copy omitted the
    :func:`is_module_doc_path` arm, so a registered module doc the EDIT
    handler happily linted was refused by the CLI as "not a documentation
    file" (``.claude/ccy/CLAUDE.md`` was the file that exposed the gap).

    In scope: the doc corpus's own scope (:func:`is_in_scope`), OR a path
    declared in the generated-docs manifest (which may legitimately name a
    path outside the corpus scope -- ``.claude/HOOKS-DAEMON.md`` is exactly
    this case), OR any module-scoped ``CLAUDE.md`` (:func:`is_module_doc_path`,
    deliberately wider than the corpus scope).
    """
    # Deferred: docs_qa.checks/__init__ imports checks.duplicate_block, which
    # imports DocCorpus from this module -- a module-level import here would
    # be circular.
    from claude_code_hooks_daemon.docs_qa.checks.generated_doc_hand_edit import (
        matched_manifest_entry,
    )

    return (
        is_in_scope(path, project_root, policy)
        or matched_manifest_entry(rel_path, policy.qa.generated_docs) is not None
        or is_module_doc_path(rel_path, policy.trees.agent)
    )


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
class QuoteRef:
    """A lightweight reference to one ``ssot-quote`` block's declared source.

    Deliberately carries no body text — see the module docstring for why.
    """

    source_path: str
    anchor: str


@dataclass(frozen=True)
class DocRecord:
    """One indexed document: identity, outbound links, and quote references."""

    rel_path: str
    mtime_ns: int
    size: int
    links: tuple[str, ...]
    quotes: tuple[QuoteRef, ...] = ()
    # Normalised sha256 hashes of this doc's structured blocks (R4 classes:
    # fences, tables, list-runs of 3+ items) at or above the length floor --
    # see docs_qa.structured_blocks. Consumed by checks.duplicate_block.
    block_hashes: tuple[str, ...] = ()
    # Same blocks as ``block_hashes``, same order, each carrying its
    # 1-indexed inclusive line span (Task 3.3 T1) -- lets
    # checks.duplicate_block cite ``path:start-end`` for both sides of a
    # duplicate instead of just a bare filename.
    block_locations: tuple[BlockLocation, ...] = ()


@dataclass(frozen=True)
class DocCorpus:
    """The doc inventory + link graph + quote reference index.

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

    def quoters_of(self, source_path: str, anchor: str) -> tuple[str, ...]:
        """Every indexed document's rel_path that quotes ``source_path#anchor``.

        The REVERSE half of the quote index — used by ``quote-source-stale``
        to name which quoting files need re-checking when a source section
        changes. Linear scan: the corpus is a few hundred documents at most,
        and this is called at most once per edited source file, not per
        keystroke.
        """
        return tuple(
            sorted(
                rel_path
                for rel_path, record in self.documents.items()
                if any(
                    ref.source_path == source_path and ref.anchor == anchor for ref in record.quotes
                )
            )
        )


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
    if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
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
                # A schema-current payload always carries this key once a
                # file has been indexed, but the ``.get`` default keeps a
                # per-record parse permissive rather than schema-rejecting
                # the whole cache over one field -- cross-schema gaps are
                # already ruled out above by the version check.
                quotes=tuple(
                    QuoteRef(source_path=ref["source_path"], anchor=ref["anchor"])
                    for ref in entry.get("quotes", [])
                ),
                block_hashes=tuple(entry.get("block_hashes", [])),
                block_locations=tuple(
                    BlockLocation(
                        block_hash=loc["block_hash"],
                        start_line=int(loc["start_line"]),
                        end_line=int(loc["end_line"]),
                    )
                    for loc in entry.get("block_locations", [])
                ),
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
        "schema_version": _CACHE_SCHEMA_VERSION,
        "documents": {
            rel: {
                "mtime_ns": record.mtime_ns,
                "size": record.size,
                "links": list(record.links),
                "quotes": [
                    {"source_path": ref.source_path, "anchor": ref.anchor} for ref in record.quotes
                ],
                "block_hashes": list(record.block_hashes),
                "block_locations": [
                    {
                        "block_hash": loc.block_hash,
                        "start_line": loc.start_line,
                        "end_line": loc.end_line,
                    }
                    for loc in record.block_locations
                ],
            }
            for rel, record in corpus.documents.items()
        },
    }
    tmp_path = index_path.with_suffix(index_path.suffix + _INDEX_TMP_SUFFIX)
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(index_path)


def refresh_own_record(
    corpus: DocCorpus, project_root: Path, file_path: Path, content: str
) -> DocCorpus:
    """Return ``corpus`` with ``file_path``'s record replaced by one built
    fresh from ``content`` -- the content actually being linted, never
    whatever a possibly-stale on-disk cache last recorded for it.

    ``load_or_cold_corpus`` performs no staleness check at all (that is
    ``build_and_save_corpus``'s job, and it only runs at SessionStart/CLI
    sweep time) -- so every EDIT-stage caller (``docs-qa --lint`` and
    :class:`handlers.pre_tool_use.docs_qa_edit.DocsQaEditHandler`) must call
    this immediately after loading the cache and before constructing the
    check context. Without it, ``checks.duplicate_block``'s cross-document
    index requires TWO *distinct corpus entries* sharing a hash before it
    reports anything (``len(paths) >= 2`` in ``_hash_index``) -- so a block
    the edit just introduced, matching an EXISTING partner, stays invisible
    until a full sweep rebuilds the corpus, because the file's own stale
    record never carried the new hash (Plan 00284 Task 3.5).

    Every OTHER document's record is left exactly as loaded -- partner
    staleness is accepted (that is the sweep's job); only the file actually
    being linted must never lag its own content.
    """
    rel_path = str(file_path.relative_to(project_root))
    block_locations = extract_structured_block_locations(content)
    fresh_record = DocRecord(
        rel_path=rel_path,
        mtime_ns=0,
        size=len(content.encode("utf-8")),
        links=tuple(extract_link_targets(content)),
        quotes=tuple(
            QuoteRef(source_path=block.source_path, anchor=block.anchor)
            for block in parse_quote_blocks(content)
        ),
        block_hashes=tuple(loc.block_hash for loc in block_locations),
        block_locations=block_locations,
    )
    documents = dict(corpus.documents)
    documents[rel_path] = fresh_record
    return DocCorpus(project_root=corpus.project_root, documents=documents, cold=corpus.cold)


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
        block_locations = extract_structured_block_locations(text)
        documents[rel_path] = DocRecord(
            rel_path=rel_path,
            mtime_ns=stat.st_mtime_ns,
            size=stat.st_size,
            links=tuple(extract_link_targets(text)),
            quotes=tuple(
                QuoteRef(source_path=block.source_path, anchor=block.anchor)
                for block in parse_quote_blocks(text)
            ),
            block_hashes=tuple(loc.block_hash for loc in block_locations),
            block_locations=block_locations,
        )

    corpus = DocCorpus(project_root=project_root, documents=documents, cold=False)
    _save_corpus(corpus, index_path)
    return corpus
