"""``pyrightconfig.json`` keeps the language server on the project's own code.

The file is the single source of truth for Python import resolution for both
the pyright CLI and the long-running language server Claude Code's LSP
integration spawns (``CLAUDE/development/LSP.md``). Without an ``exclude``
the server also analysed everything under ``untracked/``: every linked
worktree's half-built branch, the dummy-client fixture, canary clones, and
the venvs. Two sub-agents' in-progress files then surfaced as thousands of
"unknown attribute" and "unresolved import" diagnostics against THIS
checkout, drowning the real ones. Archived plan code and the deliberately
broken test fixtures are noise of the same kind, as is the ccy supervisor's
own ``plugins/`` runtime tree: vendored third-party Claude Code marketplace
plugin code (``hookify``, ``security-guidance``, ``skill-creator``, ...)
that ccy clones underneath ``.claude/ccy/``, never this project's code
(Plan 00368 Task 3.1).
"""

import json
from pathlib import Path

from claude_code_hooks_daemon.constants import ProjectPath
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / "pyrightconfig.json"

# Trees that are never this checkout's live code: linked worktrees, venvs,
# fixtures and canary clones (untracked/), the plan archive's historical
# probes and archived code, the acceptance-test fixture files, the test
# fixtures that are broken on purpose, the ccy supervisor's own vendored
# plugin-marketplace runtime tree (ProjectPath.CCY_PLUGINS_DIR), and the
# reviewed vendored/build names at any depth (the same set the
# lsp_noise_checker advisory derives its expectation from, so this repo's
# own config satisfies its own handler).
_REQUIRED_EXCLUDES = frozenset(
    {
        "untracked",
        "CLAUDE/Plan",
        "CLAUDE/AcceptanceTests/fixtures",
        "tests/fixtures",
        "remote-docs",
        ProjectPath.CCY_PLUGINS_DIR,
    }
    | {f"**/{name}" for name in CORE_VENDORED_BUILD_DIR_NAMES}
)


def _config() -> dict[str, object]:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))


class TestTheLanguageServerStaysOnProjectCode:
    def test_every_non_project_tree_is_excluded(self) -> None:
        exclude = _config().get("exclude")
        assert isinstance(exclude, list), "pyrightconfig.json has no `exclude` list"
        missing = sorted(_REQUIRED_EXCLUDES - set(exclude))
        assert not missing, (
            f"pyrightconfig.json must exclude {missing}: the language server otherwise "
            "analyses other checkouts' in-progress files and reports them against this one."
        )


class TestImportResolutionIsUnchanged:
    def test_the_venv_symlink_and_source_path_are_still_pinned(self) -> None:
        config = _config()
        assert config["venvPath"] == "untracked"
        assert config["venv"] == "venv"
        extra_paths = config["extraPaths"]
        assert isinstance(extra_paths, list)
        assert "src" in extra_paths
