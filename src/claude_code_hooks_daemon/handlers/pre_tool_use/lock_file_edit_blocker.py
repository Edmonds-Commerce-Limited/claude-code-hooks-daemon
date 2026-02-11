"""Handler to block direct editing of package manager lock files.

Lock files from package managers should NEVER be directly edited. They must only
be modified through the proper package manager commands. Direct editing can lead
to inconsistent dependency resolution, broken package installations, hash/checksum
mismatches, version conflicts, and build failures.

This handler blocks Write and Edit tools when targeting lock files across all major
language ecosystems (PHP, JavaScript, Python, Ruby, Rust, Go, .NET, Swift).
"""

from typing import Any

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import HookResult


class LockFileEditBlockerHandler(Handler):
    """Block direct editing of package manager lock files.

    Lock files are generated artifacts that capture exact dependency versions and
    checksums. They ensure reproducible builds across environments. Direct editing
    breaks these guarantees because:
    - Hash mismatches: Manually edited entries won't match package checksums
    - Dependency resolution: Lock files represent solved dependency graphs
    - Version conflicts: Manual edits can create impossible version constraints
    - Build failures: Corrupted lock files cause CI/CD failures

    Priority: 10 (safety-critical)
    Terminal: True (blocks execution)
    """

    # Protected lock files (14 types across 8 ecosystems)
    LOCK_FILES = [
        # PHP/Composer
        "composer.lock",
        # JavaScript/Node
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        # Python
        "poetry.lock",
        "Pipfile.lock",
        "pdm.lock",
        # Ruby
        "Gemfile.lock",
        # Rust
        "Cargo.lock",
        # Go
        "go.sum",
        # .NET
        "packages.lock.json",
        "project.assets.json",
        # Swift
        "Package.resolved",
    ]

    # Package manager commands for each lock file type
    PACKAGE_MANAGER_COMMANDS = {
        "composer.lock": "composer install / composer update",
        "package-lock.json": "npm install / npm update",
        "yarn.lock": "yarn install / yarn upgrade",
        "pnpm-lock.yaml": "pnpm install / pnpm update",
        "bun.lockb": "bun install / bun update",
        "poetry.lock": "poetry install / poetry update",
        "Pipfile.lock": "pipenv install / pipenv update",
        "pdm.lock": "pdm install / pdm update",
        "Gemfile.lock": "bundle install / bundle update",
        "Cargo.lock": "cargo update",
        "go.sum": "go get / go mod tidy",
        "packages.lock.json": "dotnet restore",
        "project.assets.json": "dotnet restore",
        "Package.resolved": "swift package update",
    }

    def __init__(self) -> None:
        """Initialize handler with safety-critical priority."""
        super().__init__(
            name=HandlerID.LOCK_FILE_EDIT_BLOCKER.display_name,
            priority=Priority.LOCK_FILE_EDIT_BLOCKER,
            terminal=True,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if Write or Edit tool is targeting a lock file.

        Matches:
        - Write tool with file_path ending in any protected lock file name
        - Edit tool with file_path ending in any protected lock file name
        - Case-insensitive matching

        Does NOT match:
        - Read tool (reading is safe)
        - Bash tool (package manager commands are safe)
        - Files that aren't lock files

        Args:
            hook_input: Hook input containing tool_name and tool_input

        Returns:
            True if Write/Edit tool is targeting a lock file
        """
        # Only process Write and Edit tools
        tool_name = hook_input.get("tool_name")
        if tool_name not in [ToolName.WRITE, ToolName.EDIT]:
            return False

        # Extract file path
        tool_input = hook_input.get("tool_input", {})
        file_path = tool_input.get("file_path")
        if not file_path:
            return False

        # Check if file path ends with any protected lock file (case-insensitive)
        file_path_lower = file_path.lower()
        for lock_file in self.LOCK_FILES:
            if file_path_lower.endswith(lock_file.lower()):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Block operation and explain why lock files must not be edited.

        Args:
            hook_input: Hook input containing the operation to block

        Returns:
            HookResult with deny decision and explanation
        """
        # Safety check: if doesn't match, allow
        if not self.matches(hook_input):
            return HookResult(decision=Decision.ALLOW)

        tool_input = hook_input.get("tool_input", {})
        file_path = tool_input.get("file_path", "")

        # Extract lock file name from path
        lock_file_name = file_path.split("/")[-1]

        # Find matching lock file (case-insensitive)
        matched_lock_file: str | None = None
        for lock_file in self.LOCK_FILES:
            if lock_file_name.lower() == lock_file.lower():
                matched_lock_file = lock_file
                break

        # Get proper package manager commands
        if matched_lock_file:
            proper_commands = self.PACKAGE_MANAGER_COMMANDS.get(
                matched_lock_file, "appropriate package manager commands"
            )
        else:
            proper_commands = "appropriate package manager commands"

        reason = f"""🚫 BLOCKED: Direct editing of lock file

FILE: {file_path}

WHY BLOCKED:
Lock files are generated artifacts that must ONLY be modified through
package manager commands. They contain dependency checksums and resolved
version constraints.

Direct editing causes:
  • Hash/checksum mismatches (packages won't install)
  • Broken dependency resolution (impossible version constraints)
  • Corrupted lock files (CI/CD failures)
  • Irreversible build breakage

PROPER WAY TO UPDATE:
Use the package manager commands:
  {proper_commands}

These commands will:
  • Update dependencies correctly
  • Regenerate checksums
  • Resolve version constraints
  • Maintain lock file integrity

NEVER manually edit lock files with Write or Edit tools."""

        return HookResult(
            decision=Decision.DENY,
            reason=reason,
            context=[],
            guidance=None,
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for lock file edit blocker handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="Write to package-lock.json",
                command="Use the Write tool to write to /tmp/acceptance-test-locks/package-lock.json with content '{}'",
                description="Blocks direct editing of package-lock.json (corruption risk)",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"lock file",
                    r"npm install",
                ],
                safety_notes="Uses /tmp path - safe. Handler blocks Write before file is created.",
                test_type=TestType.BLOCKING,
                setup_commands=["mkdir -p /tmp/acceptance-test-locks"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-locks"],
            ),
            AcceptanceTest(
                title="Edit Cargo.lock",
                command="Use the Edit tool on /tmp/acceptance-test-locks/Cargo.lock with old_string 'old' and new_string 'new'",
                description="Blocks direct editing of Cargo.lock",
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"lock file",
                    r"cargo update",
                ],
                safety_notes="Uses /tmp path - safe. Handler blocks Edit before file is modified.",
                test_type=TestType.BLOCKING,
                setup_commands=[
                    "mkdir -p /tmp/acceptance-test-locks",
                    "echo 'old content' > /tmp/acceptance-test-locks/Cargo.lock",
                ],
                cleanup_commands=["rm -rf /tmp/acceptance-test-locks"],
            ),
        ]
