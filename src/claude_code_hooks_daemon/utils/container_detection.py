"""
Container detection utility.

Reusable container environment detection logic with confidence scoring.
Extracted from yolo_container_detection handler for wider use.
"""

import logging
import os
from pathlib import Path

from claude_code_hooks_daemon.core import ProjectContext

logger = logging.getLogger(__name__)

# Default confidence threshold for container detection
DEFAULT_CONFIDENCE_THRESHOLD = 3


def get_container_confidence_score() -> int:
    """
    Calculate confidence score based on detected container indicators.

    Uses a multi-tier confidence scoring system:
    - Primary indicators (3 points each): Strong signals of YOLO environment
    - Secondary indicators (2 points each): Container-related signals
    - Tertiary indicators (1 point each): Weak signals

    Returns:
        Confidence score (0-12 possible range)
    """
    score = 0

    try:
        # Primary indicators (3 points each)
        if os.environ.get("CLAUDECODE") == "1":
            score += 3

        if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "cli":
            score += 3

        # Check for /workspace + .claude/ directory
        try:
            if ProjectContext.project_root() == Path("/workspace"):
                if ProjectContext.config_dir().exists():
                    score += 3
        except (OSError, RuntimeError):
            # Filesystem errors - skip this check
            pass

        # Secondary indicators (2 points each)
        if os.environ.get("DEVCONTAINER") == "true":
            score += 2

        if os.environ.get("IS_SANDBOX") == "1":
            score += 2

        container_env = os.environ.get("container", "")
        if container_env in ["podman", "docker"]:
            score += 2

        # Tertiary indicators (1 point each)
        try:
            socket_path = Path(".claude/hooks-daemon/untracked/venv/socket")
            if socket_path.exists():
                score += 1
        except (OSError, RuntimeError):
            # Filesystem errors - skip this check
            pass

        try:
            if os.getuid() == 0:
                score += 1
        except AttributeError:
            # os.getuid() not available on Windows - skip
            pass

    except (OSError, RuntimeError, AttributeError) as e:
        logger.debug("Confidence score calculation failed: %s", e)
        return 0
    except Exception as e:
        logger.error("Unexpected error in confidence score: %s", e, exc_info=True)
        return 0

    return score


def is_container_environment(threshold: int = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
    """
    Check if running in a container environment.

    Uses confidence scoring to determine if the current environment
    is a container (threshold: score >= 3).

    Args:
        threshold: Minimum confidence score to consider as container (default 3)

    Returns:
        True if confidence score >= threshold, False otherwise
    """
    score = get_container_confidence_score()
    return score >= threshold


def get_detected_indicators() -> list[str]:
    """
    Get list of detected container indicators with descriptions.

    Returns:
        List of detected indicator descriptions (empty if none detected)
    """
    indicators: list[str] = []

    try:
        # Primary indicators
        if os.environ.get("CLAUDECODE") == "1":
            indicators.append("CLAUDECODE=1 environment variable")

        if os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "cli":
            indicators.append("CLAUDE_CODE_ENTRYPOINT=cli environment variable")

        try:
            if (
                ProjectContext.project_root() == Path("/workspace")
                and ProjectContext.config_dir().exists()
            ):
                indicators.append("Project root is /workspace with .claude/ present")
        except (OSError, RuntimeError):
            pass

        # Secondary indicators
        if os.environ.get("DEVCONTAINER") == "true":
            indicators.append("DEVCONTAINER=true environment variable")

        if os.environ.get("IS_SANDBOX") == "1":
            indicators.append("IS_SANDBOX=1 environment variable")

        container_env = os.environ.get("container", "")
        if container_env in ["podman", "docker"]:
            indicators.append(f"container={container_env} environment variable")

        # Tertiary indicators
        try:
            socket_path = Path(".claude/hooks-daemon/untracked/venv/socket")
            if socket_path.exists():
                indicators.append("Hooks daemon Unix socket present")
        except (OSError, RuntimeError):
            pass

        try:
            if os.getuid() == 0:
                indicators.append("Running as root user (UID 0)")
        except AttributeError:
            pass

    except (OSError, RuntimeError, AttributeError) as e:
        logger.debug("Indicator detection failed: %s", e)
        return []
    except Exception as e:
        logger.error("Unexpected error detecting indicators: %s", e, exc_info=True)
        return []

    return indicators
