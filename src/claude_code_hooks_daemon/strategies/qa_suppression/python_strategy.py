"""Python QA suppression strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "Python"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-qa-python"
_EXTENSIONS: tuple[str, ...] = (".py",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"#\s*type:\s*" + "ignore",
    r"#\s*no" + "qa",
    r"#\s*pylint:\s*" + "disable",
    r"#\s*pyright:\s*" + "ignore",
    r"#\s*mypy:\s*" + "ignore-errors",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "tests/fixtures/",
    "migrations/",
    "vendor/",
    ".venv/",
    "venv/",
)
_TOOL_NAMES: tuple[str, ...] = ("MyPy", "Ruff", "Pylint", "Pyright")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://mypy.readthedocs.io/",
    "https://docs.astral.sh/ruff/",
    "https://pylint.readthedocs.io/",
)


class PythonQaSuppressionStrategy:
    """QA suppression strategy for Python."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def forbidden_patterns(self) -> tuple[str, ...]:
        return _FORBIDDEN_PATTERNS

    @property
    def skip_directories(self) -> tuple[str, ...]:
        return _SKIP_DIRECTORIES

    @property
    def tool_names(self) -> tuple[str, ...]:
        return _TOOL_NAMES

    @property
    def tool_docs_urls(self) -> tuple[str, ...]:
        return _TOOL_DOCS_URLS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Python QA suppression blocked",
                command=(
                    f'Write file_path="{scratch_path(_FIXTURE_DIR, "example.py")}"'
                    ' content="x = 1  # type: ' + "ignore" + '"'
                ),
                description="Should block Python QA suppression comment",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "Python"],
                test_type=TestType.BLOCKING,
                safety_notes="Inside the gitignored scratch directory - safe",
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
