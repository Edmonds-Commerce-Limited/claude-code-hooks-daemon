"""Human-friendly worktree naming (Plan 00188).

Claude Code's ``WorktreeCreate`` hook fully delegates path choice to the hook —
the input carries no requested path, only a ``name`` field (an Agent-tool name
when set, else an ``agent-<id>`` auto-name). The daemon owns creation and gives
each worktree a *semantic, human-friendly* directory name instead of Claude
Code's opaque ``wf_<hash>`` default:

    <cwd>/.claude/worktrees/<slug-of-name>-<shorthash>/

The slug is the human-readable prefix; the short hash suffix guarantees
uniqueness (two agents named identically never collide) and puts the entropy at
the end where the owner wanted it. These are pure functions with no side
effects so the naming policy is independently testable.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# Directory (relative to the session cwd / repo root) that holds worktrees. This
# matches Claude Code's own ``.claude/worktrees/`` location and is gitignored.
WORKTREES_SUBDIR: str = ".claude/worktrees"

# Fallback slug when the name yields no usable characters (empty / all-punct).
FALLBACK_SLUG: str = "worktree"

# Maximum length of the slug prefix (keeps directory names sane; the hash suffix
# is appended after this cap).
SLUG_MAX_LENGTH: int = 40

# Number of hex characters in the uniqueness hash suffix.
HASH_SUFFIX_LENGTH: int = 8

# Separator joining the slug prefix and the hash suffix.
_NAME_SEPARATOR: str = "-"

# Any run of characters that is not lowercase-alphanumeric collapses to a single
# separator during slugification.
_NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Reduce an arbitrary name to a lowercase, hyphen-separated slug.

    Non-alphanumeric runs collapse to a single hyphen; leading/trailing hyphens
    are stripped; the result is capped at :data:`SLUG_MAX_LENGTH` (never leaving
    a trailing hyphen). An empty or all-punctuation name falls back to
    :data:`FALLBACK_SLUG`.
    """
    slug = _NON_SLUG_RUN.sub(_NAME_SEPARATOR, name.lower()).strip(_NAME_SEPARATOR)
    if len(slug) > SLUG_MAX_LENGTH:
        slug = slug[:SLUG_MAX_LENGTH].strip(_NAME_SEPARATOR)
    return slug or FALLBACK_SLUG


def _short_hash(name: str | None, prompt_id: str | None, session_id: str | None) -> str:
    """Return a short, stable hex hash of the identifying fields.

    MD5 is used for a short directory-identifier only, never for security
    (``usedforsecurity=False``). Distinct ``(name, prompt_id, session_id)`` tuples
    yield distinct suffixes so two identically-named agents never collide.
    """
    material = "|".join(part or "" for part in (name, prompt_id, session_id))
    digest = hashlib.md5(material.encode("utf-8"), usedforsecurity=False)  # nosec B324
    return digest.hexdigest()[:HASH_SUFFIX_LENGTH]


def worktree_dir_name(name: str | None, prompt_id: str | None, session_id: str | None) -> str:
    """Compute the worktree directory basename ``<slug>-<shorthash>``."""
    slug = slugify(name or "")
    return f"{slug}{_NAME_SEPARATOR}{_short_hash(name, prompt_id, session_id)}"


def worktree_path(
    cwd: str, name: str | None, prompt_id: str | None, session_id: str | None
) -> Path:
    """Return the absolute worktree path under ``<cwd>/.claude/worktrees/``."""
    return Path(cwd) / WORKTREES_SUBDIR / worktree_dir_name(name, prompt_id, session_id)
