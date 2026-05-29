#!/usr/bin/env python3
"""Measure the token/byte/line footprint of the daemon's always-on instruction content.

Plan 00116, Phase 1 (Task 1.1).

Computes byte / line / approx-token counts for:
  - The injected ``<hooksdaemon>`` block (from the live CLAUDE.md in the workspace root)
  - Each active handler's ``get_claude_md()`` output individually
  - The full always-on instruction tree (CLAUDE.md + known ``@``-imported docs)

Emits a snapshot dict (JSON-serialisable) that is the regression baseline for
later phases.  Save it once with ``save_baseline()``; compare future snapshots
with ``load_baseline()`` to verify the token budget has not regressed.

Approximate token count formula: ``len(text) // 4`` (widely used rough estimate;
actual tokenisation varies by model but is consistent enough for trending).

Usage (standalone)::

    python scripts/qa/measure_instruction_footprint.py

Usage (from tests)::

    from measure_instruction_footprint import measure, save_baseline, load_baseline
    snapshot = measure()
"""

from __future__ import annotations

import importlib
import json
import logging
import pkgutil
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Resolve project root from this script's location: scripts/qa/ -> root
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent.parent

# The CLAUDE.md in the workspace root (may differ from worktree root)
_CLAUDE_MD_PATH = _PROJECT_ROOT / "CLAUDE.md"

# Always-on @-imported documents (relative to project root)
_AT_IMPORTED_DOCS: list[Path] = [
    _PROJECT_ROOT / "CLAUDE" / "PlanWorkflow.md",
    _PROJECT_ROOT / "CLAUDE" / "development" / "RELEASING.md",
    _PROJECT_ROOT / "CLAUDE" / "CodeLifecycle" / "Features.md",
    _PROJECT_ROOT / "CLAUDE" / "CodeLifecycle" / "Bugs.md",
    _PROJECT_ROOT / "CLAUDE" / "CodeLifecycle" / "General.md",
    _PROJECT_ROOT / ".claude" / "HOOKS-DAEMON.md",
]

# Default baseline storage location (untracked so it is never committed)
_BASELINE_DIR = _PROJECT_ROOT / "untracked" / "qa"
_BASELINE_FILE = _BASELINE_DIR / "instruction_footprint_baseline.json"

# Tag delimiters for the injected block
_OPEN_TAG = "<hooksdaemon>"
_CLOSE_TAG = "</hooksdaemon>"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # Approximation: 1 token ≈ 4 characters


def _approx_tokens(text: str) -> int:
    """Return approximate token count using the 4-chars-per-token heuristic."""
    return len(text) // _CHARS_PER_TOKEN


def _measure_text(text: str) -> dict[str, int]:
    """Return {bytes, lines, approx_tokens} for a text string."""
    encoded = text.encode("utf-8")
    lines = text.count("\n")
    return {
        "bytes": len(encoded),
        "lines": lines,
        "approx_tokens": _approx_tokens(text),
    }


def _extract_injected_block(claude_md_text: str) -> str:
    """Extract the content between <hooksdaemon>...</hooksdaemon> tags.

    Returns an empty string if the tags are not present.

    Args:
        claude_md_text: Full text of the CLAUDE.md file.

    Returns:
        The injected block content (including the tags themselves).
    """
    pattern = re.compile(
        re.escape(_OPEN_TAG) + r"(.*?)" + re.escape(_CLOSE_TAG),
        re.DOTALL,
    )
    match = pattern.search(claude_md_text)
    if not match:
        return ""
    # Return the full match including surrounding tags
    return match.group(0)


