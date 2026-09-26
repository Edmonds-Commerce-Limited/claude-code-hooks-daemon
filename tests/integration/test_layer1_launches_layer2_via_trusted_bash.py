"""Plan 00376 review3 — Layer 1 launches Layer 2 on a TRUSTED `bash` (Plan
00376 review2 MAJOR 1's residual).

``upgrade.sh`` (Layer 1) used to run `bash "$LAYER2_SCRIPT" ...`, resolving
`bash` from the caller's own `PATH`. A caller able to plant a fake `bash`
ahead of the real one on `PATH` therefore controlled what interpreted Layer 2
before Layer 2's own `_sanitise_layer2_env` ever got a chance to run --
sanitising Layer 2's OWN environment (the fix in the same plan) does nothing
about what LAUNCHES it.

The fix: Layer 1 sources `env_sanitise.sh` from the target it just checked
out and resolves `bash` via `_gate_tool`, a fixed, root-owned,
non-group/world-writable system location -- never the caller's `PATH`. These
tests drive the REAL `scripts/upgrade.sh` against a REAL git fixture (a bare
daemon "origin" carrying a stub Layer 2 and a real copy of
`env_sanitise.sh`), with a hostile `bash` planted early on `PATH`, and prove
it never runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
ENV_SANITISE_SH = REPO_ROOT / "scripts" / "install" / "env_sanitise.sh"
GIT = shutil.which("git") or "/usr/bin/git"
REAL_BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 120

# The stub Layer 2 committed into the fixture daemon repository. `$BASH` is
# the bash builtin naming the interpreter CURRENTLY running this script --
# exactly the fact these tests need to pin down which `bash` Layer 1 chose.
# It also reports BASH_ENV and whether a caller-exported function (any
# BASH_FUNC_* import) survived into ITS OWN environment.
_STUB_LAYER2 = """\
#!/bin/bash
set -euo pipefail
echo "STUB_LAYER2_ARGS: $*"
echo "STUB_LAYER2_INTERPRETER: $BASH"
echo "STUB_LAYER2_BASH_ENV: ${BASH_ENV:-<unset>}"
echo "STUB_LAYER2_TRACK_REF: ${HOOKS_DAEMON_UNSAFE_TRACK_REF:-<unset>}"
echo "STUB_LAYER2_TRACK_REF_BECAUSE: ${HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE:-<unset>}"
# grep -c exits 1 on zero matches, which is the expected, common case here
# (no imported function survived) -- not an error to hide, so set -e is
# toggled off around it rather than masking it with `|| true`.
set +e
STUB_FUNC_COUNT=$(env | grep -c '^BASH_FUNC_')
set -e
echo "STUB_LAYER2_IMPORTED_FUNC_COUNT: $STUB_FUNC_COUNT"
for name in @REPORTED_NAMES@; do
    if [ -n "${!name+x}" ]; then
        echo "STUB_LAYER2_VAR $name=${!name}"
    else
        echo "STUB_LAYER2_VAR $name=<unset>"
    fi
done
for name in HOOKS_DAEMON_OLD_DEFAULT_CONFIG HOOKS_DAEMON_OLD_DEFAULT_SETTINGS; do
    if [ -n "${!name:-}" ] && [ -f "${!name}" ]; then
        echo "STUB_LAYER2_FILE $name=$(tr '\\n' ' ' < "${!name}")"
    fi
done
# Signal 0 sends nothing: it only asks whether the named process exists.
if [ -n "${HOOKS_DAEMON_OLD_DEFAULT_PID:-}" ] && kill -0 "$HOOKS_DAEMON_OLD_DEFAULT_PID"; then
    echo "STUB_LAYER2_BASELINE_OWNER_ALIVE: yes"
