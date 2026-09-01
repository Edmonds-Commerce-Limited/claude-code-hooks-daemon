"""Tests for Rust lint strategy."""

import shutil
import subprocess  # nosec B404 - subprocess used for lint validation only (trusted tools)
import tempfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.strategies.lint.protocol import (
    ClassifiesToolUnavailable,
    LintStrategy,
)
from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy


@pytest.fixture()
def strategy() -> RustLintStrategy:
    return RustLintStrategy()


class TestProtocolConformance:
    def test_implements_protocol(self, strategy: RustLintStrategy) -> None:
        assert isinstance(strategy, LintStrategy)

    def test_implements_classifies_tool_unavailable(self, strategy: RustLintStrategy) -> None:
        assert isinstance(strategy, ClassifiesToolUnavailable)


class TestProperties:
    def test_language_name(self, strategy: RustLintStrategy) -> None:
        assert strategy.language_name == "Rust"

    def test_extensions(self, strategy: RustLintStrategy) -> None:
        assert strategy.extensions == (".rs",)

    def test_default_lint_command(self, strategy: RustLintStrategy) -> None:
        # `-Z parse-only` is nightly-only and denies every .rs write on a
        # stable toolchain (acceptance Test 128). `--emit=metadata --out-dir`
        # performs the same syntax/type check and works on stable rustc.
        assert strategy.default_lint_command == (
            "rustc --edition 2021 --crate-type lib --emit=metadata "
            "--out-dir /tmp/claude-hooks-daemon-rust-lint {file}"
        )

    def test_default_lint_command_does_not_use_nightly_only_flag(
        self, strategy: RustLintStrategy
    ) -> None:
        assert "-Z" not in strategy.default_lint_command

    def test_extended_lint_command(self, strategy: RustLintStrategy) -> None:
        assert strategy.extended_lint_command == "clippy-driver {file}"

    def test_skip_paths_contains_target(self, strategy: RustLintStrategy) -> None:
        assert any("target" in p for p in strategy.skip_paths)


class TestIsToolUnavailableOutput:
    """Acceptance Test 128, cycle 2: rustup's clippy-driver shim false-denies.

    The shim resolves on PATH and runs successfully (no FileNotFoundError)
    even when the `clippy` component was never installed, then exits
    non-zero reporting that fact -- which must be classified as
    tool-unavailable, not a genuine lint failure.
    """

    def test_recognises_rustup_shim_not_installed_message(self, strategy: RustLintStrategy) -> None:
        output = (
            "error: 'clippy-driver' is not installed for the toolchain "
            "'stable-x86_64-unknown-linux-gnu'.\n"
            "To install, run `rustup component add clippy`\n"
        )
        assert strategy.is_tool_unavailable_output(output) is True

    def test_genuine_clippy_finding_is_not_classified_as_unavailable(
        self, strategy: RustLintStrategy
    ) -> None:
        output = (
            "warning: this `if` has identical blocks\n"
            " --> src/lib.rs:2:13\n"
            "error: could not compile due to previous error\n"
        )
        assert strategy.is_tool_unavailable_output(output) is False

    def test_empty_output_is_not_classified_as_unavailable(
        self, strategy: RustLintStrategy
    ) -> None:
        assert strategy.is_tool_unavailable_output("") is False


class TestAcceptanceTests:
    def test_returns_list(self, strategy: RustLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert isinstance(tests, list)

    def test_returns_at_least_one_test(self, strategy: RustLintStrategy) -> None:
        tests = strategy.get_acceptance_tests()
        assert len(tests) >= 1


@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
class TestRealRustcIntegration:
    """Runs the actual default_lint_command against a real rustc.

    Guards against the acceptance Test 128 regression: `-Z parse-only`
    is nightly-only and denies every valid .rs write on a stable
    toolchain. These tests exercise the real command end-to-end rather
    than mocking subprocess, so a future stable-incompatible flag would
    fail here even if unit tests mocking subprocess did not catch it.
    """

    def _run(
        self, strategy: RustLintStrategy, source: str, filename: str
    ) -> "subprocess.CompletedProcess[str]":
        with tempfile.TemporaryDirectory() as tmp_dir:
            rs_file = Path(tmp_dir) / filename
            rs_file.write_text(source)
            command = strategy.default_lint_command.replace("{file}", str(rs_file))
            return subprocess.run(  # nosec B603 - rustc is trusted, args built from test fixtures
                command.split(),
                capture_output=True,
                text=True,
                timeout=Timeout.REQUEST_DEFAULT,
            )

    def test_valid_rust_passes_on_stable_toolchain(self, strategy: RustLintStrategy) -> None:
        result = self._run(strategy, "pub fn hello() {}", "valid.rs")
        assert result.returncode == 0, result.stderr
        assert "only accepted on the nightly compiler" not in result.stderr

    def test_invalid_rust_fails_with_real_syntax_error(self, strategy: RustLintStrategy) -> None:
        result = self._run(strategy, "pub fn hello( {}", "invalid.rs")
        assert result.returncode != 0
        assert "unclosed delimiter" in result.stderr


@pytest.mark.skipif(shutil.which("clippy-driver") is None, reason="clippy-driver not on PATH")
class TestRealClippyDriverIntegration:
    """Runs the actual extended_lint_command against whatever clippy-driver

    is really on this box's PATH. On a rustup install with the `clippy`
    component NOT added, `clippy-driver` is a SHIM that stays resolvable
    but exits non-zero reporting the component is missing (acceptance
    Test 128, cycle 2) -- that output must classify as tool-unavailable.
    On a box where the component IS installed, this instead exercises the
    real-clippy path and documents that genuine findings are unaffected.
    """

    def _run_extended(
        self, strategy: RustLintStrategy, source: str, filename: str
    ) -> "subprocess.CompletedProcess[str]":
        assert strategy.extended_lint_command is not None
        with tempfile.TemporaryDirectory() as tmp_dir:
            rs_file = Path(tmp_dir) / filename
            rs_file.write_text(source)
            command = strategy.extended_lint_command.replace("{file}", str(rs_file))
            return subprocess.run(  # nosec B603 - clippy-driver is trusted, args from test fixtures
                command.split(),
                capture_output=True,
                text=True,
                timeout=Timeout.REQUEST_DEFAULT,
            )

    def test_shim_or_real_clippy_output_classified_correctly(
        self, strategy: RustLintStrategy
    ) -> None:
        result = self._run_extended(strategy, "pub fn hello() {}", "valid.rs")
        combined_output = result.stdout + result.stderr

        if result.returncode == 0:
            # Real clippy installed and the valid file has no findings --
            # nothing to classify, this box cannot reproduce the shim bug.
            return

        # Non-zero: either the rustup shim reporting absence, or a real
        # clippy finding against admittedly-valid code (unexpected but
        # possible with a stricter default lint level). Either way the
        # classification here must match what a live lint_on_edit run would
        # decide: shim absence degrades gracefully, a real finding does not.
        is_shim_absence = strategy.is_tool_unavailable_output(combined_output)
        if "is not installed for the toolchain" in combined_output:
            assert is_shim_absence is True
        else:
            assert is_shim_absence is False
