"""Manifest of daemon-owned assets deployed into CLIENT-owned directories.

Plan 00217. The daemon does not confine itself to ``.claude/hooks-daemon/``. It
also writes executable, lintable source into directories the client owns,
commits and runs their own quality gates over — the hook forwarders, the skill
scripts, ``mkplan.bash``, and the ccy PTY supervisor.

Why that matters, and why the vendor directory does not have this problem:

``.claude/hooks-daemon/`` is git-ignored by the installer, and ruff (like most
modern tooling) respects ``.gitignore``. So no client ever wrote a "vendor
exclusion" — git wrote it for them, as a side effect. Everything this manifest
lists is deliberately NOT ignored, because it must be committed to work
(``install/ccy_supervisor.py`` even whitelists the supervisor back out of the
ccy ignore so teammates receive it). That same act of un-ignoring is what puts
daemon-owned source into the client's tooling.

A client field report against v3.51.0 hit exactly this: three ruff findings in
``.claude/ccy/claude-supervise.py``, none of them a defect, none of them
fixable by the client (upgrades overwrite the file), none of them silenceable
(the daemon's own ``qa_suppression`` handler denies writing a directive), and
none of them covered by the exclusion anybody would think to write.

The list previously existed only implicitly, spread across four install
modules. There was therefore nothing to document, nothing to test, and nothing
to hand a client. This module is that list, and it exists to be consumed by
two things:

1. ``tests/integration/test_client_owned_asset_lint.py`` — the guard asserting
   each asset stays clean under its language's DEFAULT rule set. Upstream can
   promise default-clean; it cannot promise cleanliness under rules a client
   chooses, which is why the boundary document also ships the exclusion.
2. ``tests/unit/install/test_client_owned_assets.py`` — pins the manifest to
   real files and to the client-facing document.

Entries are declared with BOTH paths on purpose. ``source`` is where the
canonical file lives in this repository (what we lint and what we ship);
``deployed_to`` is where a client finds it (what they must be told about).
Conflating the two is how the list went missing in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

#: Client-project-relative prefix of the daemon's OWN vendor directory. Assets
#: under it are git-ignored and therefore already outside every default tool
#: scope — they must never appear in this manifest.
VENDOR_DIR: Final[str] = ".claude/hooks-daemon/"

#: Repo-relative path of the document that states the ownership boundary to
#: clients. Held here so the manifest and the prose cannot drift apart: a test
#: asserts every ``deployed_to`` below appears in it.
CLIENT_BOUNDARY_DOC: Final[str] = "CLAUDE/LLM-INSTALL.md"

#: Substring every deployed asset must carry, so the file itself answers "is
#: this mine?" at the moment someone opens it. Shell and Python both comment
#: with ``#``, so one banner serves every asset below. Asserted by
#: ``tests/unit/install/test_client_owned_assets.py``.
OWNERSHIP_MARKER: Final[str] = "DAEMON-OWNED FILE - do not edit"


class AssetLanguage(Enum):
    """Language of a deployed asset — selects which default linter applies.

    Only languages the guard can actually check belong here. A value the guard
    does not know how to lint would make that entry pass by omission, which is
    the failure mode this whole manifest exists to prevent.
    """

    SHELL = "shell"
    PYTHON = "python"
    # Markdown arrived with the first deployed AGENT DEFINITION (Plan 00216).
    # Added together with its check in the lint guard, never ahead of it: an
    # entry whose language the guard cannot lint passes by omission, which is
    # the exact failure this manifest exists to prevent.
    MARKDOWN = "markdown"


@dataclass(frozen=True)
class ClientOwnedAsset:
    """One daemon-owned artifact that lands in client-owned space.

    Attributes:
        source: Repo-relative glob for the canonical file(s) in this repository.
            This is what the lint guard checks and what the installer ships.
        deployed_to: Client-project-relative glob for the deployed copy. This is
            the path a client sees, excludes, and must be told about.
        language: Which default rule set the guard applies.
        deployed_by: The code that performs the deploy — ``install.py`` at the
            repo root, or a module name within this package. Keeps every entry
            traceable to the thing that would have to change.
        why: Why the asset cannot simply live inside the vendor directory.
    """

    source: str
    deployed_to: str
    language: AssetLanguage
    deployed_by: str
    why: str


CLIENT_OWNED_ASSETS: Final[tuple[ClientOwnedAsset, ...]] = (
    ClientOwnedAsset(
        source="init.sh",
        deployed_to=".claude/init.sh",
        language=AssetLanguage.SHELL,
        deployed_by="install.py",
        why=(
            "Sourced by every hook forwarder to resolve the socket and start the "
            "daemon; must sit beside them, outside the replaceable clone."
        ),
    ),
    ClientOwnedAsset(
        source=".claude/hooks/*",
        deployed_to=".claude/hooks/*",
        language=AssetLanguage.SHELL,
        deployed_by="install.py",
        why=(
            "Claude Code executes these by path from settings.json; the location "
            "is the contract, not a choice."
        ),
    ),
    ClientOwnedAsset(
        source="src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/*.sh",
        deployed_to=".claude/skills/hooks-daemon/scripts/*.sh",
        language=AssetLanguage.SHELL,
        deployed_by="skills",
        why=(
            "Claude Code discovers skills under .claude/skills/; a skill script "
            "inside the vendor clone would never be found."
        ),
    ),
    ClientOwnedAsset(
        source="src/claude_code_hooks_daemon/install/templates/mkplan.bash",
        deployed_to="CLAUDE/Plan/mkplan.bash",
        language=AssetLanguage.SHELL,
        deployed_by="plan_workflow",
        why=(
            "Scaffolds plans inside the project's plan directory and is invoked "
            "from it by CLAUDE.md guidance and the plan_number_helper handler."
        ),
    ),
    ClientOwnedAsset(
        source="src/claude_code_hooks_daemon/install/templates/hooks-daemon-plan-dedupe-scout.md",
        deployed_to=".claude/agents/hooks-daemon-plan-dedupe-scout.md",
        language=AssetLanguage.MARKDOWN,
        deployed_by="plan_workflow",
        why=(
            "Claude Code discovers sub-agents only under .claude/agents/, a flat "
            "directory the client owns and fills with its own agents; a definition "
            "inside the vendor clone would never be dispatchable. The name is "
            "prefixed so it cannot collide with a client's own agent, since a "
            "collision there silently drops one definition rather than erroring."
        ),
    ),
    ClientOwnedAsset(
        source=".claude/ccy/claude-supervise.py",
        deployed_to=".claude/ccy/claude-supervise.py",
        language=AssetLanguage.PYTHON,
        deployed_by="ccy_supervisor",
        why=(
            "exec'd by the ccy launcher from ccy.env's own directory inside a "
            "disposable container, and deliberately committed (Plan 00147/00148) "
            "so teammates receive a working supervisor. Both requirements put it "
            "outside the git-ignored clone."
        ),
    ),
)


def resolve_sources(repo_root: Path) -> list[tuple[ClientOwnedAsset, Path]]:
    """Expand every manifest entry's source glob against ``repo_root``.

    Args:
        repo_root: Root of this repository (where the canonical assets live).

    Returns:
        ``(asset, path)`` pairs for every existing file each entry matches,
        ordered by manifest order then path. Entries whose glob matches nothing
        contribute no pairs — the unit test fails that case loudly rather than
        letting the lint guard quietly check an empty set.
    """
    resolved: list[tuple[ClientOwnedAsset, Path]] = []
    for asset in CLIENT_OWNED_ASSETS:
        for path in sorted(repo_root.glob(asset.source)):
            if path.is_file():
                resolved.append((asset, path))
    return resolved
