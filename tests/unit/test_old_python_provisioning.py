"""``tests/old_python.py`` provisions an old interpreter through ``uv`` (Plan 00546 Task 3.1).

The old-interpreter tests are a standing gate only if they do not skip when an
interpreter is merely missing. With ``uv`` present the helper installs the
version; it skips only when ``uv`` itself is absent, and the skip reason names
that cause. A failed install is a failure, never a skip.
"""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from tests import old_python


def _completed(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class _FakeUv:
    """Records ``uv python`` calls; ``find`` succeeds only after ``install`` ran."""

    def __init__(self, install_returncode: int = 0) -> None:
        self.calls: list[str] = []
        self.install_returncode = install_returncode
        self.installed = False

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        action = cmd[2]
        self.calls.append(action)
        if action == "install":
            self.installed = self.install_returncode == 0
            return _completed(self.install_returncode, stderr="network down")
        if self.installed:
            return _completed(0, stdout="/uv/python3.9\n")
        return _completed(1)


class TestFindOldPython:
    def test_prefers_an_interpreter_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(old_python.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert old_python.find_old_python("3.9") == "/usr/bin/python3.9"

    def test_installs_through_uv_when_find_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = _FakeUv()
        monkeypatch.setattr(
            old_python.shutil, "which", lambda name: "/bin/uv" if name == "uv" else None
        )
        monkeypatch.setattr(old_python.subprocess, "run", fake)
        assert old_python.find_old_python("3.9") == "/uv/python3.9"
        assert fake.calls == ["find", "install", "find"]

    def test_returns_none_only_when_uv_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(old_python.shutil, "which", lambda name: None)
        assert old_python.find_old_python("3.9") is None

    def test_a_failed_install_raises_with_uv_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            old_python.shutil, "which", lambda name: "/bin/uv" if name == "uv" else None
        )
        monkeypatch.setattr(old_python.subprocess, "run", _FakeUv(install_returncode=2))
        with pytest.raises(old_python.OldPythonProvisionError, match="network down"):
            old_python.find_old_python("3.9")


class TestOldPythonOrSkip:
    def test_skip_reason_names_the_missing_uv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(old_python.shutil, "which", lambda name: None)
        with pytest.raises(pytest.skip.Exception, match="uv is not installed"):
            old_python.old_python_or_skip("3.9")

    def test_a_failed_install_fails_instead_of_skipping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            old_python.shutil, "which", lambda name: "/bin/uv" if name == "uv" else None
        )
        monkeypatch.setattr(old_python.subprocess, "run", _FakeUv(install_returncode=2))
        with pytest.raises(pytest.fail.Exception, match="could not be provisioned"):
            old_python.old_python_or_skip("3.9")
