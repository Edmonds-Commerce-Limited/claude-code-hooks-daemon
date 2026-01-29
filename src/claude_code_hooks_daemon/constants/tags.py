"""Handler tag constants - single source of truth for all handler tags.

This module defines all valid handler tags used for categorizing and filtering
handlers. Tags enable language-specific, function-specific, or project-specific
handler groups.

Usage:
    from claude_code_hooks_daemon.constants import HandlerTag

    # In handler __init__:
    super().__init__(
        handler_id=HandlerID.DESTRUCTIVE_GIT,
        tags=[HandlerTag.SAFETY, HandlerTag.GIT, HandlerTag.BLOCKING],
    )

    # In config (YAML):
    handlers:
      enable_tags: [python, typescript]  # String values in YAML
      disable_tags: [yolo-mode]
"""

from __future__ import annotations

from typing import Literal


class HandlerTag:
    """Canonical handler tag values - single source of truth.

    Tags are used to categorize handlers for filtering via enable_tags/disable_tags
    in the daemon configuration. Each handler can have multiple tags.

    Tag Categories:
        - Languages: python, typescript, javascript, php, go, bash
        - Safety: safety, blocking, terminal, non-terminal
        - Workflow: workflow, advisory, validation, automation
        - QA: qa-enforcement, qa-suppression-prevention, tdd
        - Domains: git, file-ops, content-quality, npm, nodejs, github, markdown
        - System: status, display, health, logging, cleanup
        - Project: ec-specific, ec-preference, project-specific
        - Other: planning, environment, yolo-mode, state-management, context-injection
    """

    # Language tags
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PHP = "php"
    GO = "go"
    BASH = "bash"

    # Safety/behavior tags
    SAFETY = "safety"
    BLOCKING = "blocking"
    TERMINAL = "terminal"
    NON_TERMINAL = "non-terminal"

    # Workflow tags
    WORKFLOW = "workflow"
    ADVISORY = "advisory"
    VALIDATION = "validation"
    AUTOMATION = "automation"

    # QA-related tags
    QA_ENFORCEMENT = "qa-enforcement"
    QA_SUPPRESSION_PREVENTION = "qa-suppression-prevention"
    TDD = "tdd"

    # Domain-specific tags
    GIT = "git"
    FILE_OPS = "file-ops"
    CONTENT_QUALITY = "content-quality"
    NPM = "npm"
    NODEJS = "nodejs"
    GITHUB = "github"
    MARKDOWN = "markdown"

    # System tags
    STATUS = "status"
    STATUSLINE = "statusline"
    DISPLAY = "display"
    HEALTH = "health"
    LOGGING = "logging"
    CLEANUP = "cleanup"
    DAEMON = "daemon"
    ARCHIVING = "archiving"
    TEST = "test"

    # Project-specific tags
    EC_SPECIFIC = "ec-specific"
    EC_PREFERENCE = "ec-preference"
    PROJECT_SPECIFIC = "project-specific"

    # Other tags
    PLANNING = "planning"
    ENVIRONMENT = "environment"
    YOLO_MODE = "yolo-mode"
    STATE_MANAGEMENT = "state-management"
    CONTEXT_INJECTION = "context-injection"


# Type alias for valid tag values (for type checking)
TagLiteral = Literal[
    # Languages
    "python",
    "typescript",
    "javascript",
    "php",
    "go",
    "bash",
    # Safety
    "safety",
    "blocking",
    "terminal",
    "non-terminal",
    # Workflow
    "workflow",
    "advisory",
    "validation",
    "automation",
    # QA
    "qa-enforcement",
    "qa-suppression-prevention",
    "tdd",
    # Domains
    "git",
    "file-ops",
    "content-quality",
    "npm",
    "nodejs",
    "github",
    "markdown",
    # System
    "status",
    "statusline",
    "display",
    "health",
    "logging",
    "cleanup",
    "daemon",
    "archiving",
    "test",
    # Project-specific
    "ec-specific",
    "ec-preference",
    "project-specific",
    # Other
    "planning",
    "environment",
    "yolo-mode",
    "state-management",
    "context-injection",
]


__all__ = ["HandlerTag", "TagLiteral"]
