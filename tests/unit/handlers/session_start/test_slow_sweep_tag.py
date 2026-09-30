"""The SessionStart handlers that walk the repository run after the cheap ones.

Measured on this repository under load: five handlers spent 30 s of a 33 s
chain between them, while ``persistent_cron_assertor`` needed 0.5 s. The sweeps
carry ``SLOW_SWEEP`` so the chain orders them last and a budget overrun cannot
starve a cheap handler.
"""

import pytest

from claude_code_hooks_daemon.constants.tags import HandlerTag
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.session_start.docs_qa_sweep import DocsQaSweepHandler
from claude_code_hooks_daemon.handlers.session_start.git_upstream_checker import (
    GitUpstreamCheckerHandler,
)
from claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker import (
    GitignoreSafetyCheckerHandler,
)
from claude_code_hooks_daemon.handlers.session_start.persistent_cron_assertor import (
    PersistentCronAssertorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.plan_qa_sweep import PlanQaSweepHandler
from claude_code_hooks_daemon.handlers.session_start.reference_repo_sweep import (
    ReferenceRepoSweepHandler,
)
from claude_code_hooks_daemon.handlers.session_start.secret_file_hygiene_checker import (
    SecretFileHygieneCheckerHandler,
)


@pytest.mark.parametrize(
    "handler_class",
    [
        DocsQaSweepHandler,
        GitUpstreamCheckerHandler,
        GitignoreSafetyCheckerHandler,
        PlanQaSweepHandler,
        ReferenceRepoSweepHandler,
        SecretFileHygieneCheckerHandler,
    ],
)
def test_repository_walking_handler_is_a_slow_sweep(handler_class: type[Handler]) -> None:
    """Each handler that walks the repository or the network is tagged SLOW_SWEEP."""
    assert HandlerTag.SLOW_SWEEP in handler_class().tags


def test_persistent_cron_assertor_is_not_a_slow_sweep() -> None:
    """The assertor is a pure config read and must never be ordered behind a sweep."""
    assert HandlerTag.SLOW_SWEEP not in PersistentCronAssertorHandler().tags
