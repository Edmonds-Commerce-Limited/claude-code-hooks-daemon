"""Rust lint strategy: edition from the owning Cargo.toml, crate-context errors.

GitHub #76: the strategy framed every ``.rs`` file as a standalone edition-2021
library crate, so valid modules of a Cargo crate were denied.
"""

import logging
from pathlib import Path

import pytest

from claude_code_hooks_daemon.strategies.lint.protocol import ProvidesCommandValues
from claude_code_hooks_daemon.strategies.lint.rust_strategy import (
    RustLintStrategy,
    resolve_edition,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class TestCapability:
    def test_implements_provides_command_values(self) -> None:
        assert isinstance(RustLintStrategy(), ProvidesCommandValues)

    def test_commands_carry_the_edition_placeholder(self) -> None:
        strategy = RustLintStrategy()
        assert "--edition {edition}" in strategy.default_lint_command
        extended = strategy.extended_lint_command
        assert extended is not None
        assert "--edition {edition}" in extended

    def test_command_values_supplies_the_edition(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "x"\nedition = "2018"\n')
        source = _write(tmp_path / "src" / "lib.rs", "")
        assert RustLintStrategy().command_values(str(source)) == {"edition": "2018"}


class TestResolveEdition:
    def test_package_edition(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "x"\nedition = "2024"\n')
        source = _write(tmp_path / "src" / "a.rs", "")
        assert resolve_edition(str(source)) == "2024"

    def test_no_cargo_toml_keeps_the_standalone_framing(self, tmp_path: Path) -> None:
        source = _write(tmp_path / "loose.rs", "")
        assert resolve_edition(str(source)) == "2021"

    def test_package_without_edition_is_cargos_default(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "x"\n')
        source = _write(tmp_path / "src" / "a.rs", "")
        assert resolve_edition(str(source)) == "2015"

    @pytest.mark.parametrize(
        "inherit",
        [
            "edition.workspace = true\n",
            "edition = { workspace = true }\n",
        ],
    )
    def test_workspace_inherited_edition_both_spellings(self, tmp_path: Path, inherit: str) -> None:
        _write(
            tmp_path / "Cargo.toml",
            '[workspace]\nmembers = ["crates/m"]\n\n[workspace.package]\nedition = "2024"\n',
        )
        _write(
            tmp_path / "crates" / "m" / "Cargo.toml",
            f'[package]\nname = "m"\n{inherit}',
        )
        source = _write(tmp_path / "crates" / "m" / "src" / "lib.rs", "")
        assert resolve_edition(str(source)) == "2024"

    def test_inherited_edition_with_no_workspace_edition_falls_back(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(tmp_path / "Cargo.toml", '[workspace]\nmembers = ["m"]\n')
        _write(tmp_path / "m" / "Cargo.toml", '[package]\nname = "m"\nedition.workspace = true\n')
        source = _write(tmp_path / "m" / "src" / "lib.rs", "")
        with caplog.at_level(logging.WARNING):
            assert resolve_edition(str(source)) == "2021"
        assert "edition" in caplog.text

    def test_inherited_edition_with_no_workspace_at_all_falls_back(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "m"\nedition.workspace = true\n')
        source = _write(tmp_path / "src" / "lib.rs", "")
        assert resolve_edition(str(source)) == "2021"

    def test_malformed_manifest_falls_back_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(tmp_path / "Cargo.toml", "[package\nname = = broken")
        source = _write(tmp_path / "src" / "lib.rs", "")
        with caplog.at_level(logging.WARNING):
            assert resolve_edition(str(source)) == "2021"
        assert "Cargo.toml" in caplog.text

    def test_unreadable_manifest_falls_back(self, tmp_path: Path) -> None:
        # A directory named Cargo.toml cannot be read as a file.
        (tmp_path / "Cargo.toml").mkdir()
        source = _write(tmp_path / "src" / "lib.rs", "")
        assert resolve_edition(str(source)) == "2021"

    def test_unknown_edition_falls_back_and_logs(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "x"\nedition = "2099 --evil"\n')
        source = _write(tmp_path / "src" / "lib.rs", "")
        with caplog.at_level(logging.WARNING):
            assert resolve_edition(str(source)) == "2021"
        assert "2099" in caplog.text

    def test_non_string_edition_falls_back(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "x"\nedition = 2021\n')
        source = _write(tmp_path / "src" / "lib.rs", "")
        assert resolve_edition(str(source)) == "2021"

    def test_virtual_manifest_without_package_falls_back(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[workspace]\nmembers = ["m"]\n')
        source = _write(tmp_path / "build.rs", "")
        assert resolve_edition(str(source)) == "2021"

    def test_nearest_manifest_wins(self, tmp_path: Path) -> None:
        _write(tmp_path / "Cargo.toml", '[package]\nname = "outer"\nedition = "2018"\n')
        _write(tmp_path / "inner" / "Cargo.toml", '[package]\nname = "i"\nedition = "2024"\n')
        source = _write(tmp_path / "inner" / "src" / "lib.rs", "")
        assert resolve_edition(str(source)) == "2024"


class TestCrateContextClassification:
    """Errors that mean "this file cannot be resolved outside its crate"."""

    @pytest.mark.parametrize("code", ["E0432", "E0433", "E0463", "E0583"])
    def test_crate_context_code_is_could_not_analyse(self, code: str) -> None:
        output = f"error[{code}]: something about resolution\n --> src/b.rs:1:5\n"
        assert RustLintStrategy().is_tool_unavailable_output(output) is True

    def test_syntax_error_still_a_finding(self) -> None:
        output = "error: this file contains an unclosed delimiter\n --> src/b.rs:1:15\n"
        assert RustLintStrategy().is_tool_unavailable_output(output) is False

    def test_plain_type_error_still_a_finding(self) -> None:
        output = "error[E0308]: mismatched types\n --> src/b.rs:1:30\n"
        assert RustLintStrategy().is_tool_unavailable_output(output) is False

    def test_code_in_prose_without_error_prefix_is_not_matched(self) -> None:
        output = "error: aborting; see docs mentioning E0432 in passing\n"
        assert RustLintStrategy().is_tool_unavailable_output(output) is False

    def test_rustup_shim_still_recognised(self) -> None:
        output = "error: 'clippy-driver' is not installed for the toolchain 'stable'.\n"
        assert RustLintStrategy().is_tool_unavailable_output(output) is True
