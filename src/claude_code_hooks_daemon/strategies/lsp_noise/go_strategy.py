"""Go LSP-noise strategy: gopls has no exclude list at all.

Unlike pyright and tsserver, gopls takes no project-file exclude
configuration (verified against ``anthropics/claude-plugins-official``'s
``.claude-plugin/marketplace.json``: the ``gopls-lsp`` entry carries no
``settings``/``initializationOptions``) - it scopes to module boundaries
declared by ``go.mod`` instead. So there is nothing to "add an exclude
entry" to; the only real signal is whether one of the daemon's known
non-project trees actually holds ``.go`` files gopls would walk into as
part of this module.

Scope: only the daemon's own plain (non-glob) required trees - its runtime
directory, the plan directory, the remote-docs tree - are walked. The
any-depth vendored/build names (``**/node_modules`` and siblings) are not
separately walked here: in practice a same-language vendored directory
practically never holds a DIFFERENT language's source files, and a bounded
recursive walk of the whole project root to rule that out on every session
start would cost far more than the noise it could catch.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.common import tree_contains_extension

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LANGUAGE_NAME: Final[str] = "Go"
_PROCESS_NAMES: Final[tuple[str, ...]] = ("gopls",)
_GO_MOD_FILE: Final[str] = "go.mod"
_GO_EXTENSION: Final[str] = ".go"
_ANY_DEPTH_PREFIX: Final[str] = "**/"


class GoLspNoiseStrategy:
    """LSP-noise strategy for Go projects (gopls)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def process_names(self) -> tuple[str, ...]:
        return _PROCESS_NAMES

    def is_relevant(self, context: RelevanceContext) -> bool:
        return context.uses_any_language(HandlerTag.GO)

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        go_mod = root / _GO_MOD_FILE
        if not go_mod.is_file():
            return [], None

        plain_trees = sorted(r for r in required if not r.startswith(_ANY_DEPTH_PREFIX))
        offending = [
            tree
            for tree in plain_trees
            if tree_contains_extension(
                root, tree, _GO_EXTENSION, prune_names=CORE_VENDORED_BUILD_DIR_NAMES
            )
        ]
        if not offending:
            return [], go_mod

        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): gopls takes no "
            f"exclude list - it scopes to {_GO_MOD_FILE}'s module boundary - and "
            f"{len(offending)} tree(s) that are not this project's code hold `.go` files "
            "inside that boundary:",
            "",
            *(f"  ❌ {entry}" for entry in offending),
            "",
            "Fix: give each one its own module boundary (a nested go.mod, so gopls treats "
            "it as a separate module and does not walk into it from this one), or make "
            "sure it holds no .go files. Then end the running language server so it "
            "re-reads the module boundary. LSP output must be signal: fix the noise "
            "source, never skim the stream.",
            "",
        ], go_mod

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="lsp noise checker - Go - reports .go files inside a non-project tree",
                command='echo "test"',
                description=(
                    "In a Go project whose daemon runtime directory holds a stray .go "
                    "file, a new session is told which non-project trees gopls will "
                    "walk into and the module-boundary fix."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"R-LSP-CONFIG-EXCLUDE", r"Go"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, Go project)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
