"""The one place a lint command template becomes an argv list."""

from pathlib import Path

from claude_code_hooks_daemon.strategies.lint.common import build_lint_argv
from claude_code_hooks_daemon.strategies.lint.rust_strategy import RustLintStrategy


class _Plain:
    """A strategy with no per-file values."""


class _Valued:
    def command_values(self, file_path: str) -> dict[str, str]:
        return {"edition": "2024", "tag": "x y"}


class TestBuildLintArgv:
    def test_file_is_one_element_even_with_spaces_or_flags(self) -> None:
        hostile = "my file.py --config /tmp/evil.toml"
        assert build_lint_argv("ruff check {file}", hostile, _Plain()) == [
            "ruff",
            "check",
            hostile,
        ]

    def test_effective_path_replaces_file(self) -> None:
        argv = build_lint_argv("go vet {file}", "/p/a.go", _Plain(), effective_path="./p/")
        assert argv == ["go", "vet", "./p/"]

    def test_strategy_values_fill_whole_element_placeholders_as_one_element(self) -> None:
        argv = build_lint_argv("rustc --edition {edition} --x {tag} {file}", "/a.rs", _Valued())
        assert argv == ["rustc", "--edition", "2024", "--x", "x y", "/a.rs"]

    def test_override_without_the_placeholder_is_unchanged(self) -> None:
        argv = build_lint_argv("rustc --edition 2018 {file}", "/a.rs", _Valued())
        assert argv == ["rustc", "--edition", "2018", "/a.rs"]

    def test_placeholder_inside_a_larger_element_is_left_alone(self) -> None:
        argv = build_lint_argv("tool --e={edition} {file}", "/a.rs", _Valued())
        assert argv == ["tool", "--e={edition}", "/a.rs"]

    def test_no_strategy_values_leave_edition_unfilled(self) -> None:
        assert build_lint_argv("rustc --edition {edition} {file}", "/a.rs", None) == [
            "rustc",
            "--edition",
            "{edition}",
            "/a.rs",
        ]

    def test_rust_default_command_is_fully_filled(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\nedition = "2024"\n')
        source = tmp_path / "src.rs"
        strategy = RustLintStrategy()
        for template in (strategy.default_lint_command, strategy.extended_lint_command):
            assert template is not None
            argv = build_lint_argv(template, str(source), strategy)
            assert argv[argv.index("--edition") + 1] == "2024"
            assert not any("{" in part for part in argv)