fi
"""

# Layer 1's handover to Layer 2 (review4 BLOCKER 1): Layer 1 exports each of
# these for Layer 2 itself, so each must survive the `env -i` launch.
_HANDOVER_NAMES = (
    "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION",
    "HOOKS_DAEMON_OLD_DEFAULT_CONFIG",
    "HOOKS_DAEMON_OLD_DEFAULT_PID",
    "HOOKS_DAEMON_OLD_DEFAULT_SETTINGS",
)

# Operator settings Layer 2, its libraries or the daemon it restarts read
# (review4 m2): each is data, not a way to choose what code runs.
_KEPT_OPERATOR_SETTINGS = {
    "HOOKS_DAEMON_VENV_PATH": "/opt/venvs/hooks",
    "HOOKS_DAEMON_VENV_BUILD_TIMEOUT": "900",
    "HOOKS_DAEMON_VENV_PROBE_TIMEOUT": "30",
    "HOOKS_DAEMON_VENV_LOCK_TIMEOUT": "120",
    "HOOKS_DAEMON_VENV_LOCK_STALE_SECONDS": "600",
    "HOOKS_DAEMON_VENV_LOCK_HEARTBEAT_SECONDS": "15",
    "HOOKS_DAEMON_VENV_LOCK_BACKEND": "mkdir",
    "HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP": "0",
    "HOOKS_DAEMON_ROOT_DIR": "/srv/project",
    "CI": "false",
    "VERBOSE": "true",
    "HOSTNAME": "pinned-host",
    "XDG_RUNTIME_DIR": "/run/user/4242",
    "CLAUDE_HOOKS_SOCKET_PATH": "/run/hooks/daemon.sock",
    "CLAUDE_HOOKS_PID_PATH": "/run/hooks/daemon.pid",
    "CLAUDE_HOOKS_LOG_PATH": "/run/hooks/daemon.log",
    "HOOKS_DAEMON_MODE": "default",
    "HOOKS_DAEMON_EVENTS_DIR": "/run/hooks/events",
    "HOOKS_DAEMON_LOG_LEVEL": "DEBUG",
    "HOOKS_DAEMON_INPUT_VALIDATION": "true",
    "HOOKS_DAEMON_VALIDATION_STRICT": "false",
    "UV_LINK_MODE": "copy",
    "UV_CACHE_DIR": "/var/cache/uv",
}

# Never forwarded: Layer 2's own internal state, test seams, and a family
# nothing in Layer 2 reads.
_DROPPED_SETTINGS = {
    "HOOKS_DAEMON_UPGRADE_SECOND_PASS": "1",
    "HOOKS_DAEMON_COMPAT_CHECK_DONE": "1",
    "HOOKS_DAEMON_VENV_LOCK_INHERITED": "flock:9",
    "HOOKS_DAEMON_DOCKERENV_PATH": "/tmp/fake-dockerenv",
    "HOOKS_DAEMON_CONTAINERENV_PATH": "/tmp/fake-containerenv",
    "PIP_INDEX_URL": "https://example.invalid/simple",
    "PIP_CONFIG_FILE": "/tmp/pip.conf",
}

_STUB_LAYER2 = _STUB_LAYER2.replace(
    "@REPORTED_NAMES@",
    " ".join([*_HANDOVER_NAMES, *_KEPT_OPERATOR_SETTINGS, *_DROPPED_SETTINGS]),
)

# The example config and settings v1.0.0 shipped, which Layer 1 preserves for
# Layer 2 before its checkout replaces them.
_OLD_EXAMPLE_CONFIG = "version: '1.0'\nold_default: true\n"
_OLD_SETTINGS = '{"old": true}\n'


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
def daemon_remote(tmp_path: Path) -> Path:
    """A bare daemon "origin" tagged v1.0.0: a stub Layer 2 plus a real
    `env_sanitise.sh`, the same tree `$LAYER2_SCRIPT` itself is read from.
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
    scripts.mkdir()
    stub = scripts / "upgrade_version.sh"
    stub.write_text(_STUB_LAYER2)
    stub.chmod(0o755)
    install_dir = scripts / "install"
    install_dir.mkdir()
    shutil.copy(ENV_SANITISE_SH, install_dir / "env_sanitise.sh")
    (work / ".claude").mkdir()
    (work / ".claude" / "hooks-daemon.yaml.example").write_text(_OLD_EXAMPLE_CONFIG)
    (work / ".claude" / "settings.json").write_text(_OLD_SETTINGS)

    _commit_all(work, "release v1.0.0")
    _require_ok(_git("tag", "v1.0.0", cwd=work), "tag")
    _require_ok(_git("push", "-q", "origin", "main", cwd=work), "push main")
    _require_ok(_git("push", "-q", "origin", "v1.0.0", cwd=work), "push tag")
    return remote


