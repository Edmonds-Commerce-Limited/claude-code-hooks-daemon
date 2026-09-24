"""Deterministic finder for long comment blocks (Plan 00284 Task 3.1g, Decision 7).

The ``hooks-daemon-docs-qa`` agent explicitly hunts verbose comment blocks
that function as documentation, so they can be cross-checked against the
canonical doc tree for SSoT violations. This module is the deterministic
half of that hunt: it LISTS candidate blocks, using the same comment
extraction engine ``comment_size`` uses to enforce its own line-count limit.

It never judges content and never gates a tool call — a finder, not a
check. The daemon's ``find-comment-blocks`` CLI subcommand and the
``docs-qa`` skill's wrapper script both call this directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.strategies.comments.extractor import extract_comment_spans
from claude_code_hooks_daemon.strategies.comments.registry import CommentStrategyRegistry
from claude_code_hooks_daemon.utils.git_repo import GitRepo, git_visible_paths

logger = logging.getLogger(__name__)

#: Lower than ``comment_size``'s own 40-line block-length limit (which gates a
#: WRITE) — this finder feeds an AGENT's worklist rather than blocking
#: anything, so it deliberately surfaces smaller blocks a documentation
#: auditor would still want to see.
DEFAULT_MIN_BLOCK_LINES: Final[int] = 15


@dataclass(frozen=True)
class CommentBlockFinding:
    """One comment block at or above the configured line-count threshold.

    Attributes:
        path: Absolute path to the source file containing the block.
        start_line: 1-indexed line number where the block starts.
        end_line: 1-indexed line number where the block ends (inclusive).
        line_count: Number of physical lines the block occupies.
        preview: The block's first line, verbatim, for a quick worklist scan.
    """

    path: Path
    start_line: int
    end_line: int
    line_count: int
    preview: str


def _iter_candidate_files(paths: list[Path]) -> list[Path]:
    """Expand directories to files; pass files through unchanged.

    A file the caller names directly is never filtered (naming it is
    explicit consent, the same convention ``daemon.cli``'s
    ``format-markdown`` walk follows) — only the recursive directory
    expansion below is.
    """
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.extend(_iter_dir_files_git_filtered(path))
        elif path.is_file():
            files.append(path)
    return files


def _iter_dir_files_git_filtered(directory: Path) -> list[Path]:
    """Every file under ``directory``, minus what git does not consider part
    of the project (Plan 00468 P3 / Plan 00466 N9's class).

    A gitignored Claude Code plugin install (e.g. ``.claude/ccy/plugins/``)
    is not this project's documentation, so it must not surface in the
    docs-qa agent's worklist as if it were. ``directory`` may sit below the
    enclosing git repository's root (``GitRepo.resolve_for`` walks up to
    find it, mirroring ``daemon.cli``'s ``_enclosing_project_root``); when
    there is no enclosing repository, or git is unavailable,
    :func:`utils.git_repo.git_visible_paths` returns ``None`` and every
    candidate is kept, matching the pre-existing unfiltered behaviour.
    """
    candidates = sorted(p for p in directory.rglob("*") if p.is_file())
    repo = GitRepo.resolve_for(directory)
    if repo is None:
        return candidates
    git_visible = git_visible_paths(repo.root)
    if git_visible is None:
        return candidates
    visible: list[Path] = []
    for candidate in candidates:
        try:
            rel = candidate.relative_to(repo.root).as_posix()
        except ValueError:
            # Should not happen: `candidate` was reached by rglob-ing
            # `directory`, which `GitRepo.resolve_for` walked UP FROM to
            # find `repo.root` -- so `candidate` is always under it. Logged
            # rather than silently dropped in case that invariant is ever
            # violated (a symlink escaping the tree, say).
            logger.info(
                "comment_finder: %s is not under resolved repo root %s; skipping",
                candidate,
                repo.root,
            )
            continue
        if rel in git_visible:
            visible.append(candidate)
    return visible


def find_long_comment_blocks(
    paths: list[Path], min_lines: int = DEFAULT_MIN_BLOCK_LINES
) -> list[CommentBlockFinding]:
    """Find every non-doc comment block at or above ``min_lines`` under ``paths``.

    Args:
        paths: Files and/or directories to scan. Directories are expanded
            recursively; files with no registered comment strategy (no
            supported extension) are silently skipped.
        min_lines: Minimum block length (physical lines) to report.

    Returns:
        Findings in file-then-position order. Docstring/JSDoc-style spans
        (``is_doc``) are excluded — they are already documentation in a
        recognised, tooled location, not the "comment functioning as
        documentation" shape Decision 7 targets.
    """
    registry = CommentStrategyRegistry.create_default()
    findings: list[CommentBlockFinding] = []
    for file_path in _iter_candidate_files(paths):
        strategy = registry.get_strategy(str(file_path))
        if strategy is None:
            continue
        content = file_path.read_text(errors="ignore")
        for span in extract_comment_spans(content, strategy.syntax):
            if span.is_doc or span.line_count < min_lines:
                continue
            first_line = span.text.split("\n", 1)[0]
            findings.append(
                CommentBlockFinding(
                    path=file_path,
                    start_line=span.start_line + 1,
                    end_line=span.end_line + 1,
                    line_count=span.line_count,
                    preview=first_line,
                )
            )
    return findings
