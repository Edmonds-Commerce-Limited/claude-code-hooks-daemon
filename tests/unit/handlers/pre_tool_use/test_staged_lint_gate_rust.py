"""staged_lint_gate runs Rust with the owning crate's edition (GitHub #76)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from tests.support.git_fixtures import git_setup_timeout

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate import StagedLintGateHandler
from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy

_RUN = "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate.subprocess.run"


@pytest.fixture(autouse=True)
def _reset_data_layer() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=git_setup_timeout(),
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


def _stage(repo: Path, relpath: str, content: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _git(repo, "add", relpath)


def _commit(handler: StagedLintGateHandler, repo: Path) -> Any:
    handler._mode = "block"
    target = (
        "claude_code_hooks_daemon.handlers.pre_tool_use.staged_lint_gate."
        "ProjectContext.project_root"
    )
    hook_input = {"tool_name": "Bash", "tool_input": {"command": 'git commit -m "x"'}}
    with patch(target, return_value=repo):
        return handler.handle(hook_input)


_CARGO = '[package]\nname = "widget"\nversion = "0.1.0"\nedition = "2024"\n'
_LET_CHAIN = (
    "pub fn thing(x: Option<u32>) -> bool {\n"
    "    if let Some(v) = x && v > 1 {\n        return true;\n    }\n    false\n}\n"
)


class TestSyntaxCheckCommand:
    def test_the_edition_is_filled_before_rustc_runs(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text(_CARGO)
        source = tmp_path / "src" / "a.rs"
        done = MagicMock(returncode=0, stdout="", stderr="")
        handler = StagedLintGateHandler()

        with (
            patch.object(handler, "_resolve_executable", return_value="/usr/bin/rustc"),
            patch(_RUN, return_value=done) as run,
        ):
            assert handler._syntax_check(str(source), RustLintStrategy()) is None

        argv = run.call_args[0][0]
        assert argv[argv.index("--edition") + 1] == "2024"
        assert not any("{" in part for part in argv)

    @pytest.mark.parametrize(
        "stderr",
        [
            "error[E0432]: unresolved import `crate::a`\n",
            "error[E0583]: file not found for module `x`\n",
            "error: 'clippy-driver' is not installed for the toolchain 'stable'.\n",
        ],
    )
    def test_could_not_analyse_output_is_not_a_finding(self, stderr: str, tmp_path: Path) -> None:
        failed = MagicMock(returncode=1, stdout="", stderr=stderr)
        handler = StagedLintGateHandler()

        with (
            patch.object(handler, "_resolve_executable", return_value="/usr/bin/rustc"),
            patch(_RUN, return_value=failed),
        ):
            assert handler._syntax_check(str(tmp_path / "a.rs"), RustLintStrategy()) is None

    def test_a_syntax_error_is_still_a_finding(self, tmp_path: Path) -> None:
        failed = MagicMock(returncode=1, stdout="", stderr="error: unclosed delimiter\n")
        handler = StagedLintGateHandler()

        with (
            patch.object(handler, "_resolve_executable", return_value="/usr/bin/rustc"),
            patch(_RUN, return_value=failed),
        ):
            assert "unclosed delimiter" in (
                handler._syntax_check(str(tmp_path / "a.rs"), RustLintStrategy()) or ""
            )


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
class TestLiveRustc:
    def test_a_valid_edition_2024_module_is_not_denied(self, repo: Path) -> None:
        _stage(repo, "Cargo.toml", _CARGO)
        _stage(repo, "src/lib.rs", "pub mod a;\npub mod b;\n")
        _stage(repo, "src/a.rs", _LET_CHAIN)
        _stage(repo, "src/b.rs", "use crate::a::thing;\npub fn run() -> bool { thing(None) }\n")
        _stage(repo, "tests/a_test.rs", "use widget::a::thing;\n#[test]\nfn t() { thing(None); }\n")

        result = _commit(StagedLintGateHandler(), repo)

        assert result.decision == Decision.ALLOW, result.reason

    def test_a_staged_syntax_error_is_still_denied(self, repo: Path) -> None:
        _stage(repo, "Cargo.toml", _CARGO)
        _stage(repo, "src/broken.rs", "pub fn f( {}\n")

        result = _commit(StagedLintGateHandler(), repo)

        assert result.decision == Decision.DENY
        assert "broken.rs" in (result.reason or "")
