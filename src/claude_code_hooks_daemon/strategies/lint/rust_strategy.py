"""Rust lint strategy implementation."""

import logging
import re
import tomllib
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.strategies.lint.common import COMMON_SKIP_PATHS, lint_output_dir
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.path_predicates import path_is_file, read_text_or_reason
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

# Language-specific constants
_LANGUAGE_NAME = "Rust"
_EXTENSIONS: tuple[str, ...] = (".rs",)
#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR = "acceptance-test-lint-rust"
#: Both commands share this framing. `clippy-driver` is a rustc wrapper, so it
#: defaults to a BINARY crate and rejects any library-shaped file with E0601
#: "main function not found" — including this strategy's own "valid code
#: passes" probe. Only a machine with the clippy component genuinely installed
#: ever sees it, which is why a rustup-shim box (and so this project's CI until
#: Plan 00250 gave it a daemon) reported the command working.
#: `--out-dir` takes the shared per-process destination from
#: :func:`lint_output_dir` rather than a literal path in the temp directory,
#: which was predictable enough for another user on a shared host to
#: pre-create as a symlink.
#: ``{edition}`` is left in place: the handler fills it, per file, from
#: :meth:`RustLintStrategy.command_values` as one whole argv element.
_CRATE_FRAMING_TEMPLATE = (
    "--edition {{edition}} --crate-type lib --emit=metadata --out-dir {out_dir}"
)

#: Cargo's manifest, which names the crate that owns a file and its edition.
_MANIFEST_NAME = "Cargo.toml"
#: The only values that may reach argv as the edition. Anything else in a
#: manifest is ignored, so manifest text never becomes a compiler argument.
_KNOWN_EDITIONS: frozenset[str] = frozenset({"2015", "2018", "2021", "2024"})
#: A file with no usable manifest keeps the framing it always had.
_STANDALONE_EDITION = "2021"
#: What Cargo itself assumes when a package names no edition.
_CARGO_DEFAULT_EDITION = "2015"

#: rustc error codes that mean "this file cannot be resolved outside its
#: crate", not "this file is wrong": an unresolved import, a failed path or
#: undeclared crate/module, a crate that cannot be found, a module file that is
#: not found. Syntax errors stop rustc before name resolution, so they carry
#: none of these and still deny.
_CRATE_CONTEXT_ERROR = re.compile(r"error\[(?:E0432|E0433|E0463|E0583)\]")

logger = logging.getLogger(__name__)


def _crate_framing() -> str:
    """The framing both commands share, with the output directory resolved."""
    return _CRATE_FRAMING_TEMPLATE.format(out_dir=lint_output_dir())


def _find_manifest(start: Path) -> Path | None:
    """The nearest ``Cargo.toml`` in ``start`` or an ancestor."""
    for directory in (start, *start.parents):
        candidate = directory / _MANIFEST_NAME
        if path_is_file(candidate, unreadable_means=False):
            return candidate
    return None


def _load_manifest(manifest: Path) -> dict[str, Any] | None:
    """Parse a manifest, or None (logged) when it cannot be read or parsed."""
    loaded = read_text_or_reason(manifest, errors="replace")
    if loaded.text is None:
        logger.warning("rust lint: cannot read %s (%s)", manifest, loaded.reason)
        return None
    try:
        return tomllib.loads(loaded.text)
    except tomllib.TOMLDecodeError as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"rust lint: {manifest} is not valid TOML, so the edition falls back to the standalone framing rather than failing the write",
        )
    return None


def _inherits_workspace_edition(edition: object) -> bool:
    """Whether a package's ``edition`` is the ``{ workspace = true }`` form."""
    return isinstance(edition, dict) and edition.get("workspace") is True


def _workspace_edition(crate_manifest: Path) -> object:
    """``[workspace.package].edition`` of the nearest ancestor workspace root."""
    for directory in crate_manifest.parent.parents:
        candidate = directory / _MANIFEST_NAME
        if not path_is_file(candidate, unreadable_means=False):
            continue
        data = _load_manifest(candidate)
        if data is None:
            return None
        workspace = data.get("workspace")
        if isinstance(workspace, dict):
            package = workspace.get("package")
            return package.get("edition") if isinstance(package, dict) else None
    return None


def resolve_edition(file_path: str) -> str:
    """The Rust edition to compile ``file_path`` under.

    Read from the nearest ``Cargo.toml``: ``package.edition``, the workspace
    root's ``[workspace.package].edition`` when the package inherits it, or
    Cargo's own default when the package names none. A file with no manifest,
    an unreadable or malformed one, a manifest without a ``[package]`` table, or
    an edition outside :data:`_KNOWN_EDITIONS` keeps the standalone framing
    (logged where something was wrong), and this never raises: an unreadable
    manifest must degrade the check, not break the write.
    """
    manifest = _find_manifest(Path(file_path).parent)
    if manifest is None:
        return _STANDALONE_EDITION
    data = _load_manifest(manifest)
    if data is None:
        return _STANDALONE_EDITION
    package = data.get("package")
    if not isinstance(package, dict):
        return _STANDALONE_EDITION

    edition: object = package.get("edition", _CARGO_DEFAULT_EDITION)
    if _inherits_workspace_edition(edition):
        edition = _workspace_edition(manifest)

    if isinstance(edition, str) and edition in _KNOWN_EDITIONS:
        return edition
    logger.warning(
        "rust lint: unusable edition %r for %s, using %s", edition, manifest, _STANDALONE_EDITION
    )
    return _STANDALONE_EDITION


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
        return f"rustc {_crate_framing()} {{file}}"

    @property
    def extended_lint_command(self) -> str | None:
        return f"clippy-driver {_crate_framing()} {{file}}"

    @property
    def skip_paths(self) -> tuple[str, ...]:
        # "target/" is already in COMMON_SKIP_PATHS (Plan 00288 Task 3.2 --
        # was a redundant duplicate here, dropped).
        return COMMON_SKIP_PATHS

    def command_values(self, file_path: str) -> dict[str, str]:
        """The edition of the crate owning ``file_path`` (see :func:`resolve_edition`)."""
        return {"edition": resolve_edition(file_path)}

    def is_tool_unavailable_output(self, output: str) -> bool:
        """Recognise output that means the file could not be analysed, not that it is wrong.

        Two causes, both degrading to an advisory ALLOW:

        - rustup's clippy-driver shim runs successfully (no FileNotFoundError)
          but reports the real clippy component is absent
          (``_RUSTUP_SHIM_NOT_INSTALLED_MARKER``);
        - the file is a module of a Cargo crate linted on its own, so rustc
          cannot resolve its imports (``_CRATE_CONTEXT_ERROR``). Resolving them
          would need the whole crate graph, which this check does not build.
        """
        return _RUSTUP_SHIM_NOT_INSTALLED_MARKER in output or bool(
            _CRATE_CONTEXT_ERROR.search(output)
        )

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

        fixture_root = acceptance_path(_FIXTURE_DIR)
        probe_valid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "valid.rs"),
                "content": "pub fn hello() {}",
            },
        )
        probe_invalid = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "invalid.rs"),
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
                    "Inside the gitignored acceptance directory - safe. Creates temporary Rust file."
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
                    "Inside the gitignored acceptance directory - safe. "
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
