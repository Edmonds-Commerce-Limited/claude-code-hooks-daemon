"""C# QA suppression strategy implementation."""

from typing import Any

from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

# ── Language-specific constants ──────────────────────────────────
_LANGUAGE_NAME = "C#"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-qa-csharp"
_EXTENSIONS: tuple[str, ...] = (".cs",)
_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    r"#pragma\s+warning\s+" + "disable",
    r"//\s*ReSharper\s+" + "disable",
    r"\[Suppress" + r"Message\(",
)
_SKIP_DIRECTORIES: tuple[str, ...] = (
    "bin/",
    "obj/",
    "vendor/",
)
_TOOL_NAMES: tuple[str, ...] = ("Roslyn Analyzers", "ReSharper", "StyleCop")
_TOOL_DOCS_URLS: tuple[str, ...] = (
    "https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/",
    "https://www.jetbrains.com/resharper/",
)


class CSharpQaSuppressionStrategy:
    """QA suppression strategy for C#."""

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
        """Return acceptance tests for C# QA suppression strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="C# QA suppression blocked",
                command=(
                    f'Write file_path="{scratch_path(_FIXTURE_DIR, "Example.cs")}"'
                    ' content="#pragma warning ' + "disable" + ' CS0168\\npublic class Example {}"'
                ),
                description="Should block C# QA suppression directive",
                expected_decision=Decision.DENY,
                expected_message_patterns=["suppression", "BLOCKED", "C#"],
                test_type=TestType.BLOCKING,
                safety_notes="Inside the gitignored scratch directory - safe",
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
