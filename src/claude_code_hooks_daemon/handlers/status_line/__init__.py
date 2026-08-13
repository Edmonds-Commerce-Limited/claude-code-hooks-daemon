"""Status line handlers for formatting daemon-based status display.

This module provides handlers for the Status event, which generates
the terminal status line text showing model, context, git branch,
and daemon health information.
"""

from claude_code_hooks_daemon.handlers.status_line.account_display import (
    AccountDisplayHandler,
)
from claude_code_hooks_daemon.handlers.status_line.context_sidecar import (
    ContextSidecarHandler,
)
from claude_code_hooks_daemon.handlers.status_line.current_time import CurrentTimeHandler
from claude_code_hooks_daemon.handlers.status_line.daemon_stats import DaemonStatsHandler
from claude_code_hooks_daemon.handlers.status_line.environment_indicator import (
    EnvironmentIndicatorHandler,
)
from claude_code_hooks_daemon.handlers.status_line.git_branch import GitBranchHandler
from claude_code_hooks_daemon.handlers.status_line.git_repo_name import GitRepoNameHandler
from claude_code_hooks_daemon.handlers.status_line.model_context import ModelContextHandler
from claude_code_hooks_daemon.handlers.status_line.multithread_indicator import (
    MultithreadIndicatorHandler,
)
from claude_code_hooks_daemon.handlers.status_line.supervisor_indicator import (
    SupervisorIndicatorHandler,
)
from claude_code_hooks_daemon.handlers.status_line.upgrade_notifier import (
    UpgradeNotifierHandler,
)
from claude_code_hooks_daemon.handlers.status_line.working_directory import (
    WorkingDirectoryHandler,
)

__all__ = [
    "AccountDisplayHandler",
    "ContextSidecarHandler",
    "CurrentTimeHandler",
    "DaemonStatsHandler",
    "EnvironmentIndicatorHandler",
    "GitBranchHandler",
    "GitRepoNameHandler",
    "ModelContextHandler",
    "MultithreadIndicatorHandler",
    "SupervisorIndicatorHandler",
    "UpgradeNotifierHandler",
    "WorkingDirectoryHandler",
]
