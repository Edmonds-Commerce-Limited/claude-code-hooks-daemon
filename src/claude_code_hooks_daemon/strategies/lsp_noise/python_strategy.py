"""Python LSP-noise strategy: pyright's ``exclude`` list.

pyright reads its own project-root config regardless of who launches it
(Claude Code's ``pyright-lsp`` marketplace plugin ships no ``settings`` or
``initializationOptions`` at all - verified against
``anthropics/claude-plugins-official``'s ``.claude-plugin/marketplace.json``),
so the noise-source fix is the same file whoever is running pyright: add the
missing trees to ``pyrightconfig.json``'s (or ``[tool.pyright]``'s)
``exclude``.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.common import (
    ConfigView,
    entry_covers,
    json_list,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LANGUAGE_NAME: Final[str] = "Python"
_PROCESS_NAMES: Final[tuple[str, ...]] = ("pyright-langserver",)
_PYRIGHT_CONFIG_FILE: Final[str] = "pyrightconfig.json"
_PYPROJECT_FILE: Final[str] = "pyproject.toml"
_PYPROJECT_TOOL_TABLE: Final[str] = "[tool.pyright]"
_EXCLUDE_KEY: Final[str] = "exclude"


class PythonLspNoiseStrategy:
    """LSP-noise strategy for Python projects (pyright)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def process_names(self) -> tuple[str, ...]:
        return _PROCESS_NAMES

    def is_relevant(self, context: RelevanceContext) -> bool:
        return context.uses_any_language(HandlerTag.PYTHON)

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        view = self._read_config(root)
        return self._finding(view, required), view.path

    def _read_config(self, root: Path) -> ConfigView:
        json_path = root / _PYRIGHT_CONFIG_FILE
        if json_path.is_file():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return ConfigView(json_path, _PYRIGHT_CONFIG_FILE, None, parse_error=str(exc))
            return ConfigView(json_path, _PYRIGHT_CONFIG_FILE, _exclude_list(data))

        pyproject = root / _PYPROJECT_FILE
        if pyproject.is_file():
            where = f"{_PYPROJECT_TOOL_TABLE} in {_PYPROJECT_FILE}"
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                return ConfigView(pyproject, where, None, parse_error=str(exc))
            table = data.get("tool", {}).get("pyright")
            if isinstance(table, dict):
                return ConfigView(pyproject, where, _exclude_list(table))
        return ConfigView(None, _PYRIGHT_CONFIG_FILE, None)

    def _finding(self, view: ConfigView, required: frozenset[str]) -> list[str]:
        wanted = sorted(required)
        if view.parse_error is not None:
            return [
                f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): "
                f"{view.where} could not be parsed ({view.parse_error}), so pyright "
                "is running on its defaults and analysing everything.",
                "",
                "Fix the file, then check it excludes:",
                *json_list(wanted),
                "",
            ]
        if view.path is None:
            return [
                f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): no pyright "
                "config at the project root, so the language server analyses every tree "
                "here, including ones that are not this project's code.",
                "",
                f"Fix: create {_PYRIGHT_CONFIG_FILE} with at least:",
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
                title="lsp noise checker - Python - reports a missing pyright exclude",
                command='echo "test"',
                description=(
                    "In a Python project whose pyrightconfig.json lacks an exclude for "
                    "the daemon's runtime dir, a new session is told which entries are "
                    "missing, ready to paste."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"R-LSP-CONFIG-EXCLUDE", r"Python"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, Python project)",
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
