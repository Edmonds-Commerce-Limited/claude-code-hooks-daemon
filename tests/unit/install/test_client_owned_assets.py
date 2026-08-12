"""The manifest of daemon-owned assets deployed into CLIENT-owned directories.

Plan 00217. A client field report found linter output coming from
``.claude/ccy/claude-supervise.py`` — 3,100 lines of daemon-owned source that
the installer deploys into a directory the client owns, commits, and lints.
The client could not fix it (upgrades overwrite it), could not silence it (the
daemon's own ``qa_suppression`` handler denies writing a directive), and would
not think to exclude it (the conventional exclusion is
``.claude/hooks-daemon/``).

The instance is one file. The *class* is that the daemon deploys several
artifacts outside its own vendor directory and the list existed only implicitly,
spread across four install modules — so there was nothing to document, nothing
to test, and nothing to hand a client. This manifest is that missing list.

These tests pin the manifest to reality: every entry must name a file that
actually exists, must deploy OUTSIDE the vendor directory (inside it needs no
declaration — git-ignoring it already excludes it from every tool), and must be
enumerated in the client-facing document.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.install.client_owned_assets import (
    CLIENT_BOUNDARY_DOC,
    CLIENT_OWNED_ASSETS,
    OWNERSHIP_MARKER,
    VENDOR_DIR,
    AssetLanguage,
    ClientOwnedAsset,
    resolve_sources,
)

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

# The file whose field report started Plan 00217. Named explicitly so a manifest
# that drops it fails by name rather than by a silent count change.
_SUPERVISOR_DEPLOY_PATH: Final[str] = ".claude/ccy/claude-supervise.py"

_INSTALL_PACKAGE: Final[str] = "claude_code_hooks_daemon.install"
# Deployers that are not modules of the install package.
_NON_PACKAGE_DEPLOYERS: Final[frozenset[str]] = frozenset({"install.py"})


class TestManifestDescribesRealFiles:
    """A manifest that names files which do not exist documents nothing."""

    def test_manifest_is_not_empty(self) -> None:
        """Control: every other assertion here is vacuous on an empty tuple."""
        assert CLIENT_OWNED_ASSETS, (
            "CLIENT_OWNED_ASSETS is empty. The daemon demonstrably deploys "
            "code outside .claude/hooks-daemon/ (init.sh, the hook forwarders, "
            "the skill scripts); an empty manifest means the list went missing, "
            "not that the problem did."
        )

    def test_every_source_glob_resolves(self) -> None:
        """Each entry points at real, tracked source in this repository."""
        for asset, matches in _sources_by_asset().items():
            assert matches, (
                f"{asset.source!r} (deployed to {asset.deployed_to!r} by "
                f"{asset.deployed_by}) matches no file in this repository. "
                f"Either the asset moved and the manifest was not updated, or "
                f"the glob is wrong — both leave the guard checking nothing."
            )

    def test_resolve_sources_returns_existing_paths(self) -> None:
        """The public resolver hands callers paths they can actually read."""
        resolved = resolve_sources(_REPO_ROOT)
        assert resolved, "resolve_sources() found nothing under the repo root."
        for _asset, path in resolved:
            assert path.is_file(), f"resolve_sources() returned a non-file: {path}"


class TestManifestScopeIsTheClientOwnedSurface:
    """Only assets OUTSIDE the vendor directory belong here."""

    def test_no_asset_deploys_inside_the_vendor_directory(self) -> None:
        """Vendor-dir assets need no declaration — .gitignore already excludes them.

        The installer git-ignores ``.claude/hooks-daemon/``, and ruff (like most
        modern tooling) respects .gitignore, so nothing in there reaches a
        client's linter. Listing such an asset here would imply a boundary
        problem that does not exist and dilute the ones that do.
        """
        offenders = [
            a.deployed_to for a in CLIENT_OWNED_ASSETS if a.deployed_to.startswith(VENDOR_DIR)
        ]
        assert not offenders, (
            f"These entries deploy inside {VENDOR_DIR}, which is git-ignored and "
            f"therefore already outside every client tool's default scope: "
            f"{offenders}"
        )

    def test_the_reported_supervisor_is_listed(self) -> None:
        """The instance that prompted the plan must be in the class it belongs to."""
        deployed = {asset.deployed_to for asset in CLIENT_OWNED_ASSETS}
        assert _SUPERVISOR_DEPLOY_PATH in deployed, (
            f"{_SUPERVISOR_DEPLOY_PATH} is absent from the manifest. It is the "
            f"file the Plan 00217 field report was written about; a manifest "
            f"without it cannot be the fix for that report."
        )

    def test_every_language_is_one_we_can_actually_check(self) -> None:
        """A language the guard cannot lint is an entry the guard silently skips."""
        for asset in CLIENT_OWNED_ASSETS:
            assert isinstance(asset.language, AssetLanguage), (
                f"{asset.deployed_to} declares language {asset.language!r}, which "
                f"is not an AssetLanguage member — the lint guard would not know "
                f"which default rule set applies and would pass by omission."
            )

    def test_every_deployer_exists(self) -> None:
        """``deployed_by`` must name real code, so the manifest is traceable."""
        for asset in CLIENT_OWNED_ASSETS:
            if asset.deployed_by in _NON_PACKAGE_DEPLOYERS:
                assert (_REPO_ROOT / asset.deployed_by).is_file()
                continue
            module_name = f"{_INSTALL_PACKAGE}.{asset.deployed_by}"
            try:
                importlib.import_module(module_name)
            except ImportError as exc:  # pragma: no cover - failure path is the message
                pytest.fail(
                    f"{asset.deployed_to} claims to be deployed by {module_name}, "
                    f"which does not import: {exc}"
                )

    def test_entries_are_unique_by_deployed_path(self) -> None:
        """Two entries for one path make 'which rule applies?' ambiguous."""
        deployed = [asset.deployed_to for asset in CLIENT_OWNED_ASSETS]
        duplicates = {path for path in deployed if deployed.count(path) > 1}
        assert not duplicates, f"Duplicate manifest entries for: {sorted(duplicates)}"


class TestBoundaryIsDocumentedWhereAClientReadsIt:
    """A client should never have to infer which files under .claude/ are theirs."""

    def test_the_boundary_document_exists(self) -> None:
        """The manifest names a document; that document must be real."""
        assert (_REPO_ROOT / CLIENT_BOUNDARY_DOC).is_file(), (
            f"{CLIENT_BOUNDARY_DOC} does not exist, so the manifest points at "
            f"nothing a client can read."
        )

    def test_every_deployed_path_is_enumerated_in_the_document(self) -> None:
        """The list a client reads and the list the code deploys are the same list."""
        text = (_REPO_ROOT / CLIENT_BOUNDARY_DOC).read_text(encoding="utf-8")
        undocumented = [a.deployed_to for a in CLIENT_OWNED_ASSETS if a.deployed_to not in text]
        assert not undocumented, (
            f"{CLIENT_BOUNDARY_DOC} does not mention {undocumented}. A "
            f"daemon-owned path that is deployed but undocumented is exactly the "
            f"Plan 00217 defect: the client cannot tell whose file it is, and "
            f"cannot exclude what they have not been told about."
        )


class TestEveryDeployedAssetDeclaresItsOwnership:
    """The file itself must answer "is this mine?" — not only the central table.

    A client meets these files one at a time, usually because a tool pointed at
    one. The Plan 00217 reporter opened 3,100 lines of PTY-supervisor source
    whose first 59 lines discuss pseudo-terminals and thread safety, and nothing
    in it said "this is not yours and your edit will be discarded". A table in a
    document they were not reading at the time cannot answer that; a banner in
    the file can, and it travels with the file on every deploy.
    """

    def test_marker_is_specific_enough_to_assert_on(self) -> None:
        """A marker that could occur by accident would make the check meaningless."""
        assert len(OWNERSHIP_MARKER) > len("DO NOT EDIT"), (
            "OWNERSHIP_MARKER is too generic to distinguish a daemon-owned "
            "banner from incidental prose."
        )

    def test_every_deployed_asset_carries_the_marker(self) -> None:
        """Shell and Python both comment with '#', so one banner serves all five."""
        missing = [
            str(path.relative_to(_REPO_ROOT))
            for _asset, path in resolve_sources(_REPO_ROOT)
            if OWNERSHIP_MARKER not in path.read_text(encoding="utf-8", errors="replace")
        ]
        assert not missing, (
            f"These daemon-owned files are deployed into client-owned "
            f"directories without declaring it: {missing}. Add the ownership "
            f"banner containing {OWNERSHIP_MARKER!r}. For the hook forwarders "
            f"the banner belongs in install.py's generator, then regenerate "
            f"this repo's own .claude/hooks/ so the dogfooding comparison "
            f"still matches."
        )


def _sources_by_asset() -> dict[ClientOwnedAsset, list[Path]]:
    """Map each manifest entry to the repository files its source glob matches."""
    return {asset: sorted(_REPO_ROOT.glob(asset.source)) for asset in CLIENT_OWNED_ASSETS}
