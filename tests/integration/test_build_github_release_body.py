"""N262 - the GitHub release body must fit GitHub's release-body cap.

``RELEASES/vX.Y.Z.md`` folds every holding-area callout in verbatim, and the
v3.67.0 notes were 126,003 bytes: ``gh release create --notes-file`` failed
with HTTP 422 (maximum 125,000 characters) AFTER the tag was pushed.
``scripts/release/build_github_release_body.py`` turns the notes into the body
GitHub receives, and every release procedure runs it BEFORE the tag exists.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "release" / "build_github_release_body.py"
TAG = "v9.9.9"

RELEASE_PROCEDURE_DOCS = [
    REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md",
    REPO_ROOT / ".claude" / "skills" / "release" / "invoke.sh",
    REPO_ROOT / ".claude" / "agents" / "release-agent.md",
]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_github_release_body", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _notes(callout_count: int, callout_size: int) -> str:
    callouts = "".join(
        f"#### Callout {i}\n\n{'x' * callout_size}\n\n" for i in range(callout_count)
    )
    return (
        f"# Release {TAG}\n\n## Summary\n\nshort summary\n\n"
        f"## Highlights\n\n{callouts}"
        "## Changes\n\n- a change\n\n## Installation\n\ninstall it\n"
    )


@pytest.fixture(name="mod")
def _mod() -> ModuleType:
    return _load()


class TestBuildBody:
    def test_limit_is_the_named_github_cap(self, mod: ModuleType) -> None:
        assert mod.GITHUB_BODY_LIMIT == 125_000

    def test_under_cap_passes_through_byte_identical(self, mod: ModuleType) -> None:
        text = _notes(3, 100)
        assert mod.build_github_body(text, TAG) == text

    def test_over_cap_replaces_highlights_only(self, mod: ModuleType) -> None:
        text = _notes(20, 7_000)
        assert len(text) > mod.GITHUB_BODY_LIMIT
        body = mod.build_github_body(text, TAG)
        assert len(body) < mod.GITHUB_BODY_LIMIT
        assert "#### Callout" not in body
        assert f"RELEASES/{TAG}.md" in body
        assert "20 per-change notes" in body
        for section in ("# Release v9.9.9", "## Summary", "## Changes", "## Installation"):
            assert section in body
        assert "short summary" in body and "- a change" in body and "install it" in body

    def test_still_over_cap_after_substitution_fails_loudly(self, mod: ModuleType) -> None:
        text = _notes(1, 10).replace(
            "## Installation", "## Installation\n\n" + "y" * mod.GITHUB_BODY_LIMIT
        )
        with pytest.raises(ValueError, match="still over"):
            mod.build_github_body(text, TAG)

    def test_over_cap_without_highlights_fails_loudly(self, mod: ModuleType) -> None:
        text = "## Summary\n\n" + "z" * mod.GITHUB_BODY_LIMIT
        with pytest.raises(ValueError, match="Highlights"):
            mod.build_github_body(text, TAG)

    def test_highlights_as_last_section_is_replaced(self, mod: ModuleType) -> None:
        text = "## Summary\n\ns\n\n## Highlights\n\n" + "h" * mod.GITHUB_BODY_LIMIT
        body = mod.build_github_body(text, TAG)
        assert body.startswith("## Summary")
        assert "## Highlights" in body and len(body) < mod.GITHUB_BODY_LIMIT

    def test_real_v3_67_0_notes_fit_after_substitution(self, mod: ModuleType) -> None:
        source = (REPO_ROOT / "RELEASES" / "v3.67.0.md").read_text(encoding="utf-8")
        assert len(source) > mod.GITHUB_BODY_LIMIT
        body = mod.build_github_body(source, "v3.67.0")
        assert len(body) < mod.GITHUB_BODY_LIMIT
        assert "## Changes" in body and "## Post-Upgrade Tasks" in body


class TestCli:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_writes_body_and_exits_zero(self, tmp_path: Path) -> None:
        notes = tmp_path / "notes.md"
        notes.write_text(_notes(2, 50), encoding="utf-8")
        out = tmp_path / "sub" / "body.md"
        result = self._run(TAG, "--notes-file", str(notes), "--output", str(out))
        assert result.returncode == 0, result.stderr
        assert out.read_text(encoding="utf-8") == notes.read_text(encoding="utf-8")
        assert str(out) in result.stdout

    def test_pathological_notes_exit_nonzero_and_write_nothing(self, tmp_path: Path) -> None:
        notes = tmp_path / "notes.md"
        notes.write_text("## Summary\n\n" + "z" * 130_000, encoding="utf-8")
        out = tmp_path / "body.md"
        result = self._run(TAG, "--notes-file", str(notes), "--output", str(out))
        assert result.returncode != 0
        assert "Highlights" in result.stderr
        assert not out.exists()

    def test_missing_notes_file_exits_nonzero(self, tmp_path: Path) -> None:
        result = self._run(
            TAG, "--notes-file", str(tmp_path / "nope.md"), "--output", str(tmp_path / "o.md")
        )
        assert result.returncode != 0
        assert "nope.md" in result.stderr


class TestProceduresUseTheBody:
    @pytest.mark.parametrize("doc", RELEASE_PROCEDURE_DOCS, ids=lambda p: p.name)
    def test_body_is_built_before_the_tag(self, doc: Path) -> None:
        text = doc.read_text(encoding="utf-8")
        build = text.find("scripts/release/build_github_release_body.py vX.Y.Z")
        tag = text.find("git tag -a vX.Y.Z -m")
        assert build != -1, f"{doc.name} must run build_github_release_body.py vX.Y.Z"
        assert tag != -1, f"{doc.name} must show the git tag step"
        assert build < tag, f"{doc.name}: the body check must run BEFORE the tag is created"

    @pytest.mark.parametrize("doc", RELEASE_PROCEDURE_DOCS, ids=lambda p: p.name)
    def test_release_create_uses_the_built_body(self, doc: Path) -> None:
        text = doc.read_text(encoding="utf-8")
        assert "--notes-file RELEASES/vX.Y.Z.md" not in text
        assert "--notes-file untracked/release-artifacts/github-release-body.md" in text
