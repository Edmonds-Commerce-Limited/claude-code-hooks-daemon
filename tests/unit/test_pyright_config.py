"""``pyrightconfig.json`` keeps the language server on the project's own code.

The file is the single source of truth for Python import resolution for both
the pyright CLI and the long-running language server Claude Code's LSP
integration spawns (``CLAUDE/development/LSP.md``). Without an ``exclude``
the server also analysed everything under ``untracked/``: every linked
worktree's half-built branch, the dummy-client fixture, canary clones, and
the venvs. Two sub-agents' in-progress files then surfaced as thousands of
"unknown attribute" and "unresolved import" diagnostics against THIS
checkout, drowning the real ones. Archived plan code and the deliberately
broken test fixtures are noise of the same kind.
"""

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = _REPO_ROOT / "pyrightconfig.json"

# Trees that are never this checkout's live code: linked worktrees, venvs,
# fixtures and canary clones (untracked/), the plan archive's historical
# probes and archived code, the acceptance-test fixture files, and the test
# fixtures that are broken on purpose.
_REQUIRED_EXCLUDES = frozenset(
    {
        "untracked",
        "CLAUDE/Plan",
        "CLAUDE/AcceptanceTests/fixtures",
        "tests/fixtures",
        "remote-docs",
    }
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
