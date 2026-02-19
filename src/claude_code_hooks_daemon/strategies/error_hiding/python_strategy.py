"""Python error-hiding strategy - patterns that suppress errors in Python code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern

_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="bare except: pass",
        regex=r"except\s*:\s*\n\s*pass\b",
        example="except:\n    pass",
        suggestion="Catch specific exceptions and handle or re-raise them",
    ),
    ErrorHidingPattern(
        name="except Exception: pass",
        regex=r"except\s+\w[\w\s,]*:\s*\n\s*pass\b",
        example="except Exception:\n    pass",
        suggestion="Catch specific exceptions and handle or re-raise them",
    ),
    ErrorHidingPattern(
        name="bare except: ...",
        regex=r"except\s*:\s*\n\s*\.\.\.",
        example="except:\n    ...",
        suggestion="Catch specific exceptions and handle or re-raise them",
    ),
    ErrorHidingPattern(
        name="except Exception: ...",
        regex=r"except\s+\w[\w\s,]*:\s*\n\s*\.\.\.",
        example="except Exception:\n    ...",
        suggestion="Catch specific exceptions and handle or re-raise them",
    ),
)


class PythonErrorHidingStrategy:
    """Error-hiding strategy for Python source files (.py)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[ErrorHidingPattern, ...]:
        return _PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python error-hiding strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Python: bare except: pass hides all exceptions",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/python/bad.py',\n"
                    "  content='try:\\n    do_something()\\nexcept:\\n    pass\\n'\n"
                    ")"
                ),
                description=(
                    "Blocks Python file with 'except: pass' error-hiding pattern "
                    "written via Write tool"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"Error-hiding pattern detected",
                    r"bare except",
                ],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Python: proper exception handling is allowed",
                command=(
                    "Write(\n"
                    "  file_path='/tmp/acceptance-test-error-hiding/python/good.py',\n"
                    "  content='try:\\n    do_something()\\n"
                    "except ValueError as e:\\n    logger.error(e)\\n    raise\\n'\n"
                    ")"
                ),
                description=("Allows Python file with proper exception handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Uses Write tool to a /tmp path",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
