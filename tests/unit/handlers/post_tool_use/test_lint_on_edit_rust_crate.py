"""lint_on_edit runs Rust from the owning crate (GitHub #76).

Mocked tests pin the command shape (working directory, edition as one argv
element, override templates). Live tests run a real ``rustc`` and are skipped
where it is not installed.
"""

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler

_SUBPROCESS = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess"

_requires_rustc = pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")


@pytest.fixture()
def handler() -> LintOnEditHandler:
    return LintOnEditHandler()


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _hook_input(path: Path) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def _ok_result() -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


def _edition_2024_crate(root: Path) -> dict[str, Path]:
    """The report's reproduction: let chain, sibling import, integration test."""
    _write(
        root / "Cargo.toml",
        '[package]\nname = "widget"\nversion = "0.1.0"\nedition = "2024"\n',
    )
    return {
        "lib": _write(root / "src" / "lib.rs", "pub mod a;\npub mod b;\n"),
        "a": _write(
            root / "src" / "a.rs",
            "pub fn thing(x: Option<u32>) -> bool {\n"
            "    if let Some(v) = x && v > 1 {\n"
            "        return true;\n"
            "    }\n"
            "    false\n"
            "}\n",
        ),
        "b": _write(
            root / "src" / "b.rs",
            "use crate::a::thing;\n\npub fn run() -> bool {\n    thing(Some(2))\n}\n",
        ),
        "test": _write(
            root / "tests" / "a_test.rs",
            "use widget::a::thing;\n\n#[test]\nfn works() {\n    assert!(thing(Some(2)));\n}\n",
        ),
    }


class TestCommandShape:
    @patch(_SUBPROCESS)
    def test_runs_from_the_owning_crate(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path / "workspace" / "widget")
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(crate["b"]))

        assert mock_subprocess.run.call_args[1]["cwd"] == str(tmp_path / "workspace" / "widget")

    @patch(_SUBPROCESS)
    def test_edition_enters_argv_as_one_validated_element(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path)
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(crate["a"]))

        argv = mock_subprocess.run.call_args[0][0]
        assert argv[argv.index("--edition") + 1] == "2024"
        assert "{edition}" not in argv
        assert argv[-1] == str(crate["a"])

    @patch(_SUBPROCESS)
    def test_hostile_edition_text_never_reaches_argv(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _write(
            tmp_path / "Cargo.toml",
            '[package]\nname = "x"\nedition = "2024 --out-dir /tmp/evil"\n',
        )
        source = _write(tmp_path / "src" / "lib.rs", "pub fn f() {}\n")
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(source))

        argv = mock_subprocess.run.call_args[0][0]
        assert argv[argv.index("--edition") + 1] == "2021"
        assert not any("evil" in part for part in argv)

    @patch(_SUBPROCESS)
    def test_loose_file_keeps_the_standalone_framing(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        source = _write(tmp_path / "loose.rs", "pub fn f() {}\n")
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(source))

        argv = mock_subprocess.run.call_args[0][0]
        assert argv[argv.index("--edition") + 1] == "2021"
        assert argv[argv.index("--crate-type") + 1] == "lib"

    @patch(_SUBPROCESS)
    def test_override_with_placeholder_is_substituted(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        handler._command_overrides = {"Rust": {"default": "rustc --edition {edition} {file}"}}
        crate = _edition_2024_crate(tmp_path)
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(crate["a"]))

        argv = mock_subprocess.run.call_args_list[0][0][0]
        assert argv[1:] == ["--edition", "2024", str(crate["a"])]

    @patch(_SUBPROCESS)
    def test_override_without_placeholder_still_works(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        handler._command_overrides = {"Rust": {"default": "rustc --edition 2018 {file}"}}
        crate = _edition_2024_crate(tmp_path)
        mock_subprocess.run.return_value = _ok_result()

        handler.handle(_hook_input(crate["a"]))

        argv = mock_subprocess.run.call_args_list[0][0][0]
        assert argv[1:] == ["--edition", "2018", str(crate["a"])]


class TestCrateContextErrorsAllow:
    @patch(_SUBPROCESS)
    def test_unresolved_import_is_allowed_with_an_advisory(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path)
        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = "error[E0432]: unresolved import `crate::a`\n"
        mock_subprocess.run.return_value = failed

        result = handler.handle(_hook_input(crate["b"]))

        assert result.decision.value == "allow"
        assert "NOT checked" in " ".join(result.context)

    @patch(_SUBPROCESS)
    def test_type_error_still_denies(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path)
        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        failed.stderr = "error[E0308]: mismatched types\n"
        mock_subprocess.run.return_value = failed

        assert handler.handle(_hook_input(crate["b"])).decision.value == "deny"


@_requires_rustc
class TestLiveRustc:
    def test_the_reports_reproduction_is_allowed(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path)
        for name in ("lib", "a", "b", "test"):
            result = handler.handle(_hook_input(crate[name]))
            assert result.decision.value == "allow", (name, result.reason)

    def test_let_chain_needs_the_crates_edition(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        """Without the 2024 edition a let chain is an error, so this proves it is read."""
        crate = _edition_2024_crate(tmp_path)
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "widget"\nedition = "2021"\n')
        assert handler.handle(_hook_input(crate["a"])).decision.value == "deny"

    def test_syntax_error_in_a_crate_is_denied(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        crate = _edition_2024_crate(tmp_path)
        broken = _write(tmp_path / "src" / "broken.rs", "use crate::a::thing;\npub fn f( {}\n")
        result = handler.handle(_hook_input(broken))
        assert result.decision.value == "deny"
        assert "Rust lint FAILED" in (result.reason or "")
        assert crate["a"].exists()

    def test_loose_file_without_cargo_toml_behaves_as_before(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        good = _write(tmp_path / "good.rs", "pub fn hello() {}\n")
        bad = _write(tmp_path / "bad.rs", "pub fn hello( {}\n")
        assert handler.handle(_hook_input(good)).decision.value == "allow"
        assert handler.handle(_hook_input(bad)).decision.value == "deny"

    def test_loose_file_with_a_let_chain_is_still_an_edition_2021_error(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        source = _write(
            tmp_path / "chain.rs",
            "pub fn f(x: Option<u32>) -> bool {\n    if let Some(v) = x && v > 1 { true } else { false }\n}\n",
        )
        assert handler.handle(_hook_input(source)).decision.value == "deny"
