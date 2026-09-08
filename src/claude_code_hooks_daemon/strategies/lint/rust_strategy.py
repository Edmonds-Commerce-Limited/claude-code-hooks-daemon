"""Rust lint strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# Language-specific constants
_LANGUAGE_NAME = "Rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-lint-rust"
#: Both commands share this framing. `clippy-driver` is a rustc wrapper, so it
#: defaults to a BINARY crate and rejects any library-shaped file with E0601
#: "main function not found" — including this strategy's own "valid code
#: passes" probe. Only a machine with the clippy component genuinely installed
#: ever sees it, which is why a rustup-shim box (and so this project's CI until
#: Plan 00250 gave it a daemon) reported the command working.
_CRATE_FRAMING = (
    "--edition 2021 --crate-type lib --emit=metadata "
    "--out-dir /tmp/claude-hooks-daemon-rust-lint"
)
_DEFAULT_LINT_COMMAND = f"rustc {_CRATE_FRAMING} {{file}}"
_EXTENDED_LINT_COMMAND = f"clippy-driver {_CRATE_FRAMING} {{file}}"
# rustup ships a `clippy-driver` SHIM on PATH even when the `clippy` component
# is not installed. The shim resolves and runs (so it never raises
# FileNotFoundError, the handler's usual "tool absent" signal) but exits
# non-zero with this message -- a launcher reporting the real tool is
# missing, not a genuine lint failure against the file's content.
_RUSTUP_SHIM_NOT_INSTALLED_MARKER = "is not installed for the toolchain"


class RustLintStrategy:
    """Lint enforcement strategy for Rust files.

    Default: rustc syntax check via ``--emit=metadata --out-dir``. This
    works on stable rustc (unlike ``-Z parse-only``, which requires a
    nightly toolchain and denies every .rs write on stable) and writes the
    compiled metadata to a shared scratch directory instead of next to the
    user's file. ``-o /dev/null`` was tried first but fails in some
    sandboxes where rustc cannot rename its temp output onto the device
    node ("Device or resource busy").
    Extended: clippy-driver (comprehensive linting)
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def default_lint_command(self) -> str:
        return _DEFAULT_LINT_COMMAND

    @property
    def extended_lint_command(self) -> str | None:
        return _EXTENDED_LINT_COMMAND

    @property
    def skip_paths(self) -> tuple[str, ...]:
        # "target/" is already in COMMON_SKIP_PATHS (Plan 00288 Task 3.2 --
        # was a redundant duplicate here, dropped).
        return COMMON_SKIP_PATHS

    def is_tool_unavailable_output(self, output: str) -> bool:
        """Recognise the rustup clippy-driver shim's "not installed" output.

        See ``_RUSTUP_SHIM_NOT_INSTALLED_MARKER`` for why this exists: the
        shim runs successfully (no FileNotFoundError) but reports the real
        clippy component is absent, which must degrade to an advisory ALLOW
        rather than deny a valid file for a tool the box never had.
        """
        return _RUSTUP_SHIM_NOT_INSTALLED_MARKER in output

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Rust lint strategy."""
        from claude_code_hooks_daemon.constants import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)
        probe_valid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "valid.rs")),
                "content": "pub fn hello() {}",
            },
        )
        probe_invalid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": str(scratch_path(_FIXTURE_DIR, "invalid.rs")),
                "content": "pub fn hello( {}",
            },
        )

        return [
            AcceptanceTest(
                title="Rust lint - valid code passes",
                command=probe_valid.as_instruction(),
                tool_payload=probe_valid,
                description="Valid Rust code should pass lint validation",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Creates temporary Rust file."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Rust lint - invalid code blocked",
                command=probe_invalid.as_instruction(),
                tool_payload=probe_invalid,
                description="Invalid Rust code (missing closing paren) should be blocked",
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"Rust lint FAILED", r"invalid.rs"],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. "
                    "Creates temporary Rust file with syntax error."
                ),
                test_type=TestType.BLOCKING,
                required_tools=["rustc"],
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
