"""N271 -- where the uv that builds the venv may come from.

What builds the venv decides what code the daemon runs, so Layer 2 never takes
a uv from the caller's PATH. The owner's ruling widens the fixed locations it
trusts (Homebrew's prefixes, pipx's bin directory) and lets the human name a uv
for one run with ``--uv <path>``, carried from Layer 1 to Layer 2 in the
one-shot handoff file. These tests run the real ``_venv_uv`` from
``scripts/install/venv.sh``, the real ``_read_handoff`` from
``scripts/upgrade_version.sh`` and the real argument parsing of
``scripts/upgrade.sh``.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"
LAYER1 = REPO_ROOT / "scripts" / "upgrade.sh"
LAYER2 = REPO_ROOT / "scripts" / "upgrade_version.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30


def _run(
    harness: str, env: dict[str, str], *, args: list[str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", harness, "harness", *(args or [])],
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )


def _fake_uv(directory: Path, label: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    uv = directory / "uv"
    uv.write_text(f'#!/bin/sh\necho "{label} $*"\n', encoding="utf-8")
    uv.chmod(0o755)
    return uv


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return home


def _uv_harness(setup: str = "") -> str:
    """Source the real venv.sh, then run `_venv_uv --version` with PATH emptied."""
    return (
        "set -euo pipefail\n"
        f'source "{VENV_SH}"\n'
        'PATH="$EMPTY_PATH"\n'
        f"{setup}\n"
        "_venv_uv --version\n"
    )


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    env = {"HOME": str(_home(tmp_path)), "PATH": "/usr/bin:/bin", "EMPTY_PATH": str(empty)}
    env.update(extra)
    return env


class TestPipxBinDir:
    """`$PIPX_BIN_DIR` is honoured when set; its default is `~/.local/bin`."""

    def test_uv_in_pipx_bin_dir_is_used(self, tmp_path: Path) -> None:
        pipx_bin = tmp_path / "pipx-bin"
        _fake_uv(pipx_bin, "pipx uv")
        pipx_bin.chmod(0o755)

        result = _run(_uv_harness(), _env(tmp_path, PIPX_BIN_DIR=str(pipx_bin)))

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "pipx uv --version"

    def test_a_group_writable_pipx_bin_dir_is_not_trusted(self, tmp_path: Path) -> None:
        pipx_bin = tmp_path / "pipx-bin"
        _fake_uv(pipx_bin, "pipx uv")
        pipx_bin.chmod(0o775)

        result = _run(_uv_harness(), _env(tmp_path, PIPX_BIN_DIR=str(pipx_bin)))

        assert result.returncode != 0
        assert "pipx uv" not in result.stdout

    def test_a_relative_pipx_bin_dir_is_ignored(self, tmp_path: Path) -> None:
        _fake_uv(tmp_path / "rel-bin", "relative uv")
        (tmp_path / "rel-bin").chmod(0o755)
        harness = _uv_harness(f'cd "{tmp_path}"')

        result = _run(harness, _env(tmp_path, PIPX_BIN_DIR="rel-bin"))

        assert result.returncode != 0
        assert "relative uv" not in result.stdout

    def test_the_default_location_still_answers(self, tmp_path: Path) -> None:
        env = _env(tmp_path)
        _fake_uv(Path(env["HOME"]) / ".local" / "bin", "home uv")

        result = _run(_uv_harness(), env)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "home uv --version"


class TestFixedSearchDirectories:
    """The fixed directories `_venv_uv` searches after the trusted PATH."""

    def _dirs(self, tmp_path: Path, **extra: str) -> list[str]:
        harness = f'source "{VENV_SH}"\n_venv_uv_search_dirs\n'
        result = _run(harness, _env(tmp_path, **extra))
        assert result.returncode == 0, result.stderr
        return result.stdout.splitlines()

    def test_homebrew_prefixes_are_searched(self, tmp_path: Path) -> None:
        dirs = self._dirs(tmp_path)

        assert "/opt/homebrew/bin" in dirs
        assert "/usr/local/bin" in dirs
        assert "/home/linuxbrew/.linuxbrew/bin" in dirs

    def test_the_default_pipx_location_is_searched(self, tmp_path: Path) -> None:
        env = _env(tmp_path)

        dirs = self._dirs(tmp_path)

        assert f"{env['HOME']}/.local/bin" in dirs

    def test_pipx_bin_dir_is_searched_when_set(self, tmp_path: Path) -> None:
        pipx_bin = tmp_path / "pipx-bin"
        pipx_bin.mkdir()
        pipx_bin.chmod(0o755)

        assert str(pipx_bin) in self._dirs(tmp_path, PIPX_BIN_DIR=str(pipx_bin))

    def test_the_callers_path_is_never_searched(self, tmp_path: Path) -> None:
        caller_bin = tmp_path / "caller-bin"
        caller_bin.mkdir()

        dirs = self._dirs(tmp_path, PATH=f"{caller_bin}:/usr/bin:/bin")

        assert str(caller_bin) not in dirs


class TestUvOverride:
    """`--uv <path>` reaches `_venv_uv` as `VENV_UV_OVERRIDE`, set by Layer 2
    after it sources venv.sh and never read from the inherited environment."""

    def test_the_override_wins_over_path_and_installer_location(self, tmp_path: Path) -> None:
        env = _env(tmp_path)
        _fake_uv(Path(env["HOME"]) / ".local" / "bin", "home uv")
        chosen = _fake_uv(tmp_path / "chosen", "chosen uv")

        result = _run(_uv_harness(f'VENV_UV_OVERRIDE="{chosen}"'), env)

        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "chosen uv --version"

    def test_an_inherited_override_is_ignored(self, tmp_path: Path) -> None:
        planted = _fake_uv(tmp_path / "planted", "planted uv")

        result = _run(_uv_harness(), _env(tmp_path, VENV_UV_OVERRIDE=str(planted)))

        assert result.returncode != 0
        assert "planted uv" not in result.stdout

    @pytest.mark.parametrize("bad", ["relative/uv", "/nonexistent/uv"])
    def test_a_bad_override_fails_naming_the_path(self, tmp_path: Path, bad: str) -> None:
        env = _env(tmp_path)
        _fake_uv(Path(env["HOME"]) / ".local" / "bin", "home uv")

        result = _run(_uv_harness(f'VENV_UV_OVERRIDE="{bad}"'), env)

        assert result.returncode != 0
        assert bad in result.stderr
        assert "home uv" not in result.stdout

    def test_an_override_that_is_not_executable_is_rejected(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain" / "uv"
        plain.parent.mkdir()
        plain.write_text("#!/bin/sh\necho plain\n", encoding="utf-8")
        plain.chmod(0o644)

        result = _run(_uv_harness(f'VENV_UV_OVERRIDE="{plain}"'), _env(tmp_path))

        assert result.returncode != 0
        assert str(plain) in result.stderr


class TestNotFoundMessage:
    def test_names_both_fixes(self, tmp_path: Path) -> None:
        result = _run(_uv_harness(), _env(tmp_path))

        assert result.returncode != 0
        assert "trusted location" in result.stderr
        assert "--uv <path>" in result.stderr


def _function_source(script: Path, name: str) -> str:
    text = script.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.DOTALL | re.MULTILINE)
    assert match is not None, f"{name} not found in {script}"
    return match.group(0)


class TestLayer2UvArgument:
    """Layer 2 takes `--uv <path>` among its trailing arguments (Layer 1 passes
    it there; the second pass forwards it) and sets `VENV_UV_OVERRIDE`."""

    def _take(self, *args: str) -> subprocess.CompletedProcess[str]:
        harness = (
            "set -euo pipefail\n"
            'fail_fast() { echo "FAIL $*" >&2; exit 1; }\n'
            'VENV_UV_OVERRIDE=""\n'
            f"{_function_source(LAYER2, '_take_uv_override')}\n"
            '_take_uv_override "$@"\n'
            'echo "override=[$VENV_UV_OVERRIDE]"\n'
        )
        return _run(harness, {"PATH": "/usr/bin:/bin"}, args=list(args))

    def test_the_space_spelling_is_taken(self, tmp_path: Path) -> None:
        uv = _fake_uv(tmp_path / "bin", "x")

        result = self._take("--skip-config-optimisation", "--uv", str(uv))

        assert result.stdout.strip() == f"override=[{uv}]"

    def test_the_equals_spelling_is_taken(self, tmp_path: Path) -> None:
        uv = _fake_uv(tmp_path / "bin", "x")

        assert self._take(f"--uv={uv}").stdout.strip() == f"override=[{uv}]"

    def test_no_argument_means_no_override(self) -> None:
        assert self._take("--skip-config-optimisation").stdout.strip() == "override=[]"

    @pytest.mark.parametrize("bad", ["relative/uv", "/nonexistent/uv"])
    def test_a_bad_path_stops_the_upgrade(self, bad: str) -> None:
        result = self._take("--uv", bad)

        assert result.returncode == 1
        assert bad in result.stderr

    def test_a_missing_value_stops_the_upgrade(self) -> None:
        result = self._take("--uv")

        assert result.returncode == 1
        assert "--uv requires" in result.stderr

    def test_layer1_forwards_it_as_an_argument_not_an_environment_variable(self) -> None:
        text = LAYER1.read_text(encoding="utf-8")

        assert '_LAYER2_ARGS+=(--uv "$UV_OVERRIDE")' in text
        assert "UV_OVERRIDE=" not in text[text.index("_LAYER2_ENV_ALLOWLIST=(") :].split(")")[0]


class TestLayer1UvArgument:
    """`upgrade.sh --uv <path>` accepts only an absolute path to an executable
    file, and says why when it is not."""

    def _layer1(self, tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = {"PATH": "/usr/bin:/bin", "HOME": str(_home(tmp_path))}
        return _run(f'bash "{LAYER1}" --project-root "{tmp_path}" "$@"', env, args=list(args))

    def test_a_relative_path_is_rejected(self, tmp_path: Path) -> None:
        result = self._layer1(tmp_path, "--uv", "bin/uv")

        assert result.returncode == 1
        assert "--uv" in result.stderr
        assert "absolute" in result.stderr

    def test_a_missing_file_is_rejected(self, tmp_path: Path) -> None:
        result = self._layer1(tmp_path, "--uv", str(tmp_path / "nope" / "uv"))

        assert result.returncode == 1
        assert "executable" in result.stderr

    def test_a_non_executable_file_is_rejected(self, tmp_path: Path) -> None:
        plain = tmp_path / "uv"
        plain.write_text("x", encoding="utf-8")
        plain.chmod(0o644)

        result = self._layer1(tmp_path, "--uv", str(plain))

        assert result.returncode == 1
        assert "executable" in result.stderr

    def test_a_missing_value_is_rejected(self, tmp_path: Path) -> None:
        result = self._layer1(tmp_path, "--uv")

        assert result.returncode == 1
        assert "--uv requires" in result.stderr

    def test_the_equals_spelling_is_validated_too(self, tmp_path: Path) -> None:
        result = self._layer1(tmp_path, "--uv=bin/uv")

        assert result.returncode == 1
        assert "absolute" in result.stderr

    def test_help_documents_it(self, tmp_path: Path) -> None:
        result = self._layer1(tmp_path, "--help")

        assert result.returncode == 0
        assert "--uv PATH" in result.stdout

    def test_pipx_bin_dir_survives_the_layer2_environment_reset(self) -> None:
        text = LAYER1.read_text(encoding="utf-8")
        kept = text[text.index("_LAYER2_KEPT_NAMES=(") :]
        kept = kept[: kept.index("\n        )\n")]

        assert "PIPX_BIN_DIR" in kept
