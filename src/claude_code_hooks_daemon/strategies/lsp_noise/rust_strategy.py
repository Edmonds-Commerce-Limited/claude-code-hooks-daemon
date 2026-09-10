"""Rust LSP-noise strategy: rust-analyzer honours Cargo workspace membership.

Like gopls, rust-analyzer takes no project-file exclude configuration
(verified against ``anthropics/claude-plugins-official``'s
``.claude-plugin/marketplace.json``: the ``rust-analyzer-lsp`` entry carries
no ``settings``/``initializationOptions``) - it scopes to the crates the
root ``Cargo.toml`` declares as workspace members instead. Unlike Go,
Cargo's workspace manifest DOES carry a real, project-editable membership
knob: ``[workspace] exclude = [...]``. The fix this strategy prints points
there rather than at "give it its own manifest", because a nested
``Cargo.toml`` alone does not stop the ROOT workspace from auto-discovering
it as a member - the ``exclude`` list is what does.

Scope: only the daemon's own plain (non-glob) required trees - its runtime
directory, the plan directory, the remote-docs tree - are walked, for the
same reason as the Go strategy: a same-language vendored directory
practically never holds a different language's source files.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.common import (
    json_list,
    tree_contains_extension,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LANGUAGE_NAME: Final[str] = "Rust"
_PROCESS_NAMES: Final[tuple[str, ...]] = ("rust-analyzer",)
_CARGO_TOML_FILE: Final[str] = "Cargo.toml"
_RUST_EXTENSION: Final[str] = ".rs"
_ANY_DEPTH_PREFIX: Final[str] = "**/"


class RustLspNoiseStrategy:
    """LSP-noise strategy for Rust projects (rust-analyzer)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def process_names(self) -> tuple[str, ...]:
        return _PROCESS_NAMES

    def is_relevant(self, context: RelevanceContext) -> bool:
        return context.uses_any_language(HandlerTag.RUST)

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        cargo_toml = root / _CARGO_TOML_FILE
        if not cargo_toml.is_file():
            return [], None

        plain_trees = sorted(r for r in required if not r.startswith(_ANY_DEPTH_PREFIX))
        offending = [
            tree
            for tree in plain_trees
            if tree_contains_extension(
                root, tree, _RUST_EXTENSION, prune_names=CORE_VENDORED_BUILD_DIR_NAMES
            )
        ]
        if not offending:
            return [], cargo_toml

        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): rust-analyzer "
            f"takes no exclude list - it scopes to {_CARGO_TOML_FILE}'s declared workspace "
            f"members - and {len(offending)} tree(s) that are not this project's code hold "
            "`.rs` files rust-analyzer would pick up as members:",
            "",
            *(f"  ❌ {entry}" for entry in offending),
            "",
            f"Fix: add these to `[workspace] exclude` in the root {_CARGO_TOML_FILE} "
            "(paste-ready):",
            *json_list(offending),
            "",
            "then end the running language server so it re-reads the workspace. LSP "
            "output must be signal: fix the noise source, never skim the stream.",
            "",
        ], cargo_toml

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="lsp noise checker - Rust - reports .rs files inside a non-project tree",
                command='echo "test"',
                description=(
                    "In a Rust project whose daemon runtime directory holds a stray .rs "
                    "file, a new session is told which non-project trees rust-analyzer "
                    "will pick up and the workspace-exclude fix."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"R-LSP-CONFIG-EXCLUDE", r"Rust"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, Rust project)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
