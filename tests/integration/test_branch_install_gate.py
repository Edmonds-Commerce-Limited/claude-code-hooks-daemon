r"""Plan 00291 Phase 3 — the guarded branch-install gate in the upgrade tooling.

The owner ruling: tracking a branch must not be something a normal user can
do. So the gate is two environment variables, both required, with no
positional spelling and no mention in the user-facing documents. These tests
pin every clause of that ruling against the REAL ``scripts/upgrade.sh``
(Layer 1) and the REAL ``scripts/install/branch_install.sh`` library that
Layer 2 sources.

Layer 1 is driven against a synthetic daemon repository whose Layer 2 is a
stub that records what it was handed. That keeps these tests fast (no venv)
while still running the real argument parsing, gate evaluation, fetch and
checkout. The venv-building end of the chain is covered by the slow
acceptance test in ``tests/acceptance/test_guarded_branch_install.py``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
BRANCH_INSTALL_LIB = REPO_ROOT / "scripts" / "install" / "branch_install.sh"
OUTPUT_LIB = REPO_ROOT / "scripts" / "install" / "output.sh"
GIT = shutil.which("git") or "/usr/bin/git"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 120

REF_VAR = "HOOKS_DAEMON_UNSAFE_TRACK_REF"
REASON_VAR = "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE"

# The stub Layer 2 committed into the fixture daemon repository. It records
# its positional arguments and the gate-related environment so a test can
# assert what Layer 1 handed over, and exits 0 so Layer 1 goes on to emit
# its UPGRADE_METADATA block.
_STUB_LAYER2 = """\
#!/bin/bash
set -euo pipefail
echo "STUB_LAYER2_ARGS: $*"
echo "STUB_LAYER2_HEAD: $(git -C "$2" rev-parse HEAD)"
echo "STUB_LAYER2_REF_VAR: ${HOOKS_DAEMON_UNSAFE_TRACK_REF:-<unset>}"
echo "STUB_LAYER2_REASON_VAR: ${HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE:-<unset>}"
echo "STUB_LAYER2_PREVIOUS_VERSION: ${HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION:-<unset>}"
"""


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT, *args], cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
    )


def _require_ok(result: subprocess.CompletedProcess[str], what: str) -> None:
    if result.returncode != 0:
        raise AssertionError(f"fixture setup failed ({what}): {result.stderr.strip()}")


def _commit_all(work: Path, message: str) -> str:
    _require_ok(_git("add", "-A", cwd=work), f"add ({message})")
    _require_ok(_git("commit", "-qm", message, cwd=work), f"commit ({message})")
    return _git("rev-parse", "HEAD", cwd=work).stdout.strip()


@pytest.fixture
def daemon_remote(tmp_path: Path) -> dict[str, object]:
    """A bare daemon "origin" with a tag ``v1.0.0`` and a ``main`` one commit ahead.

    Returns the bare path, the tag commit and the branch-tip commit so a test
    can say which one Layer 1 landed on.
    """
    remote = tmp_path / "daemon-origin.git"
    work = tmp_path / "daemon-work"
    _require_ok(_git("init", "-q", "--bare", "-b", "main", str(remote), cwd=tmp_path), "bare")
    _require_ok(_git("clone", "-q", str(remote), str(work), cwd=tmp_path), "clone work")
    _require_ok(_git("config", "user.email", "test@example.com", cwd=work), "email")
    _require_ok(_git("config", "user.name", "Test", cwd=work), "name")
    _require_ok(_git("checkout", "-q", "-b", "main", cwd=work), "main branch")

    (work / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "1.0.0"\n')
    scripts = work / "scripts"
    (scripts / "lib").mkdir(parents=True)
    shutil.copy(REPO_ROOT / "scripts" / "lib" / "python_discovery.sh", scripts / "lib")
    stub = scripts / "upgrade_version.sh"
    stub.write_text(_STUB_LAYER2)
    stub.chmod(0o755)
    tag_commit = _commit_all(work, "release v1.0.0")
    _require_ok(_git("tag", "v1.0.0", cwd=work), "tag")

    (work / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "1.1.0"\n')
    tip_commit = _commit_all(work, "work towards v1.1.0")

    _require_ok(_git("push", "-q", "origin", "main", cwd=work), "push main")
    _require_ok(_git("push", "-q", "origin", "v1.0.0", cwd=work), "push tag")
    return {"remote": remote, "tag_commit": tag_commit, "tip_commit": tip_commit}


@pytest.fixture
def client_project(tmp_path: Path, daemon_remote: dict[str, object]) -> Path:
    """A client project whose daemon dir is a clone sitting on ``v1.0.0``."""
    project = tmp_path / "client"
    (project / ".claude").mkdir(parents=True)
    _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "client init")
    (project / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    daemon_dir = project / ".claude" / "hooks-daemon"
    remote = str(daemon_remote["remote"])
    _require_ok(_git("clone", "-q", remote, str(daemon_dir), cwd=tmp_path), "daemon clone")
    _require_ok(_git("checkout", "-q", "v1.0.0", cwd=daemon_dir), "checkout tag")
    return project


def _run_layer1(
    project: Path, *positional: str, gate: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["NO_COLOR"] = "1"
    env.pop("HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION", None)
    if gate:
        env.update(gate)
    return subprocess.run(
        [BASH, str(LAYER1_UPGRADE_SH), "--project-root", str(project), *positional],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _daemon_head(project: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=project / ".claude" / "hooks-daemon").stdout.strip()


# ---------------------------------------------------------------------------
# Layer 1: the positional spelling never reaches a branch
# ---------------------------------------------------------------------------


class TestPositionalBranchNameKeepsFailing:
    def test_bare_main_is_normalised_to_a_tag_name_and_rejected(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        result = _run_layer1(client_project, "main")
        assert result.returncode != 0
        assert "vmain" in result.stdout + result.stderr
        assert _daemon_head(client_project) == daemon_remote["tag_commit"]

    def test_a_tag_still_works_without_the_gate(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        result = _run_layer1(client_project, "v1.0.0")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_ARGS:" in result.stdout
        assert "NON-RELEASE" not in result.stdout
        assert _daemon_head(client_project) == daemon_remote["tag_commit"]


# ---------------------------------------------------------------------------
# Layer 1: the gate
# ---------------------------------------------------------------------------


class TestGateArmed:
    def test_both_variables_land_the_branch_tip_and_hand_layer2_the_commit(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        tip = str(daemon_remote["tip_commit"])
        result = _run_layer1(
            client_project, gate={REF_VAR: "main", REASON_VAR: "Plan 00291 gate test"}
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _daemon_head(client_project) == tip
        assert f"STUB_LAYER2_HEAD: {tip}" in result.stdout
        assert "STUB_LAYER2_REF_VAR: main" in result.stdout
        assert "STUB_LAYER2_REASON_VAR: Plan 00291 gate test" in result.stdout
        # Layer 2 is handed the resolved commit, never the bare ref, so its
        # own rev-parse/checkout cannot land on a stale local branch.
        args_line = next(line for line in result.stdout.splitlines() if "STUB_LAYER2_ARGS" in line)
        assert args_line.split()[-1] == tip

    def test_the_banner_is_loud_and_names_ref_reason_and_stamp(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        short = str(daemon_remote["tip_commit"])[:7]
        result = _run_layer1(
            client_project, gate={REF_VAR: "main", REASON_VAR: "Plan 00291 gate test"}
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "NON-RELEASE INSTALL" in result.stdout
        assert "Plan 00291 gate test" in result.stdout
        assert "main @" in result.stdout
        assert f"v1.1.0+main.{short}" in result.stdout

    def test_metadata_reports_the_stamp_as_the_target(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        short = str(daemon_remote["tip_commit"])[:7]
        result = _run_layer1(client_project, gate={REF_VAR: "main", REASON_VAR: "x"})
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"to_version=v1.1.0+main.{short}" in result.stdout

    def test_positional_version_alongside_the_gate_is_refused(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        result = _run_layer1(client_project, "v1.0.0", gate={REF_VAR: "main", REASON_VAR: "x"})
        assert result.returncode != 0
        assert REF_VAR in result.stderr
        assert "STUB_LAYER2_ARGS" not in result.stdout
        assert _daemon_head(client_project) == daemon_remote["tag_commit"]


class TestGateHalfArmedIsRefused:
    @pytest.mark.parametrize(
        ("present", "missing"),
        [(REF_VAR, REASON_VAR), (REASON_VAR, REF_VAR)],
    )
    def test_exactly_one_variable_fails_naming_the_other(
        self, client_project: Path, daemon_remote: dict[str, object], present: str, missing: str
    ) -> None:
        result = _run_layer1(client_project, gate={present: "main"})
        assert result.returncode != 0
        assert missing in result.stderr
        assert "STUB_LAYER2_ARGS" not in result.stdout
        assert _daemon_head(client_project) == daemon_remote["tag_commit"]

    def test_an_empty_reason_counts_as_missing(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        result = _run_layer1(client_project, gate={REF_VAR: "main", REASON_VAR: ""})
        assert result.returncode != 0
        assert REASON_VAR in result.stderr
        assert _daemon_head(client_project) == daemon_remote["tag_commit"]


class TestGateIsNotAdvertisedByTheScript:
    def test_help_does_not_mention_it(self) -> None:
        result = subprocess.run(
            [BASH, str(LAYER1_UPGRADE_SH), "--help"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0
        assert "UNSAFE_TRACK_REF" not in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Layer 1: the fresh-clone client state (Task 1.2 / 1.3)
# ---------------------------------------------------------------------------


class TestFreshCloneClientState:
    def test_missing_daemon_dir_is_cloned_and_the_upgrade_proceeds(
        self, tmp_path: Path, daemon_remote: dict[str, object]
    ) -> None:
        """Config committed, no daemon checkout, no venv: the documented route works."""
        project = tmp_path / "fresh-clone"
        (project / ".claude").mkdir(parents=True)
        _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "init")
        (project / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
        (project / ".claude" / "HOOKS-DAEMON.md").write_text(
            "# Hooks Daemon - Active Configuration\n\n"
            "> Generated on 2026-01-01 (v0.9.0) by `generate-docs`.\n"
        )

        env_url = {"HOOKS_DAEMON_CLONE_URL": str(daemon_remote["remote"])}
        result = _run_layer1(project, "v1.0.0", gate=env_url)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _daemon_head(project) == daemon_remote["tag_commit"]
        assert "STUB_LAYER2_ARGS:" in result.stdout

    def test_previous_version_comes_from_the_committed_docs_when_there_was_no_checkout(
        self, tmp_path: Path, daemon_remote: dict[str, object]
    ) -> None:
        """Task 1.3: the FROM side is the version the client last ran, not the clone's HEAD."""
        project = tmp_path / "fresh-clone"
        (project / ".claude").mkdir(parents=True)
        _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "init")
        (project / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
        (project / ".claude" / "HOOKS-DAEMON.md").write_text(
            "> Generated on 2026-01-01 (v0.9.0) by `generate-docs`.\n"
        )

        result = _run_layer1(
            project, "v1.0.0", gate={"HOOKS_DAEMON_CLONE_URL": str(daemon_remote["remote"])}
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_PREVIOUS_VERSION: v0.9.0" in result.stdout
        assert "from_version=v0.9.0" in result.stdout

    def test_previous_version_is_handed_to_layer2_on_the_normal_path_too(
        self, client_project: Path
    ) -> None:
        """Task 1.3: Layer 2 used to print 'Current version: unknown' with no venv."""
        result = _run_layer1(client_project, "v1.0.0")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_PREVIOUS_VERSION: v1.0.0" in result.stdout

    def test_no_clone_when_the_project_has_no_config(self, tmp_path: Path) -> None:
        """No config means this is not an existing client: install, do not upgrade."""
        project = tmp_path / "not-a-client"
        (project / ".claude").mkdir(parents=True)
        _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "init")

        result = _run_layer1(project, "v1.0.0")

        assert result.returncode != 0
        assert not (project / ".claude" / "hooks-daemon").exists()
        assert "LLM-INSTALL" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Layer 2 refuses a half-armed gate before touching anything
# ---------------------------------------------------------------------------

LAYER2_UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"


class TestLayer2RefusesAHalfArmedGate:
    @pytest.mark.parametrize(("present", "missing"), [(REF_VAR, REASON_VAR), (REASON_VAR, REF_VAR)])
    def test_exactly_one_variable_fails_before_any_step_runs(
        self, client_project: Path, present: str, missing: str
    ) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
        env["NO_COLOR"] = "1"
        env[present] = "main"
        daemon_dir = client_project / ".claude" / "hooks-daemon"
        result = subprocess.run(
            [BASH, str(LAYER2_UPGRADE_VERSION_SH), str(client_project), str(daemon_dir), "v1.0.0"],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode != 0
        assert missing in result.stderr
        assert "Safety checks" not in result.stdout


# ---------------------------------------------------------------------------
# The library Layer 2 sources
# ---------------------------------------------------------------------------

_LIB_HARNESS = 'set -euo pipefail\nsource "$1"\nsource "$2"\nshift 2\n"$@"\n'


def _run_lib(
    func: str, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    base["NO_COLOR"] = "1"
    if env:
        base.update(env)
    return subprocess.run(
        [BASH, "-c", _LIB_HARNESS, "_", str(OUTPUT_LIB), str(BRANCH_INSTALL_LIB), func, *args],
        capture_output=True,
        text=True,
        env=base,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


class TestBranchInstallLibrary:
    def test_lib_exists_and_is_source_safe(self) -> None:
        assert BRANCH_INSTALL_LIB.is_file()
        result = subprocess.run(
            [
                BASH,
                "-c",
                f'set -euo pipefail; source "{OUTPUT_LIB}"; source "{BRANCH_INSTALL_LIB}"',
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_gate_is_off_when_neither_variable_is_set(self) -> None:
        result = _run_lib("branch_install_gate_state")
        assert result.returncode == 0
        assert result.stdout.strip() == "off"

    def test_gate_is_armed_when_both_are_set(self) -> None:
        result = _run_lib("branch_install_gate_state", env={REF_VAR: "main", REASON_VAR: "why"})
        assert result.returncode == 0
        assert result.stdout.strip() == "armed"

    @pytest.mark.parametrize(("present", "missing"), [(REF_VAR, REASON_VAR), (REASON_VAR, REF_VAR)])
    def test_half_armed_gate_fails_naming_the_missing_variable(
        self, present: str, missing: str
    ) -> None:
        result = _run_lib("branch_install_gate_state", env={present: "main"})
        assert result.returncode != 0
        assert missing in result.stderr

    def test_stamp_is_version_plus_ref_and_short_sha(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        daemon_dir = client_project / ".claude" / "hooks-daemon"
        short = str(daemon_remote["tag_commit"])[:7]
        result = _run_lib("branch_install_stamp", str(daemon_dir), "main")
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"v1.0.0+main.{short}"

    def test_stamp_sanitises_slashes_in_the_ref(
        self, client_project: Path, daemon_remote: dict[str, object]
    ) -> None:
        daemon_dir = client_project / ".claude" / "hooks-daemon"
        short = str(daemon_remote["tag_commit"])[:7]
        result = _run_lib("branch_install_stamp", str(daemon_dir), "feature/thing")
        assert result.stdout.strip() == f"v1.0.0+feature-thing.{short}"

    def test_banner_names_ref_reason_and_stamp(self) -> None:
        result = _run_lib(
            "print_branch_install_banner", "main", "because canary", "v1.1.0+main.abc1234"
        )
        assert result.returncode == 0
        # The banner is a warning, not data: it must go to stderr so it can
        # never corrupt a VAR=$(print_branch_install_banner ...) caller (the
        # capture_corruption audit's log-helper-stdout rule).
        assert result.stdout == ""
        assert "NON-RELEASE INSTALL" in result.stderr
        assert "because canary" in result.stderr
        assert "v1.1.0+main.abc1234" in result.stderr
        assert "release tag" in result.stderr
