"""Parity integration test: bash and Python helpers MUST produce identical fingerprints.

Plan 00099: the venv keying scheme requires that
`scripts/install/python_fingerprint.sh` and
`claude_code_hooks_daemon.daemon.paths.python_venv_fingerprint()` produce
byte-identical output when given the same Python interpreter. The bash side
runs during install (before the venv is created, using system python3); the
Python side runs inside the daemon (from within the venv). Any divergence
would cause the bash-installed venv to land at a different path than the one
the Python daemon tries to activate, bricking startup.

These tests invoke both helpers as real subprocesses and assert equality.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _bash_fingerprint(
    python_bin: str,
    root: str | None = None,
    *,
    via_env: bool = False,
) -> str:
    """Invoke the bash helper against a specific Python interpreter.

    Args:
        python_bin: path to the Python interpreter to fingerprint
        root: optional project root; if given, prepends slug
        via_env: when True, pass ``root`` through ``HOOKS_DAEMON_ROOT_DIR``
            env var instead of the positional argument
    """
    if root is None:
        command = f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}"'
        env = None
    elif via_env:
        command = f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}"'
        import os

        env = {**os.environ, "HOOKS_DAEMON_ROOT_DIR": root}
    else:
        command = f'source "{BASH_HELPER}" && python_venv_fingerprint "{python_bin}" "{root}"'
        env = None

    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _python_fingerprint(python_bin: str, root: str | None = None) -> str:
    """Invoke python_venv_fingerprint() via the Python import under the given interpreter."""
    if root is None:
        snippet = (
            "from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint; "
            "print(python_venv_fingerprint())"
        )
    else:
        snippet = (
            "from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint; "
            f"print(python_venv_fingerprint({root!r}))"
        )
    result = subprocess.run(
        [python_bin, "-c", snippet],
        capture_output=True,
        text=True,
        check=True,
        cwd=str(REPO_ROOT),
    )
    return result.stdout.strip()


class TestBashHelperExists:
    """Preflight: the bash helper must exist and be executable."""

    def test_bash_helper_exists(self) -> None:
        assert BASH_HELPER.exists(), f"Missing bash helper: {BASH_HELPER}"

    def test_bash_helper_is_executable(self) -> None:
        assert BASH_HELPER.stat().st_mode & 0o111, "Bash helper is not executable"


class TestBashPythonParity:
    """Bash and Python helpers MUST produce identical fingerprints."""

    def test_parity_for_current_interpreter(self) -> None:
        """Running interpreter: bash-side and Python-side match exactly."""
        bash_fp = _bash_fingerprint(sys.executable)
        py_fp = _python_fingerprint(sys.executable)
        assert bash_fp == py_fp, f"Parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"

    def test_fingerprint_format(self) -> None:
        """Both helpers emit the documented `pyMM-XXXXXXXX` format."""
        import re

        fp = _bash_fingerprint(sys.executable)
        assert re.match(r"^py\d{2,3}-[0-9a-f]{8}$", fp), f"Bad format: {fp}"

    def test_a_venv_fingerprints_identically_to_the_interpreter_that_created_it(
        self, tmp_path: Path
    ) -> None:
        """The crucial property: a base interpreter and a venv built FROM it agree.

        bash-side runs during install using the base python BEFORE the venv
        exists; Python-side runs AFTER the venv is active. A divergence would
        put the installed venv at a different path than the one the daemon
        activates, bricking startup.

        The pair is CONSTRUCTED here rather than assumed from the ambient
        interpreter. The previous version compared ``/usr/bin/python3`` against
        whatever ``sys.executable`` happened to be, guarded by
        ``sysconfig.get_config_var("prefix") != get_config_var("base_prefix")``
        — and ``get_config_var("base_prefix")`` is always ``None``, so the guard
        was always true and never guarded anything. It passed locally only
        because the dogfood venv's base genuinely is ``/usr``; on a CI runner
        ``sys.executable`` is a hostedtoolcache python that no more descends
        from ``/usr/bin/python3`` than any other unrelated interpreter, so the
        fingerprints differed CORRECTLY and the test failed for a real property
        it was never testing (Plan 00245).
        """
        venv_dir = tmp_path / "constructed-venv"
        # --without-pip: only an interpreter to fingerprint is needed, and it
        # keeps this off the network so the parity property is verified even
        # where an install would not be possible.
        creation = subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert creation.returncode == 0, f"could not create venv: {creation.stderr}"

        venv_python = venv_dir / "bin" / "python"
        assert venv_python.exists(), f"venv has no interpreter at {venv_python}"

        # Non-vacuity: the second interpreter must really BE a venv of the
        # first, or this compares an interpreter with itself and would pass
        # against any implementation. This is the check the broken guard above
        # was reaching for — `sys.prefix != sys.base_prefix` is the canonical
        # in-a-venv test.
        prefixes = subprocess.run(
            [str(venv_python), "-c", "import sys; print(sys.prefix); print(sys.base_prefix)"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert prefixes[0] != prefixes[1], (
            f"constructed interpreter is not a venv (prefix == base_prefix == {prefixes[0]}); "
            "the parity assertion below would be vacuous"
        )

        base_fp = _bash_fingerprint(sys.executable)
        venv_fp = _bash_fingerprint(str(venv_python))
        assert base_fp == venv_fp, (
            f"A venv must fingerprint identically to the interpreter that created it!\n"
            f"  base ({sys.executable}): {base_fp}\n"
            f"  venv ({venv_python}): {venv_fp}"
        )

    def test_unrelated_interpreters_do_not_share_a_fingerprint(self) -> None:
        """The converse: two interpreters with different bases must NOT collide.

        This is what the fingerprint is FOR — two interpreters sharing only a
        major.minor version must key to separate venvs. It is also the exact
        shape a CI runner has (a hostedtoolcache python alongside the distro's
        ``/usr/bin/python3``), so the situation that used to fail this file is
        now asserted as correct behaviour rather than merely tolerated.
        """
        system_python = "/usr/bin/python3"
        if not Path(system_python).exists():
            pytest.skip(f"{system_python} unavailable in this environment")

        base_prefix_of = "import sys; print(sys.base_prefix)"
        system_base = subprocess.run(
            [system_python, "-c", base_prefix_of], capture_output=True, text=True, check=True
        ).stdout.strip()
        running_base = subprocess.run(
            [sys.executable, "-c", base_prefix_of], capture_output=True, text=True, check=True
        ).stdout.strip()

        if system_base == running_base:
            pytest.skip(
                f"{system_python} and {sys.executable} share base_prefix {system_base!r} — "
                "no unrelated pair available here, which the sibling test already covers"
            )

        assert _bash_fingerprint(system_python) != _bash_fingerprint(sys.executable), (
            f"Interpreters with different bases must key to DIFFERENT venvs!\n"
            f"  {system_python} (base {system_base})\n"
            f"  {sys.executable} (base {running_base})"
        )


class TestBashPythonSlugParity:
    """Plan 00100 Task 3.0.5: slug-prefixed fingerprints must also match.

    When a project root is supplied, both helpers must emit
    ``{slug}-py{MM}-{hash}`` with byte-identical slug and hash components so
    that the bash-installed venv and the Python-resolved venv land at the
    same directory.
    """

    def test_slug_parity_via_positional_arg(self, tmp_path: Path) -> None:
        """Bash (positional) and Python produce matching slug-prefixed fingerprints."""
        bash_fp = _bash_fingerprint(sys.executable, root=str(tmp_path))
        py_fp = _python_fingerprint(sys.executable, root=str(tmp_path))
        assert bash_fp == py_fp, f"Slug parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"

    def test_slug_parity_via_env_var(self, tmp_path: Path) -> None:
        """Bash (via HOOKS_DAEMON_ROOT_DIR env) matches Python with the same root."""
        bash_fp = _bash_fingerprint(sys.executable, root=str(tmp_path), via_env=True)
        py_fp = _python_fingerprint(sys.executable, root=str(tmp_path))
        assert (
            bash_fp == py_fp
        ), f"Slug-via-env parity violation!\n  bash: {bash_fp}\n  python: {py_fp}"

    def test_slug_positional_and_env_equivalent(self, tmp_path: Path) -> None:
        """Passing root positionally or via env var yields the same output."""
        fp_positional = _bash_fingerprint(sys.executable, root=str(tmp_path))
        fp_env = _bash_fingerprint(sys.executable, root=str(tmp_path), via_env=True)
        assert fp_positional == fp_env

    def test_slug_fingerprint_format(self, tmp_path: Path) -> None:
        """Format is ``{slug}-py{MM}-{8-hex}`` when root is supplied."""
        import re

        fp = _bash_fingerprint(sys.executable, root=str(tmp_path))
        assert re.match(r"^[A-Za-z0-9_-]+-py\d{2,3}-[0-9a-f]{8}$", fp), f"Bad format: {fp}"

    def test_distinct_roots_produce_distinct_fingerprints(self, tmp_path: Path) -> None:
        """Host-vs-container case: different roots -> different venvs."""
        root_a = tmp_path / "view_a"
        root_b = tmp_path / "view_b"
        root_a.mkdir()
        root_b.mkdir()

        fp_a = _bash_fingerprint(sys.executable, root=str(root_a))
        fp_b = _bash_fingerprint(sys.executable, root=str(root_b))
        assert fp_a != fp_b, (
            f"Distinct roots must produce distinct fingerprints!\n"
            f"  root_a ({root_a}): {fp_a}\n  root_b ({root_b}): {fp_b}"
        )

    def test_bare_fingerprint_still_unchanged(self) -> None:
        """Without root: bash still emits legacy ``py{MM}-{hash}`` (no slug)."""
        import re

        fp = _bash_fingerprint(sys.executable)
        assert re.match(
            r"^py\d{2,3}-[0-9a-f]{8}$", fp
        ), f"No-root invocation must preserve legacy format, got: {fp}"