def _load_all_handler_instances() -> list[Any]:
    """Return instantiated Handler objects from the production handler package.

    Skips handlers that cannot be imported or instantiated, logging the reason.
    """
    # Ensure the src directory is importable
    src_path = str(_PROJECT_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    try:
        import claude_code_hooks_daemon.handlers as handlers_pkg
        from claude_code_hooks_daemon.core.handler import Handler
    except ImportError as exc:
        logger.warning("Could not import handler package: %s", exc)
        return []

    # Initialise ProjectContext so handlers that call project_root() during
    # __init__ do not raise RuntimeError.  When running from a worktree the
    # project root may not have the config file; fall back to /workspace (the
    # self-install location) if the local config is absent.
    try:
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        already_initialized = getattr(ProjectContext, "_initialized", False)
        if not already_initialized:
            config_path = _PROJECT_ROOT / ".claude" / "hooks-daemon.yaml"
            if not config_path.exists():
                # Worktree fallback: try the main workspace self-install config
                config_path = Path("/workspace/.claude/hooks-daemon.yaml")
            if not config_path.exists():
                config_path = _PROJECT_ROOT / "pyproject.toml"
            ProjectContext.initialize(config_path)
    except Exception as exc:
        logger.debug("Could not initialize ProjectContext: %s", exc)

    subclasses: list[type] = []
    for _finder, name, _ispkg in pkgutil.walk_packages(
        handlers_pkg.__path__, prefix=handlers_pkg.__name__ + "."
    ):
        try:
            mod = importlib.import_module(name)
        except ImportError as exc:
            logger.debug("Skipping handler module %s: %s", name, exc)
            continue
        for attr in dir(mod):
            obj = getattr(mod, attr)
            try:
                if (
                    isinstance(obj, type)
                    and issubclass(obj, Handler)
                    and obj is not Handler
                    and not getattr(obj, "__abstractmethods__", None)
                ):
                    subclasses.append(obj)
            except TypeError as exc:
                logger.debug("Skipping attr %s.%s: %s", name, attr, exc)

    seen: set[type] = set()
    instances: list[Any] = []
    for cls in subclasses:
        if cls not in seen:
            seen.add(cls)
            try:
                instances.append(cls())
            except (TypeError, ValueError, RuntimeError) as exc:
                logger.debug("Could not instantiate %s: %s", cls.__name__, exc)
    return instances


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def measure() -> dict[str, Any]:
    """Measure the instruction footprint and return a JSON-serialisable snapshot.

    Returns a dict with three keys:

    ``injected_block``
        Measurement of the ``<hooksdaemon>…</hooksdaemon>`` section extracted
        from the workspace CLAUDE.md.

    ``handlers``
        Dict mapping handler name → measurement of its ``get_claude_md()``
        output.  Handlers returning ``None`` are excluded.

    ``always_on_tree``
        Cumulative measurement of the full always-on instruction tree:
        CLAUDE.md + all ``@``-imported docs.

    Returns:
        JSON-serialisable dict with the three measurement sections.
    """
    snapshot: dict[str, Any] = {}

    # 1. Injected block from CLAUDE.md
    claude_md_text = ""
    if _CLAUDE_MD_PATH.exists():
        claude_md_text = _CLAUDE_MD_PATH.read_text(encoding="utf-8")

    injected_block_text = _extract_injected_block(claude_md_text)
    snapshot["injected_block"] = _measure_text(injected_block_text)

    # 2. Per-handler get_claude_md() measurements
    handlers_map: dict[str, dict[str, int]] = {}
    for instance in _load_all_handler_instances():
        try:
            md = instance.get_claude_md()
        except (AttributeError, NotImplementedError) as exc:
            logger.debug("Handler %s.get_claude_md() failed: %s", instance.name, exc)
            continue
        if md is not None:
            handlers_map[instance.name] = _measure_text(md)

    snapshot["handlers"] = handlers_map

    # 3. Always-on tree: CLAUDE.md + all @-imported docs
    total_text = claude_md_text
    for doc_path in _AT_IMPORTED_DOCS:
        if doc_path.exists():
            total_text += doc_path.read_text(encoding="utf-8")
        else:
            logger.debug("At-imported doc not found: %s", doc_path)

    always_on = _measure_text(total_text)
    # Also record which @-imported files were found
    always_on["at_imported_docs"] = len([p for p in _AT_IMPORTED_DOCS if p.exists()])
    snapshot["always_on_tree"] = always_on

    return snapshot


def save_baseline(snapshot: dict[str, Any] | None = None, path: Path | None = None) -> Path:
    """Save a snapshot as the regression baseline.

    Args:
        snapshot: Snapshot to save; if None, calls ``measure()`` first.
        path:     Output file path; defaults to ``untracked/qa/instruction_footprint_baseline.json``.

    Returns:
        Path to the saved file.
    """
    if snapshot is None:
        snapshot = measure()

    target = path or _BASELINE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    logger.info("Baseline saved to %s", target)
    return target


def load_baseline(path: Path | None = None) -> dict[str, Any] | None:
    """Load a previously saved regression baseline.

    Args:
        path: File path; defaults to ``untracked/qa/instruction_footprint_baseline.json``.

    Returns:
        The parsed snapshot dict, or None if the file does not exist.
    """
    target = path or _BASELINE_FILE
    if not target.exists():
        logger.debug("No baseline file found at %s", target)
        return None
    return json.loads(target.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _main() -> None:
    """Print a human-readable measurement report to stdout."""
    logging.basicConfig(level=logging.WARNING)
    snapshot = measure()

    injected = snapshot["injected_block"]
    tree = snapshot["always_on_tree"]

    print("=" * 60)
    print("Instruction Footprint Report")
    print("=" * 60)
    print("\nInjected <hooksdaemon> block:")
    print(f"  Bytes:        {injected['bytes']:>8,}")
    print(f"  Lines:        {injected['lines']:>8,}")
    print(f"  Approx tokens:{injected['approx_tokens']:>8,}")

    print("\nAlways-on instruction tree (CLAUDE.md + @-imports):")
    print(f"  Bytes:        {tree['bytes']:>8,}")
    print(f"  Lines:        {tree.get('lines', '?'):>8}")
    print(f"  Approx tokens:{tree['approx_tokens']:>8,}")

    handlers = snapshot["handlers"]
    if handlers:
        print(f"\nPer-handler get_claude_md() sizes ({len(handlers)} handlers):")
        for name, m in sorted(handlers.items(), key=lambda x: x[1]["bytes"], reverse=True):
            print(f"  {name:<40} {m['bytes']:>6,} B  ~{m['approx_tokens']:>4} tok")

    print("\nFull JSON snapshot:")
    print(json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    _main()