@pytest.fixture
def client_project(tmp_path: Path, daemon_remote: Path) -> Path:
    """A client project whose daemon dir is a clone sitting on ``v1.0.0``."""
    project = tmp_path / "client"
    (project / ".claude").mkdir(parents=True)
    _require_ok(_git("init", "-q", str(project), cwd=tmp_path), "client init")
    (project / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    daemon_dir = project / ".claude" / "hooks-daemon"
    _require_ok(_git("clone", "-q", str(daemon_remote), str(daemon_dir), cwd=tmp_path), "daemon clone")
    _require_ok(_git("checkout", "-q", "v1.0.0", cwd=daemon_dir), "checkout tag")
    return project


@pytest.fixture
def hostile_bash(tmp_path: Path) -> tuple[Path, Path]:
    """An executable named `bash`, ahead of the real one on `PATH`.

    Returns (its directory, the marker file it touches if ever run). It
    execs the real bash afterwards so that IF it were ever invoked, the
    command it was asked to run still completes -- this is a detector, not a
    saboteur, so a false negative here cannot be mistaken for the fix simply
    crashing the upgrade.
    """
    marker = tmp_path / "hostile_bash_ran"
    bin_dir = tmp_path / "hostile-bin"
    bin_dir.mkdir()
    hostile = bin_dir / "bash"
    hostile.write_text(f'#!/bin/sh\ntouch "{marker}"\nexec {REAL_BASH} "$@"\n')
    hostile.chmod(0o755)
    return bin_dir, marker


def _run_layer1(
    project: Path,
    path_prefix: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
    env["NO_COLOR"] = "1"
    env.pop("HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION", None)
    # This suite's own test harness hermetically isolates ~/.gitconfig via
    # GIT_CONFIG_GLOBAL (tests/conftest.py) so tests never touch a real one --
    # but that would mask exactly what TestLayer1FetchIgnoresAHostileGlobalGitConfig
    # probes: a REAL caller's global config, with no such hermetic override.
    # Drop it here so Layer 1's OWN sanitisation is what is under test.
    env.pop("GIT_CONFIG_GLOBAL", None)
    env.pop("GIT_CONFIG_NOSYSTEM", None)
    if path_prefix is not None:
        env["PATH"] = f"{path_prefix}{os.pathsep}{env.get('PATH', '')}"
    if extra_env is not None:
        env.update(extra_env)
    return subprocess.run(
        [REAL_BASH, str(LAYER1_UPGRADE_SH), "--project-root", str(project), "v1.0.0"],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _stub_field(stdout: str, name: str) -> str:
    line = next(line for line in stdout.splitlines() if line.startswith(f"{name}:"))
    return line.split(":", 1)[1].strip()


def _stub_var(stdout: str, name: str) -> str:
    prefix = f"STUB_LAYER2_VAR {name}="
    line = next(line for line in stdout.splitlines() if line.startswith(prefix))
    return line[len(prefix) :]


def _stub_file(stdout: str, name: str) -> str | None:
    prefix = f"STUB_LAYER2_FILE {name}="
    for line in stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


class TestLayer1HandsItsBaselinesToLayer2:
    """Plan 00376 review4 BLOCKER 1.

    Layer 1 exports the pre-checkout version and copies of the old default
    config and settings for Layer 2 itself. Launching Layer 2 through `env -i`
    with an allowlist that left them out made every accepted default read as a
    customisation, while Layer 1 still logged that it had preserved them.
    """

    def test_the_previous_version_reaches_layer2(self, client_project: Path) -> None:
        result = _run_layer1(client_project)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_var(result.stdout, "HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION") == "v1.0.0"

    def test_the_old_default_config_baseline_reaches_layer2(self, client_project: Path) -> None:
        result = _run_layer1(client_project)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_file(result.stdout, "HOOKS_DAEMON_OLD_DEFAULT_CONFIG") == (
            _OLD_EXAMPLE_CONFIG.replace("\n", " ").strip()
        )
        assert _stub_field(result.stdout, "STUB_LAYER2_BASELINE_OWNER_ALIVE") == "yes"

    def test_the_old_default_settings_baseline_reaches_layer2(self, client_project: Path) -> None:
        result = _run_layer1(client_project)

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_file(result.stdout, "HOOKS_DAEMON_OLD_DEFAULT_SETTINGS") == _OLD_SETTINGS.strip()


class TestLayer2EnvAllowlistIsDecidedPerSetting:
    """Plan 00376 review4 m2: every setting Layer 2 reads is kept or dropped
    on purpose, not by omission."""

    @pytest.mark.parametrize(("name", "value"), sorted(_KEPT_OPERATOR_SETTINGS.items()))
    def test_an_operator_setting_reaches_layer2(
        self, client_project: Path, name: str, value: str
    ) -> None:
        result = _run_layer1(client_project, extra_env={name: value})

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_var(result.stdout, name) == value

    @pytest.mark.parametrize(("name", "value"), sorted(_DROPPED_SETTINGS.items()))
    def test_internal_state_and_unused_settings_do_not(
        self, client_project: Path, name: str, value: str
    ) -> None:
        result = _run_layer1(client_project, extra_env={name: value})

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_var(result.stdout, name) == "<unset>"


class TestLayer2IsLaunchedOnATrustedBash:
    def test_a_hostile_bash_planted_ahead_on_path_never_runs(
        self, client_project: Path, hostile_bash: tuple[Path, Path]
    ) -> None:
        bin_dir, marker = hostile_bash
        result = _run_layer1(client_project, path_prefix=bin_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        assert not marker.exists(), "the hostile bash on PATH ran Layer 2"
        assert "STUB_LAYER2_ARGS:" in result.stdout

    def test_layer2_runs_on_the_gate_trusted_interpreter_not_a_bare_path_lookup(
        self, client_project: Path, hostile_bash: tuple[Path, Path]
    ) -> None:
        bin_dir, _marker = hostile_bash
        result = _run_layer1(client_project, path_prefix=bin_dir)

        assert result.returncode == 0, result.stdout + result.stderr
        interpreter_line = next(
            line for line in result.stdout.splitlines() if line.startswith("STUB_LAYER2_INTERPRETER:")
        )
        interpreter = interpreter_line.split(": ", 1)[1].strip()
        assert interpreter != str(bin_dir / "bash")
        assert interpreter.startswith(("/usr/bin/", "/bin/", "/usr/sbin/", "/sbin/", "/usr/local/bin/", "/opt/homebrew/bin/"))

    def test_without_a_hostile_path_the_upgrade_still_succeeds(self, client_project: Path) -> None:
        """The fix must not break the ordinary, non-hostile case."""
        result = _run_layer1(client_project)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_ARGS:" in result.stdout


class TestLayer2EnvIsIsolatedFromTheCaller:
    """Plan 00376 review3 MAJOR 2 -- the trusted-bash fix closed PATH only.

    `BASH_ENV` runs inside Layer 2 before its own `_sanitise_layer2_env`
    ever gets a say, and no importing shell can strip an exported function
    from what it hands to a child (the name it lands under is not
    predictable enough to `env -u` it away). Layer 1 now launches Layer 2
    through the trusted `env -i` with an explicit allowlist instead of a
    bare inherited environment, so nothing not on that list -- BASH_ENV,
    ENV, or any BASH_FUNC_* -- reaches it at all.
    """

    def test_bash_env_does_not_reach_layer2(self, client_project: Path) -> None:
        result = _run_layer1(client_project, extra_env={"BASH_ENV": "/tmp/does-not-exist-evil.sh"})

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_field(result.stdout, "STUB_LAYER2_BASH_ENV") == "<unset>"

    def test_an_exported_function_does_not_reach_layer2(self, client_project: Path) -> None:
        """A hostile exported `unset` is the shape that defeats an in-bash
        drop loop -- `env -i` defeats it differently, by never handing the
        child an environment to import a function FROM in the first place.
        """
        harness = (
            "unset() { :; }\n"
            "export -f unset\n"
            f'exec {REAL_BASH} "{LAYER1_UPGRADE_SH}" --project-root "{client_project}" v1.0.0\n'
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
        env["NO_COLOR"] = "1"
        env.pop("HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION", None)
        result = subprocess.run(
            [REAL_BASH, "-c", harness],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_field(result.stdout, "STUB_LAYER2_IMPORTED_FUNC_COUNT") == "0"

    def test_the_guarded_branch_install_vars_do_reach_layer2(
        self, tmp_path: Path, client_project: Path, daemon_remote: Path
    ) -> None:
        """Not everything is stripped -- only the review3 MAJOR 2 attack
        surface. HOOKS_DAEMON_UNSAFE_TRACK_REF/_BECAUSE are the guarded
        branch-install feature's own first-party inputs (Plan 00291);
        dropping them from the `env -i` allowlist would silently break that
        feature rather than close a gap, and did until this test caught it.
        """
        work = tmp_path / "branch-work"
        _require_ok(_git("clone", "-q", str(daemon_remote), str(work), cwd=tmp_path), "clone branch work")
        _require_ok(_git("checkout", "-q", "-b", "e2e-track", "v1.0.0", cwd=work), "cut branch")
        _require_ok(_git("commit", "-q", "--allow-empty", "-m", "branch tip", cwd=work), "branch tip")
        _require_ok(_git("push", "-q", "origin", "e2e-track", cwd=work), "push branch")

        # The tracked ref IS the target: no positional version argument (that
        # would conflict with it), unlike every other case in this file.
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_UNSAFE")}
        env["NO_COLOR"] = "1"
        env.pop("HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION", None)
        env["HOOKS_DAEMON_UNSAFE_TRACK_REF"] = "e2e-track"
        env["HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE"] = "test"
        result = subprocess.run(
            [REAL_BASH, str(LAYER1_UPGRADE_SH), "--project-root", str(client_project)],
            capture_output=True,
            text=True,
            env=env,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert _stub_field(result.stdout, "STUB_LAYER2_TRACK_REF") == "e2e-track"
        assert _stub_field(result.stdout, "STUB_LAYER2_TRACK_REF_BECAUSE") == "test"


class TestLayer1FetchIgnoresAHostileGlobalGitConfig:
    """Plan 00376 review3 MINOR m2 (review-2 M2 residual).

    ``git -C "$DAEMON_DIR" fetch --tags --force`` (Layer 1, ``upgrade.sh``)
    honoured whatever `~/.gitconfig` the caller happened to have -- so
    `git config --global url.<evil>.insteadOf <real-remote-prefix>` silently
    rewrote where the fetch actually went, with no `git -C`/`remote set-url`
    shape for the approval guard to catch. Layer 1 now runs every git
    invocation with `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1`, so a
    hostile global config is never read at all.
    """

    def test_a_global_insteadof_rewrite_does_not_redirect_the_fetch(
        self, tmp_path: Path, client_project: Path, daemon_remote: Path
    ) -> None:
        # The decoy is not a git repository at all -- if the redirect were
        # honoured, `git fetch` would fail to reach it (non-zero exit, `set
        # -euo pipefail` aborts Layer 1). If the redirect is ignored, the
        # fetch reaches the REAL remote and the upgrade proceeds normally.
        # Whether the fetch succeeded is therefore itself the signal.
        decoy_remote = tmp_path / "decoy-not-a-repo"
        decoy_remote.mkdir()

        fake_home = tmp_path / "fake-home"
        fake_home.mkdir()
        gitconfig = fake_home / ".gitconfig"
        gitconfig.write_text(
            "[url \"" + str(decoy_remote) + "\"]\n"
            "    insteadOf = " + str(daemon_remote) + "\n"
        )

        result = _run_layer1(client_project, extra_env={"HOME": str(fake_home)})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "STUB_LAYER2_ARGS:" in result.stdout
