"""TypeScript/JavaScript LSP-noise strategy: tsconfig.json / jsconfig.json ``exclude``.

Like pyright, ``typescript-language-server`` reads the project's own
``tsconfig.json``/``jsconfig.json`` regardless of who launches it - Claude
Code's ``typescript-lsp`` marketplace plugin ships no ``settings`` or
``initializationOptions`` (verified against
``anthropics/claude-plugins-official``'s ``.claude-plugin/marketplace.json``),
so the fix is the same project file whoever is running the server.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.common import (
    ConfigView,
    entry_covers,
    json_list,
    strip_jsonc_comments,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LANGUAGE_NAME: Final[str] = "TypeScript/JavaScript"
_PROCESS_NAMES: Final[tuple[str, ...]] = ("typescript-language-server",)
_TSCONFIG_FILE: Final[str] = "tsconfig.json"
_JSCONFIG_FILE: Final[str] = "jsconfig.json"
_CANDIDATE_FILES: Final[tuple[str, ...]] = (_TSCONFIG_FILE, _JSCONFIG_FILE)
_EXCLUDE_KEY: Final[str] = "exclude"


class TypeScriptLspNoiseStrategy:
    """LSP-noise strategy for TypeScript/JavaScript projects (tsserver)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def process_names(self) -> tuple[str, ...]:
        return _PROCESS_NAMES

    def is_relevant(self, context: RelevanceContext) -> bool:
        return context.uses_any_language(HandlerTag.TYPESCRIPT, HandlerTag.JAVASCRIPT)

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        view = self._read_config(root)
        return self._finding(view, required), view.path

    def _read_config(self, root: Path) -> ConfigView:
        for name in _CANDIDATE_FILES:
            path = root / name
            if not path.is_file():
                continue
            try:
                data = json.loads(strip_jsonc_comments(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                return ConfigView(path, name, None, parse_error=str(exc))
            return ConfigView(path, name, _exclude_list(data))
        return ConfigView(None, _TSCONFIG_FILE, None)

    def _finding(self, view: ConfigView, required: frozenset[str]) -> list[str]:
        wanted = sorted(required)
        if view.parse_error is not None:
            return [
                f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): "
                f"{view.where} could not be parsed ({view.parse_error}), so the language "
                "server is running on its defaults and analysing everything.",
                "",
                "Fix the file, then check it excludes:",
                *json_list(wanted),
                "",
            ]
        if view.path is None:
            return [
                f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): no "
                f"{_TSCONFIG_FILE} or {_JSCONFIG_FILE} at the project root, so the language "
                "server analyses every tree here, including ones that are not this "
                "project's code.",
                "",
                f"Fix: create {_TSCONFIG_FILE} with at least:",
                "",
                *json.dumps({_EXCLUDE_KEY: wanted}, indent=2).splitlines(),
                "",
                "then end the running language server so it re-reads the config.",
                "",
            ]
        present = view.exclude if view.exclude is not None else []
        missing = [want for want in wanted if not any(entry_covers(e, want) for e in present)]
        if not missing:
            return []
        no_key = "" if view.exclude is not None else " (it has no `exclude` at all)"
        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): {view.where} is "
            f"missing an `exclude` for {len(missing)} tree(s) that are not this project's "
            f"code{no_key}:",
            "",
            *(f"  ❌ {entry}" for entry in missing),
            "",
            "Fix: add these to `exclude` (paste-ready):",
            *json_list(missing),
            "",
            "then end the running language server so it re-reads the config. LSP output "
            "must be signal: fix the noise source, never skim the stream.",
            "",
        ]

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title=("lsp noise checker - TypeScript - reports a missing tsconfig exclude"),
                command='echo "test"',
                description=(
                    "In a TypeScript project whose tsconfig.json lacks an exclude for "
                    "the daemon's runtime dir, a new session is told which entries are "
                    "missing, ready to paste."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"R-LSP-CONFIG-EXCLUDE", r"TypeScript"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, TypeScript project)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _exclude_list(data: object) -> list[str] | None:
    """The config's ``exclude`` as strings, or None when there is no such key."""
    if not isinstance(data, dict):
        return None
    raw = data.get(_EXCLUDE_KEY)
    if not isinstance(raw, list):
        return None
    return [str(item) for item in raw]
