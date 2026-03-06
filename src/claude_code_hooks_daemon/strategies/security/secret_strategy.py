"""Secret detection strategy - hardcoded credentials in any file type (OWASP A02)."""

from typing import Any

from claude_code_hooks_daemon.strategies.security.common import UNIVERSAL_EXTENSION
from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern

_LANGUAGE_NAME = "Secrets"
_EXTENSIONS: tuple[str, ...] = (UNIVERSAL_EXTENSION,)

_OWASP_CATEGORY = "A02"
_SUGGESTION_SECRETS = "Use environment variables, never hardcode credentials"

_PATTERNS: tuple[SecurityPattern, ...] = (
    SecurityPattern(
        name="AWS Access Key",
        regex=r"AKIA[0-9A-Z]{16}",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
    SecurityPattern(
        name="Stripe Secret Key",
        regex=r"sk_live_[a-zA-Z0-9]{24,}",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
    SecurityPattern(
        name="Stripe Publishable Key (live)",
        regex=r"pk_live_[a-zA-Z0-9]{24,}",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
    SecurityPattern(
        name="GitHub Personal Access Token",
        regex=r"ghp_[a-zA-Z0-9]{36}",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
    SecurityPattern(
        name="GitHub OAuth Token",
        regex=r"gho_[a-zA-Z0-9]{36}",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
    SecurityPattern(
        name="Private Key",
        regex=r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----",
        owasp=_OWASP_CATEGORY,
        suggestion=_SUGGESTION_SECRETS,
    ),
)


class SecretDetectionStrategy:
    """Detect hardcoded secrets in any file type (OWASP A02).

    This is a universal strategy — it applies to ALL file types regardless
    of extension. Catches AWS keys, Stripe keys, GitHub tokens, and
    private keys.
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
        """Return acceptance tests for secret detection strategy."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="Block hardcoded AWS key",
                command=(
                    "Use the Write tool to write file_path='/workspace/src/config.ts' "
                    "with content 'const key = \"AKIAIOSFODNN7EXAMPLE1\";'"
                ),
                description="Blocks writing file with hardcoded AWS access key",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"SECURITY ANTIPATTERN BLOCKED",
                    r"AWS Access Key",
                ],
                safety_notes="Handler blocks before file is written.",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Allow test fixture files",
                command=(
                    "Use the Write tool to write "
                    "file_path='/workspace/tests/fixtures/security_test.py' "
                    "with content 'AWS_KEY = \"AKIAIOSFODNN7EXAMPLE1\"'"
                ),
                description="Allows writing secrets in test fixture files (excluded path)",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Test fixtures are excluded from security scanning.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
