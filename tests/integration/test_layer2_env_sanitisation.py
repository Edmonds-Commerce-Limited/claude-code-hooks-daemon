"""Plan 00376 review2 MAJOR 1 — Layer 2 resets the caller's environment.

Layer 2 (``scripts/upgrade_version.sh``) inherits whatever environment its
caller happens to be in, whether that is Layer 1 or an agent running it
directly. Left alone, that is a way for the caller to steer the install:
``BASH_ENV``/``ENV`` run arbitrary code the moment any subshell starts,
``SHELLOPTS``/``BASHOPTS`` can turn on command tracing (or worse) before this
script's own ``set -euo pipefail`` line runs, ``CDPATH``/``GLOBIGNORE``/
``IFS`` can misdirect a bare ``cd`` or word-split a value unexpectedly, and
``PYTHON*``/``LD_*``/``DYLD_*``/``GIT_*``/``PERL5*``/``RUBY*``/
``NODE_OPTIONS`` steer the interpreters and tools the rest of this script and
the libraries it sources shell out to.

``_sanitise_layer2_env`` (``scripts/install/env_sanitise.sh``) is the fix, and
these tests exercise the REAL function: each sets a hostile value for one
variable family, sources the real library and calls the real function in a
subprocess, and proves the hostile value has no effect from that point on.
``HOME``, ``LANG``, proxy variables and ``uv``/cache settings are data, not a
way to change what code runs, and are left alone -- the last test in this
file pins that.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_SANITISE_SH = REPO_ROOT / "scripts" / "install" / "env_sanitise.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _run(harness: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _base_env(**overrides: str) -> dict[str, str]:
    """A minimal, real environment: enough for bash itself to run."""
    base = {"HOME": os.environ.get("HOME", "/root"), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    base.update(overrides)
    return base


class TestBashEnvAndEnv:
    def test_bash_env_does_not_reach_a_child_spawned_after_sanitisation(self, tmp_path: Path) -> None:
        """BASH_ENV is read at a non-interactive bash's OWN startup, so the
        outer harness process here has already sourced it once by the time
        any of the harness's own lines run -- that one run is unavoidable
        and not what this test is about. What matters is whether a CHILD
        bash spawned AFTER `_sanitise_layer2_env` still inherits it: the log
        gets exactly one line (the outer process's own unavoidable startup
        run) if sanitisation works, and two if the nested child ran it too.
        """
        log = tmp_path / "bash_env_runs.log"
        hostile = tmp_path / "hostile.sh"
        hostile.write_text(f'echo ran >> "{log}"\n', encoding="utf-8")

        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            f'{BASH} -c "true"\n'
            'echo "BASH_ENV=${BASH_ENV:-<unset>}"\n'
        )
        result = _run(harness, _base_env(BASH_ENV=str(hostile)))

        assert result.returncode == 0, result.stderr
        assert "BASH_ENV=<unset>" in result.stdout
        run_count = len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
        assert run_count == 1, (
            f"expected exactly 1 run (the outer process's own unavoidable "
            f"startup sourcing), got {run_count} -- a nested child inherited "
            "the hostile BASH_ENV"
        )

    def test_env_is_unset_after_sanitisation(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "ENV=${ENV:-<unset>}"\n'
        )
        result = _run(harness, _base_env(ENV="/tmp/hostile-env.sh"))

        assert result.returncode == 0, result.stderr
        assert "ENV=<unset>" in result.stdout


class TestPath:
    def test_path_is_reset_to_the_trusted_path(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "expected=\"$(_gate_trusted_path)\"\n"
            "_sanitise_layer2_env\n"
            'echo "EXPECTED=$expected"\n'
            'echo "ACTUAL=$PATH"\n'
        )
        result = _run(harness, _base_env(PATH="/tmp/evil-bin:" + os.environ.get("PATH", "/usr/bin:/bin")))

        assert result.returncode == 0, result.stderr
        lines = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        assert lines["ACTUAL"] == lines["EXPECTED"]
        assert "/tmp/evil-bin" not in lines["ACTUAL"]


class TestShelloptsAndBashopts:
    def test_xtrace_forced_via_shellopts_does_not_survive_sanitisation(self, tmp_path: Path) -> None:
        """SHELLOPTS/BASHOPTS are bash-maintained and readonly -- `unset` on
        them errors under `set -e`; the fix neutralises the OPTIONS they
        primed at shell startup instead of the variable itself."""
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "MARKER_AFTER_SANITISE"\n'
        )
        env = _base_env()
        env["SHELLOPTS"] = "xtrace"
        result = _run(harness, env)

        assert result.returncode == 0, result.stderr
        assert "+ echo MARKER_AFTER_SANITISE" not in result.stderr


class TestCdpathAndGlobignore:
    def test_cdpath_is_unset_after_sanitisation(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "CDPATH=${CDPATH:-<unset>}"\n'
        )
        result = _run(harness, _base_env(CDPATH="/tmp/elsewhere"))

        assert result.returncode == 0, result.stderr
        assert "CDPATH=<unset>" in result.stdout

    def test_globignore_is_unset_after_sanitisation(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "GLOBIGNORE=${GLOBIGNORE:-<unset>}"\n'
        )
        result = _run(harness, _base_env(GLOBIGNORE="*.important"))

        assert result.returncode == 0, result.stderr
        assert "GLOBIGNORE=<unset>" in result.stdout


class TestIfs:
    def test_ifs_is_reset_to_the_bash_default(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            "default=$' \\t\\n'\n"
            'if [ "$IFS" = "$default" ]; then echo "IFS_OK"; else echo "IFS_BAD"; fi\n'
        )
        env = _base_env()
        env["IFS"] = ","
        result = _run(harness, env)

        assert result.returncode == 0, result.stderr
        assert "IFS_OK" in result.stdout


class TestPythonPrefixedVariables:
    def test_python_prefixed_variables_are_unset(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "PYTHONPATH=${PYTHONPATH:-<unset>}"\n'
            'echo "PYTHONHOME=${PYTHONHOME:-<unset>}"\n'
            'echo "PYTHONSTARTUP=${PYTHONSTARTUP:-<unset>}"\n'
        )
        result = _run(
            harness,
            _base_env(
                PYTHONPATH="/tmp/evil-pth",
                PYTHONHOME="/tmp/evil-home",
                PYTHONSTARTUP="/tmp/evil-startup.py",
            ),
        )

        assert result.returncode == 0, result.stderr
        assert "PYTHONPATH=<unset>" in result.stdout
        assert "PYTHONHOME=<unset>" in result.stdout
        assert "PYTHONSTARTUP=<unset>" in result.stdout


class TestLoaderPathVariables:
    def test_ld_and_dyld_prefixed_variables_are_unset(self) -> None:
        """`LD_PRELOAD` must name a library the dynamic linker can actually
        load -- the outer `bash` invocation is itself a dynamically linked
        binary, so a bogus path would fail before the harness ever runs. A
        real, harmless library proves the point just as well: the goal is
        that it does not propagate to every child process this script and
        the libraries it sources go on to spawn (git, python, pip, ...)."""
        real_library = next(
            (
                candidate
                for candidate in (
                    "/lib/x86_64-linux-gnu/libc.so.6",
                    "/usr/lib/libc.dylib",
                    "/lib/libc.so.6",
                )
                if Path(candidate).exists()
            ),
            None,
        )
        if real_library is None:
            pytest.skip("no real shared library found to use as a harmless LD_PRELOAD value")

        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "LD_PRELOAD=${LD_PRELOAD:-<unset>}"\n'
            'echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-<unset>}"\n'
            'echo "DYLD_INSERT_LIBRARIES=${DYLD_INSERT_LIBRARIES:-<unset>}"\n'
        )
        result = _run(
            harness,
            _base_env(
                LD_PRELOAD=real_library,
                LD_LIBRARY_PATH="/tmp/evil-lib",
                DYLD_INSERT_LIBRARIES="/tmp/evil.dylib",
            ),
        )

        assert result.returncode == 0, result.stderr
        assert "LD_PRELOAD=<unset>" in result.stdout
        assert "LD_LIBRARY_PATH=<unset>" in result.stdout
        assert "DYLD_INSERT_LIBRARIES=<unset>" in result.stdout


class TestGitPrefixedVariables:
    def test_git_prefixed_variables_are_unset(self) -> None:
        """The library sets no `GIT_*` of its own, so none is exempt."""
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "GIT_SSH_COMMAND=${GIT_SSH_COMMAND:-<unset>}"\n'
            'echo "GIT_CONFIG_GLOBAL=${GIT_CONFIG_GLOBAL:-<unset>}"\n'
            'echo "GIT_EXTERNAL_DIFF=${GIT_EXTERNAL_DIFF:-<unset>}"\n'
        )
        result = _run(
            harness,
            _base_env(
                GIT_SSH_COMMAND="/tmp/evil-ssh",
                GIT_CONFIG_GLOBAL="/tmp/evil-gitconfig",
                GIT_EXTERNAL_DIFF="/tmp/evil-diff",
            ),
        )

        assert result.returncode == 0, result.stderr
        assert "GIT_SSH_COMMAND=<unset>" in result.stdout
        assert "GIT_CONFIG_GLOBAL=<unset>" in result.stdout
        assert "GIT_EXTERNAL_DIFF=<unset>" in result.stdout


class TestPerlAndRubyPrefixedVariables:
    def test_perl5_and_ruby_prefixed_variables_are_unset(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "PERL5LIB=${PERL5LIB:-<unset>}"\n'
            'echo "PERL5OPT=${PERL5OPT:-<unset>}"\n'
            'echo "RUBYOPT=${RUBYOPT:-<unset>}"\n'
            'echo "RUBYLIB=${RUBYLIB:-<unset>}"\n'
        )
        result = _run(
            harness,
            _base_env(
                PERL5LIB="/tmp/evil-perl",
                PERL5OPT="-Mevil",
                RUBYOPT="-rEvil",
                RUBYLIB="/tmp/evil-ruby",
            ),
        )

        assert result.returncode == 0, result.stderr
        assert "PERL5LIB=<unset>" in result.stdout
        assert "PERL5OPT=<unset>" in result.stdout
        assert "RUBYOPT=<unset>" in result.stdout
        assert "RUBYLIB=<unset>" in result.stdout


class TestNodeOptions:
    def test_node_options_is_unset(self) -> None:
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "NODE_OPTIONS=${NODE_OPTIONS:-<unset>}"\n'
        )
        result = _run(harness, _base_env(NODE_OPTIONS="--require /tmp/evil.js"))

        assert result.returncode == 0, result.stderr
        assert "NODE_OPTIONS=<unset>" in result.stdout


class TestDataVariablesAreLeftAlone:
    def test_home_lang_proxy_and_uv_settings_survive_sanitisation(self) -> None:
        """These are data the install legitimately needs, not code-steering."""
        harness = (
            "set -euo pipefail\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_sanitise_layer2_env\n"
            'echo "HOME=$HOME"\n'
            'echo "LANG=$LANG"\n'
            'echo "HTTPS_PROXY=$HTTPS_PROXY"\n'
            'echo "UV_CACHE_DIR=$UV_CACHE_DIR"\n'
        )
        result = _run(
            harness,
            _base_env(
                HOME="/home/example",
                LANG="en_US.UTF-8",
                HTTPS_PROXY="http://proxy.example:8080",
                UV_CACHE_DIR="/home/example/.cache/uv",
            ),
        )

        assert result.returncode == 0, result.stderr
        assert "HOME=/home/example" in result.stdout
        assert "LANG=en_US.UTF-8" in result.stdout
        assert "HTTPS_PROXY=http://proxy.example:8080" in result.stdout
        assert "UV_CACHE_DIR=/home/example/.cache/uv" in result.stdout


class TestTheIncludeGuardCannotBeInherited:
    """Plan 00376 review3 MAJOR 2 -- a pre-exported guard variable used to
    skip the whole file, function definitions included.

    ``ENV_SANITISE_SH_LOADED`` guarded a `readonly` reassignment the same way
    ``output.sh`` guards its colour constants. But a caller able to export
    ``ENV_SANITISE_SH_LOADED=1`` (plus a hostile exported ``_gate_tool``)
    made THIS file skip its own definitions entirely, leaving Layer 1 to
    call the CALLER's ``_gate_tool`` instead of the real one. Nothing here
    needs the guard -- functions redefine harmlessly, and the file's only
    plain-assigned variable is `GATE_SAFE_PATH` -- so the fix removes the
    skip path outright: sourcing this file always redefines everything.
    """

    def test_a_pre_exported_loaded_flag_does_not_skip_the_real_definitions(
        self, tmp_path: Path
    ) -> None:
        hostile_bin = tmp_path / "hostile-bin"
        hostile_bin.mkdir()
        marker = tmp_path / "hostile_gate_tool_ran"
        harness = (
            "set -euo pipefail\n"
            'export ENV_SANITISE_SH_LOADED=1\n'
            "_gate_tool() {\n"
            f'    touch "{marker}"\n'
            f'    printf \'%s\\n\' "{hostile_bin}/bash"\n'
            "}\n"
            "export -f _gate_tool\n"
            f'source "{ENV_SANITISE_SH}"\n'
            "_gate_tool bash\n"
        )
        result = _run(harness, _base_env())

        assert result.returncode == 0, result.stderr
        assert not marker.exists(), "the inherited (hostile) _gate_tool ran, not the real one"
        assert result.stdout.strip() != f"{hostile_bin}/bash"
        assert result.stdout.strip() in ("/usr/bin/bash", "/bin/bash")


_PLANTED_TOOLS = ("git", "cksum", "python3", "uv")
_ARGUMENT_PARSING_LINE = 'PROJECT_ROOT="${1:-}"'


@pytest.fixture
def layer2_head(tmp_path: Path) -> Path:
    """The REAL upgrade_version.sh up to its argument parsing -- every library
    source included -- in a copy of scripts/ so SCRIPT_DIR resolves, followed
    by a reporter."""
    scripts = tmp_path / "scripts"
    shutil.copytree(REPO_ROOT / "scripts" / "install", scripts / "install")
    shutil.copytree(REPO_ROOT / "scripts" / "lib", scripts / "lib")
    content = (REPO_ROOT / "scripts" / "upgrade_version.sh").read_text(encoding="utf-8")
    head = content[: content.index(_ARGUMENT_PARSING_LINE)]
    reporter = (
        'echo "L2_PATH=$PATH"\n'
        'echo "L2_EXPECTED=$(_gate_trusted_path)"\n'
        + "".join(
            f'echo "L2_RESOLVES {tool}=$(command -v {tool} || echo none)"\n' for tool in _PLANTED_TOOLS
        )
    )
    script = scripts / "upgrade_version.sh"
    script.write_text(head + reporter, encoding="utf-8")
    return script


@pytest.fixture
def planted_home(tmp_path: Path) -> Path:
    """A HOME whose `.local/bin` -- where the uv installer puts uv, and which
    `venv.sh` prepends to PATH when sourced -- holds a tool of each name."""
    home = tmp_path / "home"
    bin_dir = home / ".local" / "bin"
    bin_dir.mkdir(parents=True)
    for tool in _PLANTED_TOOLS:
        planted = bin_dir / tool
        planted.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        planted.chmod(0o755)
    return home


class TestLayer2PathAfterEveryLibrarySource:
    """Plan 00376 review4 MAJOR 2: `venv.sh` prepends `$HOME/.local/bin` when
    it is sourced, twelve lines AFTER `_sanitise_layer2_env`, so every step
    before the gate ran `git`, `cksum` and `python3` from a directory HOME
    names. Asserted after the LAST source, not after sanitisation."""

    def _report(self, head: Path, home: Path) -> dict[str, str]:
        result = _run(f'bash "{head}"', _base_env(HOME=str(home)))
        assert result.returncode == 0, result.stdout + result.stderr
        return dict(
            line.removeprefix("L2_").split("=", 1)
            for line in result.stdout.splitlines()
            if line.startswith("L2_")
        )

    def test_path_is_the_trusted_path_after_the_last_source(
        self, layer2_head: Path, planted_home: Path
    ) -> None:
        report = self._report(layer2_head, planted_home)

        assert report["PATH"] == report["EXPECTED"]
        assert str(planted_home) not in report["PATH"]

    @pytest.mark.parametrize("tool", ["git", "cksum", "python3"])
    def test_no_tool_resolves_from_home(
        self, layer2_head: Path, planted_home: Path, tool: str
    ) -> None:
        report = self._report(layer2_head, planted_home)

        assert not report[f"RESOLVES {tool}"].startswith(str(planted_home)), report


class TestUvIsResolvedByName:
    """The fix for MAJOR 2 keeps the uv installer's default location usable:
    `uv` alone is looked up in `$HOME/.local/bin` when PATH has none, rather
    than that directory answering for every other tool."""

    def _uv(self, home: Path, path: str) -> subprocess.CompletedProcess[str]:
        harness = (
            "set -euo pipefail\n"
            f'source "{REPO_ROOT / "scripts" / "install" / "venv.sh"}"\n'
            f'PATH="{path}"\n'
            "_venv_uv --version\n"
        )
        return _run(harness, _base_env(HOME=str(home)))

    def test_falls_back_to_the_installer_location(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        bin_dir = home / ".local" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "uv").write_text('#!/bin/sh\necho "home uv $*"\n', encoding="utf-8")
        (bin_dir / "uv").chmod(0o755)
        empty = tmp_path / "empty-bin"
        empty.mkdir()

        result = self._uv(home, str(empty))

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "home uv --version"

    def test_a_uv_on_path_wins(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        on_path = tmp_path / "path-bin"
        on_path.mkdir()
        (on_path / "uv").write_text('#!/bin/sh\necho "path uv"\n', encoding="utf-8")
        (on_path / "uv").chmod(0o755)

        result = self._uv(home, str(on_path))

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "path uv"

    def test_no_uv_anywhere_fails_loudly(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        empty = tmp_path / "empty-bin"
        empty.mkdir()

        result = self._uv(home, str(empty))

        assert result.returncode != 0
        assert "uv" in result.stderr


class TestLayer2SourcesItFirst:
    def test_upgrade_version_sh_sanitises_before_sourcing_any_other_library(self) -> None:
        """The library must be sourced, and the function called, before the
        `install/*.sh` library sources -- otherwise a hostile `BASH_ENV`/`ENV`
        has already run by the time this script tries to neutralise it."""
        content = (REPO_ROOT / "scripts" / "upgrade_version.sh").read_text(encoding="utf-8")

        sanitise_source_index = content.index('source "$INSTALL_LIB_DIR/env_sanitise.sh"')
        call_index = content.index("_sanitise_layer2_env\n", sanitise_source_index)
        first_other_library_index = content.index('source "$INSTALL_LIB_DIR/output.sh"')

        assert sanitise_source_index < call_index < first_other_library_index
