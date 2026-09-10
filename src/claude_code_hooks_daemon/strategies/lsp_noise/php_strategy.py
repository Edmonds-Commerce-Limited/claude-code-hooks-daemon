"""PHP LSP-noise strategy: intelephense has no per-project config file.

Ground truth (Plan 00368, owner-directed research - do not re-derive this
from assumption): Claude Code's official ``php-lsp`` marketplace plugin
launches ``intelephense --stdio`` with NO ``settings`` or
``initializationOptions`` at all (verified against
``anthropics/claude-plugins-official``'s ``.claude-plugin/marketplace.json``
on GitHub). intelephense's own docs
(``bmewburn/intelephense-docs/gettingStarted.md``) confirm
``intelephense.files.exclude`` is a client-delivered LSP setting
(``"scope": "resource"``, sent via ``workspace/didChangeConfiguration``) -
there is no project-root file it reads on its own, unlike pyright's
``pyrightconfig.json`` or tsserver's ``tsconfig.json``.

The only real per-project knob Claude Code offers is a project-scoped LSP
plugin that re-registers the ``.php`` extension with its OWN ``settings``
block: ``plugins-reference.md``'s "Multiple servers for the same extension"
rule makes the FIRST registered server for an extension the one that runs,
so a plugin under this project's own ``.claude/plugins/`` genuinely
overrides the marketplace ``php-lsp`` entry for `.php` files. This strategy
scans every ``.lsp.json`` (or ``plugin.json`` ``lspServers`` block) under
``.claude/plugins/*/`` for one that registers ``.php`` and carries a
complete ``intelephense.files.exclude``; when none does, it prints that
exact file, ready to drop in - never "unsupported".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from claude_code_hooks_daemon.constants import HandlerTag
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.strategies.lsp_noise.common import (
    OverrideView,
    entry_covers,
    json_list,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.relevance import RelevanceContext

_LANGUAGE_NAME: Final[str] = "PHP"
_PROCESS_NAMES: Final[tuple[str, ...]] = ("intelephense",)
_PLUGINS_DIR_PARTS: Final[tuple[str, str]] = (".claude", "plugins")
_LSP_JSON_FILE: Final[str] = ".lsp.json"
_PLUGIN_MANIFEST_FILE: Final[str] = "plugin.json"
_INLINE_LSP_KEY: Final[str] = "lspServers"
_PHP_EXTENSION: Final[str] = ".php"
_EXTENSION_TO_LANGUAGE_KEY: Final[str] = "extensionToLanguage"
_SETTINGS_KEY: Final[str] = "settings"
_INTELEPHENSE_SERVER_NAME: Final[str] = "intelephense"
_FLAT_EXCLUDE_KEY: Final[str] = "intelephense.files.exclude"
_SUGGESTED_PLUGIN_DIR: Final[str] = "lsp-noise-php-exclude"


class PhpLspNoiseStrategy:
    """LSP-noise strategy for PHP projects (intelephense)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def process_names(self) -> tuple[str, ...]:
        return _PROCESS_NAMES

    def is_relevant(self, context: RelevanceContext) -> bool:
        return context.uses_any_language(HandlerTag.PHP)

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        view = self._best_override(root)
        wanted = sorted(required)

        if view.path is None:
            return self._no_override_finding(wanted), None

        present = view.exclude if view.exclude is not None else []
        missing = [want for want in wanted if not any(entry_covers(e, want) for e in present)]
        if not missing:
            return [], view.path

        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): the project-scope "
            f"LSP plugin at {view.path} is missing `{_FLAT_EXCLUDE_KEY}` for "
            f"{len(missing)} tree(s) that are not this project's code:",
            "",
            *(f"  ❌ {entry}" for entry in missing),
            "",
            "Fix: add these to that plugin's `settings.intelephense.files.exclude` (paste-ready):",
            *json_list(missing),
            "",
            "then end the running language server so it re-reads the config. LSP output "
            "must be signal: fix the noise source, never skim the stream.",
            "",
        ], view.path

    def _no_override_finding(self, wanted: list[str]) -> list[str]:
        snippet = json.dumps(
            {
                _INTELEPHENSE_SERVER_NAME: {
                    "command": _INTELEPHENSE_SERVER_NAME,
                    "args": ["--stdio"],
                    _EXTENSION_TO_LANGUAGE_KEY: {_PHP_EXTENSION: "php"},
                    _SETTINGS_KEY: {_FLAT_EXCLUDE_KEY: wanted},
                }
            },
            indent=2,
        )
        plugin_path = "/".join((*_PLUGINS_DIR_PARTS, _SUGGESTED_PLUGIN_DIR, _LSP_JSON_FILE))
        return [
            f"⚠️  LSP NOISE [{RuleID.LSP_CONFIG_EXCLUDE}] ({_LANGUAGE_NAME}): intelephense "
            "takes its exclude list from LSP client settings, not a project file - "
            "Claude Code's official `php-lsp` marketplace plugin ships no `settings` at "
            "all, so there is no per-project file to edit for it directly.",
            "",
            "Fix: create a project-scope LSP plugin that re-registers `.php` with its own "
            "`settings` (the first server registered for an extension is the one Claude "
            f"Code runs, so this REPLACES the marketplace server). Create {plugin_path}:",
            "",
            *snippet.splitlines(),
            "",
            "then end the running language server so it re-reads the config. LSP output "
            "must be signal: fix the noise source, never skim the stream.",
            "",
        ]

    def _best_override(self, root: Path) -> OverrideView:
        """The most useful candidate override found under `.claude/plugins/*/`.

        Prefers the first COMPLETE override (covers everything asked); when
        none is complete, returns the first candidate found at all, so a
        partially-configured override is still named in the advisory rather
        than treated as if none existed. A directory that does not exist, or
        a file that cannot be parsed, is skipped - never raised: this feeds
        a session-start advisory, not a decision path.
        """
        plugins_dir = root.joinpath(*_PLUGINS_DIR_PARTS)
        if not plugins_dir.is_dir():
            return OverrideView(None, None)

        first_candidate: OverrideView | None = None
        for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
            for candidate in self._candidate_exclude(plugin_dir):
                if first_candidate is None:
                    first_candidate = candidate
                if candidate.exclude is not None:
                    return candidate
        return first_candidate if first_candidate is not None else OverrideView(None, None)

    def _candidate_exclude(self, plugin_dir: Path) -> list[OverrideView]:
        found: list[OverrideView] = []
        lsp_json = plugin_dir / _LSP_JSON_FILE
        if lsp_json.is_file():
            servers = _load_json_object(lsp_json)
            if servers is not None:
                found.extend(self._views_from_servers(lsp_json, servers))

        manifest = plugin_dir / _PLUGIN_MANIFEST_FILE
        if manifest.is_file():
            data = _load_json_object(manifest)
            if data is not None:
                servers = data.get(_INLINE_LSP_KEY)
                if isinstance(servers, dict):
                    found.extend(self._views_from_servers(manifest, servers))
        return found

    def _views_from_servers(self, path: Path, servers: dict[str, Any]) -> list[OverrideView]:
        views: list[OverrideView] = []
        for server in servers.values():
            if not isinstance(server, dict):
                continue
            extension_map = server.get(_EXTENSION_TO_LANGUAGE_KEY)
            if not isinstance(extension_map, dict) or _PHP_EXTENSION not in extension_map:
                continue
            views.append(OverrideView(path, _extract_exclude(server.get(_SETTINGS_KEY))))
        return views

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="lsp noise checker - PHP - prints the project-scope override snippet",
                command='echo "test"',
                description=(
                    "In a PHP project with no project-scope LSP plugin overriding "
                    "intelephense, a new session is told exactly which .lsp.json to "
                    "create and why there is no simpler per-project file."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"R-LSP-CONFIG-EXCLUDE", r"PHP"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session, PHP project)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _load_json_object(path: Path) -> dict[str, Any] | None:
    """The file's JSON content as a dict, or None on any read/parse failure."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_exclude(settings: object) -> list[str] | None:
    """The exclude list from a server's ``settings``, flat or nested, or None."""
    if not isinstance(settings, dict):
        return None
    flat = settings.get(_FLAT_EXCLUDE_KEY)
    if isinstance(flat, list):
        return [str(item) for item in flat]
    nested = settings.get(_INTELEPHENSE_SERVER_NAME)
    if isinstance(nested, dict):
        direct = nested.get("files.exclude")
        if isinstance(direct, list):
            return [str(item) for item in direct]
        files = nested.get("files")
        if isinstance(files, dict):
            deep = files.get("exclude")
            if isinstance(deep, list):
                return [str(item) for item in deep]
    return None
