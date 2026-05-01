"""Plan 00104 Task 5.1 — release-pipeline helper produces a valid manifest.

``scripts/release/build_bootstrap_checksums.sh`` is invoked by the release
pipeline (see ``CLAUDE/development/RELEASING.md`` Step 14) to produce the
``bootstrap-checksums.txt`` artifact that the skill ``upgrade.sh``
self-bootstrap stanza verifies against. If this helper produces an
inconsistent manifest, every user upgrading via the skill aborts —
turning a release-pipeline bug into a fleet-wide outage.

This test pins the manifest contract:

- output format is ``<sha256>  <basename>\\n`` (matches ``sha256sum``),
- the recorded sha matches an independent recomputation of the artifact,
- multiple artifacts produce one line each in the input order,
- missing artifacts cause non-zero exit and no output file is written
  (atomic write — never leave a half-built manifest behind),
- empty arg lists are rejected (no silent zero-line manifest).
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "release" / "build_bootstrap_checksums.sh"
BASH = shutil.which("bash") or "/bin/bash"


def _sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_helper_writes_sha256_manifest_for_single_artifact(tmp_path: Path) -> None:
    artifact = tmp_path / "upgrade.sh"
    artifact.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    expected_sha = _sha256_hex(artifact)

    output = tmp_path / "bootstrap-checksums.txt"
    result = subprocess.run(
        [BASH, str(HELPER), str(output), str(artifact)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"helper must succeed for a valid artifact.\n"
        f"returncode={result.returncode}\nstdout={result.stdout!r}\n"
        f"stderr={result.stderr!r}"
    )
    assert output.exists(), "manifest output file must be written"
    content = output.read_text(encoding="utf-8")
    assert content == f"{expected_sha}  upgrade.sh\n", (
        f"manifest format must be '<sha>  <basename>\\n' (matches sha256sum).\n" f"got: {content!r}"
    )


def test_helper_writes_one_line_per_artifact_in_order(tmp_path: Path) -> None:
    a = tmp_path / "upgrade.sh"
    a.write_text("a\n", encoding="utf-8")
    b = tmp_path / "install.sh"
    b.write_text("b\n", encoding="utf-8")

    output = tmp_path / "bootstrap-checksums.txt"
    result = subprocess.run(
        [BASH, str(HELPER), str(output), str(a), str(b)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"expected 2 lines, got {lines!r}"
    assert lines[0].endswith("  upgrade.sh"), lines[0]
    assert lines[1].endswith("  install.sh"), lines[1]
    assert lines[0].split("  ")[0] == _sha256_hex(a)
    assert lines[1].split("  ")[0] == _sha256_hex(b)


def test_helper_aborts_when_artifact_missing(tmp_path: Path) -> None:
    output = tmp_path / "bootstrap-checksums.txt"
    missing = tmp_path / "does-not-exist.sh"

    result = subprocess.run(
        [BASH, str(HELPER), str(output), str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, "helper must abort on missing artifact"
    assert (
        "not found" in result.stderr.lower()
    ), f"helper must explain why it aborted.\nstderr={result.stderr!r}"
    assert (
        not output.exists()
    ), "atomic write: half-built manifest must not be left behind on failure"


def test_helper_rejects_empty_argument_list(tmp_path: Path) -> None:
    output = tmp_path / "bootstrap-checksums.txt"
    result = subprocess.run(
        [BASH, str(HELPER), str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, "helper must refuse to build empty manifest"
    assert not output.exists(), "no artifacts → no output file"
