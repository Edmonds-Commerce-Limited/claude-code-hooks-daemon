"""Plan 00362 Task 1.1 — the release pipeline attaches the bootstrap assets.

The v3.62.1 GitHub release shipped with NO assets. Every skill wrapper
(``daemon-cli.sh``, ``health-check.sh``, ``init-handlers.sh``) self-bootstraps
by downloading ``bootstrap-checksums.txt`` from ``releases/latest/download/``,
so a release without the manifest broke every wrapper on every client
install. The manifest recipe existed only as a prose loop in
``CLAUDE/development/RELEASING.md`` Step 14, while the procedure the release
actually follows (``.claude/skills/release/invoke.sh`` Stage 4 and
``.claude/agents/release-agent.md`` Stage 3) ran ``gh release create`` with no
artifacts at all.

``scripts/release/publish_bootstrap_assets.sh`` is the one step that builds
and uploads the bundle. These tests pin:

- the manifest covers EVERY skill script carrying a self-bootstrap stanza
  (found by scanning the skill scripts dir, not a hard-coded list), plus
  ``upgrade.sh`` for cross-symmetry;
- two builds from the same tree are byte-identical (deterministic order);
- ``--build-only`` never touches ``gh``;
- the upload step calls ``gh release upload <tag> --clobber`` with every
  artifact, and refuses to run without a tag;
- every release procedure document names the script, so no procedure can
  again omit the assets.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH = REPO_ROOT / "scripts" / "release" / "publish_bootstrap_assets.sh"
SKILL_SCRIPTS = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts"
)
BASH = shutil.which("bash") or "/bin/bash"
_STANZA_MARKER = "# === SELF-BOOTSTRAP BEGIN"

RELEASE_PROCEDURE_DOCS = [
    REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md",
    REPO_ROOT / ".claude" / "skills" / "release" / "invoke.sh",
    REPO_ROOT / ".claude" / "agents" / "release-agent.md",
]


def _self_bootstrapping_scripts() -> list[str]:
    names = [
        p.name
        for p in sorted(SKILL_SCRIPTS.glob("*.sh"))
        if _STANZA_MARKER in p.read_text(encoding="utf-8")
    ]
    assert names, f"no self-bootstrapping scripts found under {SKILL_SCRIPTS}"
    return names


def _manifest_entries(manifest: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        sha, name = line.split("  ", 1)
        entries[name] = sha
    return entries


def _run_publish(
    args: list[str], *, artifacts_dir: Path, gh_bin: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR"] = str(artifacts_dir)
    if gh_bin is not None:
        env["HOOKS_DAEMON_GH_BIN"] = str(gh_bin)
    return subprocess.run(
        [BASH, str(PUBLISH), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        cwd=str(REPO_ROOT),
    )


def _fake_gh(tmp_path: Path) -> tuple[Path, Path]:
    """A ``gh`` stand-in that records its argv and reports every asset as uploaded."""
    log = tmp_path / "gh-calls.log"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        f"printf '%s\\n' \"$*\" >> '{log}'\n"
        'if [ "$1" = "release" ] && [ "$2" = "view" ]; then\n'
        "    for f in upgrade.sh daemon-cli.sh health-check.sh init-handlers.sh bootstrap-checksums.txt; do\n"
        '        echo "$f"\n'
        "    done\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    return gh, log


class TestBuild:
    def test_build_only_covers_every_self_bootstrapping_script(self, tmp_path: Path) -> None:
        artifacts = tmp_path / "artifacts"
        result = _run_publish(["v0.0.0-test", "--build-only"], artifacts_dir=artifacts)
        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"

        manifest = artifacts / "bootstrap-checksums.txt"
        assert manifest.is_file(), "the manifest must be written to the artifacts dir"
        entries = _manifest_entries(manifest)
        for name in _self_bootstrapping_scripts():
            assert name in entries, (
                f"{name} carries a self-bootstrap stanza but has no manifest entry — "
                f"every client running it would abort with 'no entry for {name}'"
            )
            copied = artifacts / name
            assert copied.is_file(), f"{name} must be staged next to the manifest"
            assert entries[name] == hashlib.sha256(copied.read_bytes()).hexdigest()
            assert copied.read_bytes() == (SKILL_SCRIPTS / name).read_bytes(), (
                f"staged {name} must be the exact bytes shipped in the skill tree"
            )
        assert "upgrade.sh" in entries, "upgrade.sh is bundled for cross-symmetry"

    def test_build_is_deterministic(self, tmp_path: Path) -> None:
        first = tmp_path / "a"
        second = tmp_path / "b"
        assert _run_publish(["v0.0.0-test", "--build-only"], artifacts_dir=first).returncode == 0
        assert _run_publish(["v0.0.0-test", "--build-only"], artifacts_dir=second).returncode == 0
        assert (first / "bootstrap-checksums.txt").read_bytes() == (
            second / "bootstrap-checksums.txt"
        ).read_bytes()

    def test_build_only_never_calls_gh(self, tmp_path: Path) -> None:
        gh, log = _fake_gh(tmp_path)
        result = _run_publish(
            ["v0.0.0-test", "--build-only"], artifacts_dir=tmp_path / "artifacts", gh_bin=gh
        )
        assert result.returncode == 0, result.stderr
        assert not log.exists(), f"--build-only must not touch gh; calls={log.read_text()!r}"

    def test_skill_scripts_dir_override_bundles_tag_exact_bytes(self, tmp_path: Path) -> None:
        """Attaching assets to an ALREADY published release (v3.62.1) must ship
        the bytes of that tag, not of main HEAD — the override points the
        bundle at a checkout of the tag."""
        tag_checkout = tmp_path / "tag-checkout"
        tag_checkout.mkdir()
        for name in ("upgrade.sh", "daemon-cli.sh", "health-check.sh", "init-handlers.sh"):
            (tag_checkout / name).write_text(
                f"#!/bin/bash\necho {name} from tag\n", encoding="utf-8"
            )

        artifacts = tmp_path / "artifacts"
        env = os.environ.copy()
        env["HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR"] = str(artifacts)
        env["HOOKS_DAEMON_SKILL_SCRIPTS_DIR"] = str(tag_checkout)
        result = subprocess.run(
            [BASH, str(PUBLISH), "v0.0.0-test", "--build-only"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        entries = _manifest_entries(artifacts / "bootstrap-checksums.txt")
        for name in ("daemon-cli.sh", "health-check.sh", "init-handlers.sh"):
            expected = hashlib.sha256((tag_checkout / name).read_bytes()).hexdigest()
            assert entries[name] == expected, f"{name} must be hashed from the override dir"
            assert (artifacts / name).read_bytes() == (tag_checkout / name).read_bytes()

    def test_missing_skill_scripts_dir_fails(self, tmp_path: Path) -> None:
        env = os.environ.copy()
        env["HOOKS_DAEMON_RELEASE_ARTIFACTS_DIR"] = str(tmp_path / "artifacts")
        env["HOOKS_DAEMON_SKILL_SCRIPTS_DIR"] = str(tmp_path / "nowhere")
        result = subprocess.run(
            [BASH, str(PUBLISH), "v0.0.0-test", "--build-only"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode != 0
        assert "nowhere" in result.stderr


class TestUpload:
    def test_upload_attaches_every_artifact_with_clobber(self, tmp_path: Path) -> None:
        gh, log = _fake_gh(tmp_path)
        artifacts = tmp_path / "artifacts"
        result = _run_publish(["v9.9.9"], artifacts_dir=artifacts, gh_bin=gh)
        assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"

        calls = log.read_text(encoding="utf-8").splitlines()
        uploads = [c for c in calls if c.startswith("release upload v9.9.9 ")]
        assert len(uploads) == 1, f"expected exactly one upload call, got {calls!r}"
        upload = uploads[0]
        assert "--clobber" in upload, (
            "re-running the step must replace, not fail on, existing assets"
        )
        for name in [*_self_bootstrapping_scripts(), "upgrade.sh", "bootstrap-checksums.txt"]:
            assert str(artifacts / name) in upload, f"{name} missing from upload: {upload!r}"
        assert any(c.startswith("release view v9.9.9") for c in calls), (
            "the step must verify the assets landed by reading the release back"
        )

    def test_upload_fails_when_release_read_back_lacks_an_asset(self, tmp_path: Path) -> None:
        log = tmp_path / "gh-calls.log"
        gh = tmp_path / "gh"
        gh.write_text(
            "#!/bin/bash\n"
            f"printf '%s\\n' \"$*\" >> '{log}'\n"
            'if [ "$1" = "release" ] && [ "$2" = "view" ]; then echo upgrade.sh; fi\n'
            "exit 0\n",
            encoding="utf-8",
        )
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        result = _run_publish(["v9.9.9"], artifacts_dir=tmp_path / "artifacts", gh_bin=gh)
        assert result.returncode != 0, (
            "a release still missing an asset after upload must fail the step"
        )
        assert "bootstrap-checksums.txt" in result.stderr

    def test_refuses_to_run_without_a_tag(self, tmp_path: Path) -> None:
        gh, log = _fake_gh(tmp_path)
        result = _run_publish([], artifacts_dir=tmp_path / "artifacts", gh_bin=gh)
        assert result.returncode != 0
        assert "usage" in result.stderr.lower()
        assert not log.exists()

    def test_rejects_a_tag_without_v_prefix(self, tmp_path: Path) -> None:
        gh, log = _fake_gh(tmp_path)
        result = _run_publish(["3.62.1"], artifacts_dir=tmp_path / "artifacts", gh_bin=gh)
        assert result.returncode != 0
        assert "v3.62.1" in result.stderr, "the error must show the accepted form"
        assert not log.exists()


class TestPipelineNamesTheStep:
    @pytest.mark.parametrize("doc", RELEASE_PROCEDURE_DOCS, ids=lambda p: p.name)
    def test_release_procedure_invokes_publish_step(self, doc: Path) -> None:
        text = doc.read_text(encoding="utf-8")
        assert "scripts/release/publish_bootstrap_assets.sh" in text, (
            f"{doc.relative_to(REPO_ROOT)} is a release procedure and must invoke "
            f"scripts/release/publish_bootstrap_assets.sh — v3.62.1 shipped without "
            f"assets because the followed procedure omitted the step"
        )

    @pytest.mark.parametrize("doc", RELEASE_PROCEDURE_DOCS, ids=lambda p: p.name)
    def test_publish_step_follows_release_create(self, doc: Path) -> None:
        text = doc.read_text(encoding="utf-8")
        create = text.find("gh release create vX.Y.Z")
        publish = text.find("scripts/release/publish_bootstrap_assets.sh vX.Y.Z")
        assert create != -1, f"{doc.name} must show the gh release create step"
        assert publish != -1, f"{doc.name} must show publish_bootstrap_assets.sh vX.Y.Z"
        assert publish > create, (
            f"{doc.name}: the assets are uploaded to an existing release, so the "
            f"publish step must come after gh release create"
        )
