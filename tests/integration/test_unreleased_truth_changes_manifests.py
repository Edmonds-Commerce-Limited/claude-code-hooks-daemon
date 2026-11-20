"""Every staged truth-changes manifest loads with the schema a release will load it with.

A file under ``CLAUDE/UPGRADES/UNRELEASED/truth-changes/`` is read by a branch
install's truth-change report and moved verbatim into the released directory
at release time. A malformed entry should fail here, on the branch that wrote
it, rather than in the report or the release.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.install.truth_changes import TruthChangeManifest

_UPGRADES = Path(__file__).resolve().parents[2] / "CLAUDE" / "UPGRADES"
_STAGING = _UPGRADES / "UNRELEASED" / "truth-changes"
_MANIFESTS = sorted(_STAGING.glob("v*.yaml"))


def test_staging_directory_exists() -> None:
    assert _STAGING.is_dir()


@pytest.mark.parametrize("manifest", _MANIFESTS, ids=[path.name for path in _MANIFESTS])
def test_staged_manifest_parses_and_names_its_own_version(manifest: Path) -> None:
    data: dict[str, Any] = yaml.safe_load(manifest.read_text(encoding="utf-8"))

    parsed = TruthChangeManifest.from_dict(data)

    assert f"v{parsed.version}.yaml" == manifest.name
