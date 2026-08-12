r"""Plan 00109 Phase 1.2 — failing acceptance gate for UPGRADE_METADATA emission.

Every successful run of ``scripts/upgrade.sh`` (Layer 1) MUST end by
printing a sentinel-wrapped ``UPGRADE_METADATA`` block to stdout. The
block is the contract between the upgrade script and the project agent
that follows up with an atomic ``hooks daemon upgrade`` commit.

Contract (Plan 00109 Decision 2):

  <<<UPGRADE_METADATA
  from_version=vX.Y.Z
  to_version=vA.B.C
  python_version=3.13.0
  python_path=/.../venv-pyMM-XXXX/bin/python
  venv_path=/.../venv-pyMM-XXXX
  host=<hostname>
  daemon_dir=/.../.claude/hooks-daemon
  project_root=/...
  modified_files=relpath1,relpath2,...
  config_diff_summary=no config changes | N keys changed: ...
  UPGRADE_METADATA>>>

Every field MUST be present and non-empty. The block MUST appear on the
upgrade script's stdout (NOT stderr — the agent parses stdout). The
sentinels are unique strings so the block can be located reliably even
if surrounded by other progress output.

This test is RED until Plan 00109 Phase 1.3 implements emission in
``scripts/upgrade.sh``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.acceptance.conftest import assert_clone_is_pinned, create_daemon_clone

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_VERSION_SH = REPO_ROOT / "scripts" / "install_version.sh"
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
BASH = shutil.which("bash") or "/bin/bash"

_TEST_HOSTNAME_PREFIX = "hooks-daemon-test-meta-"
_INSTALL_TIMEOUT_SECONDS = 180
_UPGRADE_TIMEOUT_SECONDS = 180

_REQUIRED_METADATA_FIELDS = (
    "from_version",
    "to_version",
    "python_version",
    "python_path",
    "venv_path",
    "host",
    "daemon_dir",
    "project_root",
    "modified_files",
    "config_diff_summary",
)

_OPEN_SENTINEL = "<<<UPGRADE_METADATA"
_CLOSE_SENTINEL = "UPGRADE_METADATA>>>"


def _make_test_hostname() -> str:
    return f"{_TEST_HOSTNAME_PREFIX}{os.getpid()}-{int(time.time())}"


def _remove_daemon_clone(clone_path: Path) -> None:
    if not clone_path.exists():
        return
    shutil.rmtree(clone_path, ignore_errors=True)


def _stop_test_daemon(venv_python: Path, project_root: Path, env: dict[str, str]) -> None:
    if not venv_python.is_file():
        return
    subprocess.run(
        [str(venv_python), "-m", "claude_code_hooks_daemon.daemon.cli", "stop"],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=Timeout.DAEMON_SHUTDOWN,
        env=env,
    )


def _extract_metadata_block(stdout: str) -> dict[str, str]:
    """Locate the sentinel-wrapped block and parse key=value lines.

    Returns the parsed dict, or an empty dict if the block is missing.
    Multi-value fields are returned as raw strings; callers may
    post-process if needed.
    """
    pattern = re.compile(
        re.escape(_OPEN_SENTINEL) + r"\n(.*?)\n" + re.escape(_CLOSE_SENTINEL),
        re.DOTALL,
    )
    match = pattern.search(stdout)
    if not match:
        return {}
    body = match.group(1)
    parsed: dict[str, str] = {}
    for line in body.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


@pytest.mark.slow
def test_layer1_upgrade_sh_emits_metadata_block(tmp_path: Path) -> None:
    """Layer 1 ``scripts/upgrade.sh`` must emit UPGRADE_METADATA on success.

    Sets up the same fixture as the H-1 install gate, installs the daemon,
    then runs Layer 1 upgrade.sh with the daemon dir's current tag as
    ``TARGET_VERSION`` (idempotent — exercises the metadata-emission code
    path without requiring a network fetch or a real tag change).
    """
    if not INSTALL_VERSION_SH.is_file():
        pytest.skip(f"install_version.sh missing at {INSTALL_VERSION_SH}")
    if not LAYER1_UPGRADE_SH.is_file():
        pytest.skip(f"Layer 1 upgrade.sh missing at {LAYER1_UPGRADE_SH}")
    if shutil.which("uv") is None:
        pytest.skip("uv not installed in this environment")

    project_root = tmp_path / "fresh-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/fake.git"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    daemon_dir = project_root / ".claude" / "hooks-daemon"
    # Pinned to its newest tag BEFORE installing, so the baseline is stamped
    # with the version this test then upgrades to. See conftest's docstring.
    target_tag = create_daemon_clone(daemon_dir)
    venv_python: Path | None = None
    env = os.environ.copy()

    try:
        env["HOSTNAME"] = _make_test_hostname()
        env.pop("CI", None)
        env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
        env["NO_COLOR"] = "1"

        # Step A: install baseline (mirrors H-1 install gate).
        install_result = subprocess.run(
            [BASH, str(INSTALL_VERSION_SH), str(project_root), str(daemon_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            cwd=project_root,
        )
        if install_result.returncode != 0:
            pytest.fail(
                "Pre-upgrade install must exit 0 to set up the fixture.\n"
                f"returncode={install_result.returncode}\n"
                f"stdout:\n{install_result.stdout}\n"
                f"stderr:\n{install_result.stderr}"
            )

        venv_candidates = sorted((daemon_dir / "untracked").glob("venv-*py3*"))
        assert venv_candidates, (
            f"Install must produce a fingerprint-keyed venv under " f"{daemon_dir}/untracked/."
        )
        venv_python = venv_candidates[0] / "bin" / "python"
        assert venv_python.is_file(), f"venv Python must exist: {venv_python}"

        # The upgrade below must be IDEMPOTENT — that is the premise the
        # metadata assertion rests on. Re-check it now, so a drift fails here
        # by name rather than as an opaque uv error inside a subprocess.
        assert_clone_is_pinned(daemon_dir, target_tag)

        # Step B: invoke Layer 1 upgrade.sh.
        #
        # HOOKS_DAEMON_PYTHON is needed because Layer 1's
        # find_compatible_python may not be able to locate a versioned
        # interpreter when the test env's PATH differs from production.
        # Pointing it at the venv's own python satisfies the >=3.11 floor
        # and the requires-python cross-check.
        env["HOOKS_DAEMON_PYTHON"] = str(venv_python)
        upgrade_result = subprocess.run(
            [
                BASH,
                str(LAYER1_UPGRADE_SH),
                "--project-root",
                str(project_root),
                target_tag,
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_UPGRADE_TIMEOUT_SECONDS,
            cwd=project_root,
        )

        # Assertion (a): Layer 1 exited 0.
        if upgrade_result.returncode != 0:
            pytest.fail(
                "Layer 1 upgrade.sh must exit 0 against an idempotent target tag.\n"
                f"returncode={upgrade_result.returncode}\n"
                f"--- stdout ---\n{upgrade_result.stdout}\n"
                f"--- stderr ---\n{upgrade_result.stderr}"
            )

        # Assertion (b): UPGRADE_METADATA block present on stdout.
        # The block lives on stdout (not stderr) so the project agent
        # parses it via `bash upgrade.sh | ...` style capture.
        assert _OPEN_SENTINEL in upgrade_result.stdout, (
            f"Layer 1 upgrade.sh must emit '{_OPEN_SENTINEL}' sentinel on stdout. "
            f"Plan 00109 Phase 1.3 implements this — this assertion stays RED "
            f"until then.\n"
            f"--- stdout (last 2000 chars) ---\n{upgrade_result.stdout[-2000:]}"
        )
        assert _CLOSE_SENTINEL in upgrade_result.stdout, (
            f"Layer 1 upgrade.sh must emit '{_CLOSE_SENTINEL}' closing sentinel. "
            f"--- stdout (last 2000 chars) ---\n{upgrade_result.stdout[-2000:]}"
        )

        # Assertion (c): every required field is present and non-empty.
        metadata = _extract_metadata_block(upgrade_result.stdout)
        missing = [f for f in _REQUIRED_METADATA_FIELDS if f not in metadata]
        assert not missing, (
            f"UPGRADE_METADATA block missing required fields: {missing}.\n"
            f"Parsed metadata: {metadata}\n"
            f"--- stdout (last 2000 chars) ---\n{upgrade_result.stdout[-2000:]}"
        )
        empty = [f for f in _REQUIRED_METADATA_FIELDS if not metadata.get(f, "").strip()]
        # config_diff_summary and modified_files MAY be empty in an
        # idempotent upgrade (no version change, no config change). The
        # contract is that the KEY is present, not that the value is
        # non-empty — those two fields are the only exceptions.
        empty_strict = [f for f in empty if f not in ("config_diff_summary", "modified_files")]
        assert not empty_strict, (
            f"UPGRADE_METADATA block has empty values for non-optional fields: "
            f"{empty_strict}.\nParsed metadata: {metadata}"
        )

        # Assertion (d): version fields look like vX.Y.Z (or vX.Y.Z-SUFFIX).
        # Catches obviously-broken capture (empty string, "HEAD", raw SHA).
        version_pattern = re.compile(r"^v\d+\.\d+\.\d+")
        for field in ("from_version", "to_version"):
            value = metadata[field]
            assert version_pattern.match(value), f"{field} must look like vX.Y.Z, got: {value!r}"

        # Assertion (e): python_path points at a fingerprint-keyed venv under
        # the daemon's untracked/, NOT a system /usr/bin/. This is the v3.9.x
        # field-bug class — if metadata emission resolves python the wrong way,
        # future upgrade-commit metadata would be misleading.
        #
        # We deliberately do NOT pin the exact venv directory. Plan 00124 added
        # the project-path slug to ensure_venv's venv key. A cross-version
        # upgrade whose target tag predates that fix installs a slug-less
        # ``venv-py{MM}-{hash}`` while the post-fix installer produces a slugged
        # ``venv-{slug}-py{MM}-{hash}`` — both legitimate fingerprint venvs may
        # sit side by side during the transition. The contract this assertion
        # guards is "a real venv interpreter under untracked/, never the system
        # python", which is exactly the v3.9.x regression surface.
        reported_python = Path(metadata["python_path"])
        untracked_dir = daemon_dir / "untracked"
        assert (
            untracked_dir in reported_python.parents
        ), f"python_path must live under {untracked_dir}, got={metadata['python_path']!r}"
        assert reported_python.match("venv-*py3*/bin/python"), (
            f"python_path must be a fingerprint-keyed venv python, "
            f"got={metadata['python_path']!r}"
        )
        assert (
            reported_python.is_file()
        ), f"python_path must point at a real interpreter, got={metadata['python_path']!r}"
        assert "/usr/bin/" not in metadata["python_path"], (
            f"python_path must never be a system /usr/bin/ path.\n"
            f"got={metadata['python_path']!r}"
        )

    finally:
        if venv_python is not None:
            _stop_test_daemon(venv_python, project_root, env)
        _remove_daemon_clone(daemon_dir)


@pytest.mark.slow
def test_layer1_upgrade_sh_prints_truth_changes_summary(tmp_path: Path) -> None:
    """Layer 1 ``scripts/upgrade.sh`` must print a project-doc reconciliation summary.

    After a successful upgrade the bare script must run
    ``check-truth-changes --from <from> --to <to>`` and surface the result
    under a prominent, stable header so an agent running the bare script
    (not following upgrade.md step 4) still SEES that project docs may need
    reconciling. We assert on the unique header marker string the
    implementation prints; the rest of the summary content is lenient.
    """
    if not INSTALL_VERSION_SH.is_file():
        pytest.skip(f"install_version.sh missing at {INSTALL_VERSION_SH}")
    if not LAYER1_UPGRADE_SH.is_file():
        pytest.skip(f"Layer 1 upgrade.sh missing at {LAYER1_UPGRADE_SH}")
    if shutil.which("uv") is None:
        pytest.skip("uv not installed in this environment")

    project_root = tmp_path / "fresh-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project_root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/fake.git"],
        cwd=project_root,
        check=True,
        capture_output=True,
    )

    daemon_dir = project_root / ".claude" / "hooks-daemon"
    # Pinned to its newest tag BEFORE installing, so the baseline is stamped
    # with the version this test then upgrades to. See conftest's docstring.
    target_tag = create_daemon_clone(daemon_dir)
    venv_python: Path | None = None
    env = os.environ.copy()

    try:
        env["HOSTNAME"] = _make_test_hostname()
        env.pop("CI", None)
        env.pop("HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP", None)
        env["NO_COLOR"] = "1"

        install_result = subprocess.run(
            [BASH, str(INSTALL_VERSION_SH), str(project_root), str(daemon_dir)],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_INSTALL_TIMEOUT_SECONDS,
            cwd=project_root,
        )
        if install_result.returncode != 0:
            pytest.fail(
                "Pre-upgrade install must exit 0 to set up the fixture.\n"
                f"returncode={install_result.returncode}\n"
                f"stdout:\n{install_result.stdout}\n"
                f"stderr:\n{install_result.stderr}"
            )

        venv_candidates = sorted((daemon_dir / "untracked").glob("venv-*py3*"))
        assert venv_candidates, (
            f"Install must produce a fingerprint-keyed venv under " f"{daemon_dir}/untracked/."
        )
        venv_python = venv_candidates[0] / "bin" / "python"
        assert venv_python.is_file(), f"venv Python must exist: {venv_python}"

        tag_proc = subprocess.run(
            ["git", "-C", str(daemon_dir), "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            check=True,
        )
        target_tag = tag_proc.stdout.strip()
        assert target_tag, f"Could not resolve a tag in {daemon_dir}"

        env["HOOKS_DAEMON_PYTHON"] = str(venv_python)
        upgrade_result = subprocess.run(
            [
                BASH,
                str(LAYER1_UPGRADE_SH),
                "--project-root",
                str(project_root),
                target_tag,
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=_UPGRADE_TIMEOUT_SECONDS,
            cwd=project_root,
        )

        if upgrade_result.returncode != 0:
            pytest.fail(
                "Layer 1 upgrade.sh must exit 0 against an idempotent target tag.\n"
                f"returncode={upgrade_result.returncode}\n"
                f"--- stdout ---\n{upgrade_result.stdout}\n"
                f"--- stderr ---\n{upgrade_result.stderr}"
            )

        # The bare script must surface the truth-changes reconciliation
        # summary under this stable, unique header marker on stdout.
        assert "Project-doc reconciliation" in upgrade_result.stdout, (
            "Layer 1 upgrade.sh must print a 'Project-doc reconciliation' summary "
            "(from check-truth-changes) on stdout so agents running the bare script "
            "see that project docs may need reconciling.\n"
            f"--- stdout (last 3000 chars) ---\n{upgrade_result.stdout[-3000:]}"
        )

    finally:
        if venv_python is not None:
            _stop_test_daemon(venv_python, project_root, env)
        _remove_daemon_clone(daemon_dir)
