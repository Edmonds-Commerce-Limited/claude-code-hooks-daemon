"""Python security strategy - dangerous function patterns (OWASP A03)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Python"
_EXTENSIONS: tuple[str, ...] = (".py",)

_OWASP_CATEGORY = "A03"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="eval() - code injection risk",
        regex=r"\beval\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use ast.literal_eval() for safe evaluation",
    ),
    SecurityPattern(
        name="exec() - code injection risk",
        regex=r"\bexec\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Avoid dynamic code execution; use safe alternatives",
    ),
    SecurityPattern(
        name="os.system() - command injection risk",
        regex=r"\bos\.system\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use subprocess.run() with explicit argument lists",
    ),
    SecurityPattern(
        name="subprocess with shell=True - command injection risk",
        regex=r"subprocess\.\w+\(.*shell\s*=\s*True",
        owasp=_OWASP_CATEGORY,
        suggestion="Use subprocess.run() with shell=False (default) and argument lists",
    ),
    SecurityPattern(
        name="pickle.load/loads - deserialization injection risk",
        regex=r"\bpickle\.loads?\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use json.loads() or other safe serialization",
    ),
    SecurityPattern(
        name="yaml.load() - code execution risk",
        regex=r"\byaml\.load\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use yaml.safe_load() instead",
    ),
    SecurityPattern(
        name="__import__() - dynamic import injection risk",
        regex=r"\b__import__\s*\(",
        owasp=_OWASP_CATEGORY,
        suggestion="Use importlib.import_module() for dynamic imports",
    ),
)


class PythonSecurityStrategy:
    """Detect Python dangerous function patterns (OWASP A03).

    Catches eval, exec, os.system, subprocess with shell=True, pickle.load/loads,
    yaml.load, and __import__ calls in Python source files.
    """

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[SecurityPattern, ...]:
        return _PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Python security strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block Python eval in source file",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/test_security.py' "
                    "with content 'result = eval(user_input)'"
                ),
                description="Blocks writing Python file with eval() call",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"eval\(\)",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
