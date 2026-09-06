"""Python error-hiding strategy - patterns that suppress errors in Python code."""

from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

_LANGUAGE_NAME = "Python"
#: Acceptance-test fixture directory, below the sanctioned scratch root.
_FIXTURE_DIR = "acceptance-test-error-hiding-python"
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

        fixture_root = scratch_path(_FIXTURE_DIR)

        return [
            AcceptanceTest(
                title="Python: bare except: pass hides all exceptions",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'bad.py')}',\n"
                    "  content='try:\\n    do_something()\\nexcept:\\n    pass\\n'\n"
                    ")"
                ),
                description=(
                    "Blocks Python file with 'except: pass' error-hiding pattern "
                    "written via Write tool"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-ERROR-HIDING\]",
                    r"bare except",
                ],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Python: proper exception handling is allowed",
                command=(
                    "Write(\n"
                    f"  file_path='{scratch_path(_FIXTURE_DIR, 'good.py')}',\n"
                    "  content='import logging\\n\\n\\n"
                    "def run(task):\\n    try:\\n        task()\\n"
                    '    except ValueError:\\n        logging.exception(\\"task failed\\")\\n'
                    "        raise\\n'\n"
                    ")"
                ),
                description=("Allows Python file with proper exception handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Inside the gitignored scratch directory - safe",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
