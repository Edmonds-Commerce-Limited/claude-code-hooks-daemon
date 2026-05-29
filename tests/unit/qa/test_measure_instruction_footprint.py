"""Tests for scripts/qa/measure_instruction_footprint.py.

Phase 1 of Plan 00116: measurement harness and no-loss contract.

Tests cover:
  - Snapshot structure: expected keys and types present
  - Byte/line/approx-token counts are non-negative integers
  - Term-set contract: every blocking handler's get_claude_md() contains
    the blocked literals and prescribed fixes recorded in this test
    (the no-semantic-loss regression contract for later phases).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from pathlib import Path
from typing import Any

import pytest

# Add scripts/qa to sys.path so we can import the measurement module
_WORKTREE_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCRIPTS_QA = _WORKTREE_ROOT / "scripts" / "qa"
sys.path.insert(0, str(_SCRIPTS_QA))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_measure() -> Any:
    """Import measure_instruction_footprint lazily so the module is importable."""
    return importlib.import_module("measure_instruction_footprint")


def _load_all_handler_instances() -> list[Any]:
    """Return instantiated Handler objects from the production handler package."""
    from claude_code_hooks_daemon.core.handler import Handler

    import claude_code_hooks_daemon.handlers as handlers_pkg

    # Initialise ProjectContext so handlers that call project_root() during __init__
    # do not raise RuntimeError in the bare test environment.
    # The worktree does not have .claude/hooks-daemon.yaml; try the main workspace
    # config first (self-install mode at /workspace).
    try:
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        already_initialized = getattr(ProjectContext, "_initialized", False)
        if not already_initialized:
            # Try main workspace config (self-install mode)
            main_config = Path("/workspace/.claude/hooks-daemon.yaml")
            worktree_config = _WORKTREE_ROOT / ".claude" / "hooks-daemon.yaml"
            if main_config.exists():
                ProjectContext.initialize(main_config)
            elif worktree_config.exists():
                ProjectContext.initialize(worktree_config)
            else:
                # Fallback: use pyproject.toml path (sufficient for basic init)
                ProjectContext.initialize(_WORKTREE_ROOT / "pyproject.toml")
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


def _handler_guidance_map() -> dict[str, str]:
    """Return {handler_name: get_claude_md()} for handlers with non-None guidance."""
    result: dict[str, str] = {}
    for instance in _load_all_handler_instances():
        try:
            md = instance.get_claude_md()
        except (AttributeError, NotImplementedError) as exc:
            logger.debug("Handler %s.get_claude_md() failed: %s", instance.name, exc)
            continue
        if md is not None:
            result[instance.name] = md
    return result


# ---------------------------------------------------------------------------
# Phase 1.1 — Snapshot structure tests
# ---------------------------------------------------------------------------


class TestSnapshotStructure:
    """Verify measure_instruction_footprint returns a well-formed snapshot."""

    def test_module_importable(self) -> None:
        """The measurement module can be imported."""
        m = _import_measure()
        assert m is not None

    def test_measure_returns_dict(self) -> None:
        """measure() returns a dict."""
        m = _import_measure()
        result = m.measure()
        assert isinstance(result, dict)

    def test_snapshot_has_hooksdaemon_block(self) -> None:
        """Snapshot contains an 'injected_block' key."""
        m = _import_measure()
        result = m.measure()
        assert "injected_block" in result

    def test_snapshot_has_handlers(self) -> None:
        """Snapshot contains a 'handlers' key."""
        m = _import_measure()
        result = m.measure()
        assert "handlers" in result

    def test_snapshot_has_always_on_tree(self) -> None:
        """Snapshot contains an 'always_on_tree' key."""
        m = _import_measure()
        result = m.measure()
        assert "always_on_tree" in result

    def test_injected_block_has_byte_count(self) -> None:
        """injected_block has bytes field as non-negative int."""
        m = _import_measure()
        result = m.measure()
        block = result["injected_block"]
        assert "bytes" in block
        assert isinstance(block["bytes"], int)
        assert block["bytes"] >= 0

    def test_injected_block_has_line_count(self) -> None:
        """injected_block has lines field as non-negative int."""
        m = _import_measure()
        result = m.measure()
        block = result["injected_block"]
        assert "lines" in block
        assert isinstance(block["lines"], int)
        assert block["lines"] >= 0

    def test_injected_block_has_approx_tokens(self) -> None:
        """injected_block has approx_tokens field as non-negative int."""
        m = _import_measure()
        result = m.measure()
        block = result["injected_block"]
        assert "approx_tokens" in block
        assert isinstance(block["approx_tokens"], int)
        assert block["approx_tokens"] >= 0

    def test_handlers_is_dict(self) -> None:
        """handlers is a dict mapping handler name -> measurement."""
        m = _import_measure()
        result = m.measure()
        assert isinstance(result["handlers"], dict)

    def test_handlers_non_empty(self) -> None:
        """handlers dict has at least one entry (handlers exist in the system)."""
        m = _import_measure()
        result = m.measure()
        assert len(result["handlers"]) > 0

    def test_handler_entry_has_bytes(self) -> None:
        """Each handler entry has a bytes field."""
        m = _import_measure()
        result = m.measure()
        for name, entry in result["handlers"].items():
            assert "bytes" in entry, f"Handler {name!r} missing 'bytes'"
            assert isinstance(entry["bytes"], int)
            assert entry["bytes"] >= 0

    def test_handler_entry_has_lines(self) -> None:
        """Each handler entry has a lines field."""
        m = _import_measure()
        result = m.measure()
        for name, entry in result["handlers"].items():
            assert "lines" in entry, f"Handler {name!r} missing 'lines'"
            assert isinstance(entry["lines"], int)
            assert entry["lines"] >= 0

    def test_handler_entry_has_approx_tokens(self) -> None:
        """Each handler entry has an approx_tokens field."""
        m = _import_measure()
        result = m.measure()
        for name, entry in result["handlers"].items():
            assert "approx_tokens" in entry, f"Handler {name!r} missing 'approx_tokens'"
            assert isinstance(entry["approx_tokens"], int)
            assert entry["approx_tokens"] >= 0

    def test_always_on_tree_has_bytes(self) -> None:
        """always_on_tree has bytes field."""
        m = _import_measure()
        result = m.measure()
        tree = result["always_on_tree"]
        assert "bytes" in tree
        assert isinstance(tree["bytes"], int)
        assert tree["bytes"] >= 0

    def test_always_on_tree_has_approx_tokens(self) -> None:
        """always_on_tree has approx_tokens field."""
        m = _import_measure()
        result = m.measure()
        tree = result["always_on_tree"]
        assert "approx_tokens" in tree
        assert isinstance(tree["approx_tokens"], int)
        assert tree["approx_tokens"] >= 0

    def test_snapshot_serializable_to_json(self) -> None:
        """measure() output is JSON-serialisable (regression baseline requirement)."""
        import json

        m = _import_measure()
        result = m.measure()
        serialised = json.dumps(result)
        assert isinstance(serialised, str)
        assert len(serialised) > 0

    def test_baseline_snapshot_function_exists(self) -> None:
        """save_baseline() function is present in the module."""
        m = _import_measure()
        assert hasattr(m, "save_baseline")
        assert callable(m.save_baseline)

    def test_load_baseline_function_exists(self) -> None:
        """load_baseline() function is present in the module."""
        m = _import_measure()
        assert hasattr(m, "load_baseline")
        assert callable(m.load_baseline)

    def test_approx_tokens_plausible_for_injected_block(self) -> None:
        """approx_tokens for the injected block is plausible (> 0 if bytes > 0)."""
        m = _import_measure()
        result = m.measure()
        block = result["injected_block"]
        if block["bytes"] > 0:
            assert block["approx_tokens"] > 0


# ---------------------------------------------------------------------------
# Phase 1.2 — Term-set contract tests
#
# These tests record the EXACT blocked literals and prescribed fixes found in
# each blocking handler's get_claude_md(). They are the no-semantic-loss
# contract: later phases (e.g. rewriting get_claude_md() to emit a compact
# table) MUST NOT break these assertions.
#
# The tests inspect the live handler instances loaded from the production
# module tree. If a handler's get_claude_md() returns None it is excluded
# from term-set checks (it has no always-on guidance to preserve).
# ---------------------------------------------------------------------------


class TestTermSetContract:
    """No-semantic-loss contract: blocked literals + fixes survive in handler guidance."""

    # The term sets below are extracted from the live handlers as of 2026-05-29.
    # Each entry: (handler_name_fragment, required_terms).
    # All terms must appear (case-insensitively) in that handler's get_claude_md().
    # Handler name fragments match against the handler's display name (e.g.
    # "prevent-destructive-git", "block-sed-command") not the config key.
    _REQUIRED_TERMS: list[tuple[str, list[str]]] = [
        # destructive_git handler — display name "prevent-destructive-git"
        (
            "prevent-destructive-git",
            [
                "git reset --hard",
                "git clean -f",
                "git stash drop",
                "git stash clear",
                "git push --force",
                "git branch -D",
                "git commit --amend",
                "git checkout",
                "git restore",
            ],
        ),
        # sed_blocker handler — display name "block-sed-command"
        (
            "block-sed-command",
            [
                "sed -i",
                "Edit",
            ],
        ),
        # pipe_blocker handler — display name "pipe-blocker"
        (
            "pipe-blocker",
            [
                "tail",
                "head",
            ],
        ),
        # tdd_enforcement handler — display name "enforce-tdd"
        (
            "enforce-tdd",
            [
                "test file",
                "source file",
            ],
        ),
        # markdown_organization handler — display name "enforce-markdown-organization"
        (
            "enforce-markdown-organization",
            [
                ".md",
            ],
        ),
        # qa_suppression handler — display name "qa-suppression-blocker"
        (
            "qa-suppression-blocker",
            [
                "noqa",
            ],
        ),
        # lock_file_edit_blocker handler — display name "lock-file-edit-blocker"
        (
            "lock-file-edit-blocker",
            [
                "lock",
            ],
        ),
        # absolute_path handler — display name "require-absolute-paths"
        (
            "require-absolute-paths",
            [
                "absolute",
            ],
        ),
        # git_stash handler — display name "block-git-stash"
        (
            "block-git-stash",
            [
                "git stash",
            ],
        ),
        # curl_pipe_shell handler — display name "block-curl-pipe-shell"
        (
            "block-curl-pipe-shell",
            [
                "curl",
                "bash",
            ],
        ),
        # dangerous_permissions handler — display name "block-dangerous-permissions"
        (
            "block-dangerous-permissions",
            [
                "chmod 777",
            ],
        ),
    ]

    def _get_md_for_handler(self, handler_name_fragment: str) -> str | None:
        """Find the guidance text for a handler whose name contains the fragment."""
        guidance_map = _handler_guidance_map()
        for name, md in guidance_map.items():
            if handler_name_fragment in name:
                return md
        return None

    @pytest.mark.parametrize("handler_fragment,terms", _REQUIRED_TERMS)
    def test_terms_present_in_handler_guidance(
        self, handler_fragment: str, terms: list[str]
    ) -> None:
        """Every recorded term appears in the handler's get_claude_md() output."""
        md = self._get_md_for_handler(handler_fragment)
        if md is None:
            pytest.skip(f"Handler matching {handler_fragment!r} not found or returns None")

        md_lower = md.lower()
        for term in terms:
            assert term.lower() in md_lower, (
                f"Term {term!r} not found in {handler_fragment!r} guidance.\n"
                f"Guidance (first 400 chars): {md[:400]!r}"
            )

    def test_at_least_one_handler_has_guidance(self) -> None:
        """At least one handler provides non-None get_claude_md() output."""
        guidance_map = _handler_guidance_map()
        assert len(guidance_map) > 0, "No handlers returned guidance — handler loading failed"

    def test_destructive_git_has_nine_patterns(self) -> None:
        """destructive_git guidance covers all 9 specific block reasons."""
        md = self._get_md_for_handler("prevent-destructive-git")
        if md is None:
            pytest.skip("destructive_git handler not found or could not be instantiated")
        commands = [
            "git reset --hard",
            "git clean -f",
            "git stash drop",
            "git stash clear",
            "git push --force",
            "git branch -D",
            "git commit --amend",
            "git checkout",
            "git restore",
        ]
        md_lower = md.lower()
        for cmd in commands:
            assert cmd.lower() in md_lower, (
                f"Command {cmd!r} missing from destructive_git guidance"
            )
