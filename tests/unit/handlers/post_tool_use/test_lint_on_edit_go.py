"""lint_on_edit's Go path: a change split across edits is not denied half-way.

Field report (fedora-desktop, v3.69.0): adding a call in one Edit and its import
in the next drew a deny on the first, "vet: integration_test.go:48:12: undefined:
syscall". Live tests run the real Go toolchain and are skipped where it is absent.
"""

import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit import LintOnEditHandler

_SUBPROCESS = "claude_code_hooks_daemon.handlers.post_tool_use.lint_on_edit.subprocess"

_requires_go = pytest.mark.skipif(
    shutil.which("go") is None or shutil.which("gofmt") is None, reason="go not installed"
)


@pytest.fixture()
def handler() -> LintOnEditHandler:
    # The extended tier is golangci-lint, which must never be required (and may
    # be absent or present on the machine running this); the plain toolchain is
    # what these tests pin.
    instance = LintOnEditHandler()
    instance._command_overrides = {"Go": {"extended": None}}
    return instance


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _hook_input(path: Path) -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def _module(root: Path) -> Path:
    return _write(root / "go.mod", "module example.com/m\n\ngo 1.19\n")


def _failed(stderr: str) -> MagicMock:
    result = MagicMock()
    result.returncode = 2
    result.stdout = ""
    result.stderr = stderr
    return result


def _ok() -> MagicMock:
    result = MagicMock()
    result.returncode = 0
    result.stdout = ""
    result.stderr = ""
    return result


class TestMockedShapes:
    @patch(_SUBPROCESS)
    def test_the_field_reports_undefined_is_allowed_with_the_finding_shown(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "integration_test.go", "package m\n")
        mock_subprocess.run.side_effect = [
            _ok(),
            _failed("# example.com/m\nvet: ./integration_test.go:48:12: undefined: syscall\n"),
        ]

        result = handler.handle(_hook_input(target))

        assert result.decision.value == "allow"
        joined = " ".join(result.context)
        assert "undefined: syscall" in joined
        assert "NOT denied" in joined

    @patch(_SUBPROCESS)
    def test_newer_go_declared_and_not_used_with_a_name_is_allowed(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "c.go", "package m\n")
        mock_subprocess.run.side_effect = [
            _ok(),
            _failed("# example.com/m\n./c.go:3:12: declared and not used: x\n"),
        ]

        result = handler.handle(_hook_input(target))

        assert result.decision.value == "allow"
        assert "declared and not used: x" in " ".join(result.context)

    @patch(_SUBPROCESS)
    def test_a_genuine_vet_finding_denies(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "d.go", "package m\n")
        mock_subprocess.run.side_effect = [
            _ok(),
            _failed(
                '# example.com/m\n./d.go:5:12: fmt.Printf format %d has arg "s" of wrong type\n'
            ),
        ]

        assert handler.handle(_hook_input(target)).decision.value == "deny"

    @patch(_SUBPROCESS)
    def test_a_gofmt_syntax_error_denies_before_vet_runs(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "f.go", "package m\n")
        mock_subprocess.run.return_value = _failed("f.go:3:9: expected ')', found '{'\n")

        result = handler.handle(_hook_input(target))

        assert result.decision.value == "deny"
        assert mock_subprocess.run.call_count == 1
        assert mock_subprocess.run.call_args[0][0][0].endswith("gofmt")

    @patch(_SUBPROCESS)
    def test_build_constraints_excluding_every_file_is_an_advisory(
        self, mock_subprocess: MagicMock, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "x.go", "package m\n")
        failed = _failed("package example.com/m: build constraints exclude all Go files in /x\n")
        failed.returncode = 1
        mock_subprocess.run.side_effect = [_ok(), failed]

        result = handler.handle(_hook_input(target))

        assert result.decision.value == "allow"
        assert "NOT checked" in " ".join(result.context)


@_requires_go
class TestLiveGoToolchain:
    def test_a_call_then_its_import_is_never_denied(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = tmp_path / "a.go"

        _write(target, "package m\n\nfunc A() int { return syscall.Getpid() }\n")
        first = handler.handle(_hook_input(target))
        assert first.decision.value == "allow", first.reason

        _write(
            target, 'package m\n\nimport "syscall"\n\nfunc A() int { return syscall.Getpid() }\n'
        )
        second = handler.handle(_hook_input(target))
        assert second.decision.value == "allow", second.reason

    def test_an_import_added_before_its_use_is_allowed(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "b.go", 'package m\n\nimport "os"\n\nfunc B() {}\n')
        assert handler.handle(_hook_input(target)).decision.value == "allow"

    def test_an_unused_variable_is_allowed_mid_edit(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "c.go", "package m\n\nfunc C() { x := 1 }\n")
        assert handler.handle(_hook_input(target)).decision.value == "allow"

    def test_printf_misuse_still_denies(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        _module(tmp_path)
        target = _write(
            tmp_path / "d.go",
            'package m\n\nimport "fmt"\n\nfunc D() { fmt.Printf("%d\\n", "s") }\n',
        )
        result = handler.handle(_hook_input(target))
        assert result.decision.value == "deny"
        assert "Go lint FAILED" in (result.reason or "")

    def test_a_syntax_error_still_denies(self, handler: LintOnEditHandler, tmp_path: Path) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "f.go", "package m\n\nfunc F( {\n")
        assert handler.handle(_hook_input(target)).decision.value == "deny"

    def test_a_syntax_error_denies_without_a_go_mod(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        target = _write(tmp_path / "f.go", "package m\n\nfunc F( {\n")
        assert handler.handle(_hook_input(target)).decision.value == "deny"

    def test_an_unformatted_file_is_not_denied(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "u.go", "package m\nfunc   U( ) {  }\n")
        assert handler.handle(_hook_input(target)).decision.value == "allow"

    def test_a_finding_only_in_a_sibling_file_does_not_deny_this_write(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        _write(
            tmp_path / "sibling.go",
            'package m\n\nimport "fmt"\n\nfunc S() { fmt.Printf("%d\\n", "s") }\n',
        )
        target = _write(tmp_path / "clean.go", "package m\n\nfunc Clean() {}\n")
        result = handler.handle(_hook_input(target))
        assert result.decision.value == "allow", result.reason
        assert "sibling.go" in " ".join(result.context)

    def test_a_finding_in_the_edited_file_still_denies_beside_a_sibling(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        _write(tmp_path / "clean.go", "package m\n\nfunc Clean() {}\n")
        target = _write(
            tmp_path / "bad.go",
            'package m\n\nimport "fmt"\n\nfunc D() { fmt.Printf("%d\\n", "s") }\n',
        )
        assert handler.handle(_hook_input(target)).decision.value == "deny"

    def test_a_package_whose_files_are_all_build_constrained_is_allowed(
        self, handler: LintOnEditHandler, tmp_path: Path
    ) -> None:
        _module(tmp_path)
        target = _write(tmp_path / "x.go", "//go:build ignore\n\npackage m\n")
        result = handler.handle(_hook_input(target))
        assert result.decision.value == "allow", result.reason
