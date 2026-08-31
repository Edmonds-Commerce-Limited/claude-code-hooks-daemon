"""Handler to block direct editing of package manager lock files.

Lock files from package managers should NEVER be directly edited. They must only
be modified through the proper package manager commands. Direct editing can lead
to inconsistent dependency resolution, broken package installations, hash/checksum
mismatches, version conflicts, and build failures.

This handler blocks Write and Edit tools when targeting lock files across all major
language ecosystems (PHP, JavaScript, Python, Ruby, Rust, Go, .NET, Swift).
"""

from typing import Any, ClassVar

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter

_RULE = Rule(
    rule_id=RuleID.LOCK_FILE_EDIT,
    blocked="Direct `Write`/`Edit` of a package manager lock file",
    why="Lock files are generated artifacts; manual edits create checksum mismatches and broken dependency graphs",
    fix="Use the package manager commands instead (e.g. `npm install`, `cargo update`)",
    verbose=(
        "WHY BLOCKED:\n"
        "Lock files are generated artifacts that must ONLY be modified through\n"
        "package manager commands. They contain dependency checksums and resolved\n"
        "version constraints.\n\n"
        "Direct editing causes:\n"
        "  - Hash/checksum mismatches (packages won't install)\n"
        "  - Broken dependency resolution (impossible version constraints)\n"
        "  - Corrupted lock files (CI/CD failures)\n"
        "  - Irreversible build breakage\n\n"
        "These commands will update dependencies correctly, regenerate checksums,\n"
        "resolve version constraints and maintain lock file integrity.\n\n"
        "NEVER manually edit lock files with Write or Edit tools."
    ),
)


class LockFileEditBlockerHandler(PreToolUseHandlerBase):
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
    LOCK_FILES: ClassVar[list[str]] = [
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
    PACKAGE_MANAGER_COMMANDS: ClassVar[dict[str, str]] = {
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
            handler_id=HandlerID.LOCK_FILE_EDIT_BLOCKER,
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
        return any(file_path_lower.endswith(lock_file.lower()) for lock_file in self.LOCK_FILES)

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Block operation with a verbose-first/terse-after explanation.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The matched file and its
        package manager command are appended on every fire — they change per
        invocation, so they are not part of the static teaching content.

        Args:
            hook_input: Hook input containing the operation to block

        Returns:
            GatingResult with deny decision and explanation
        """
        # Safety check: if doesn't match, allow
        if not self.matches(hook_input):
            return GatingResult(decision=Decision.ALLOW)

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

        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        formatter = RuleFormatter()

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.LOCK_FILE_EDIT):
            message = formatter.terse(_RULE)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.LOCK_FILE_EDIT)
            message = formatter.verbose(_RULE)

        message += f"\n\nFILE: {file_path}\nPROPER WAY TO UPDATE: {proper_commands}"

        return GatingResult(
            decision=Decision.DENY,
            reason=message,
            context=[],
            guidance=None,
        )

    def get_claude_md(self) -> str | None:
        return (
            "## lock_file_edit_blocker — never directly edit lock files\n\n"
            "Direct `Write` or `Edit` to package manager lock files is blocked. "
            "Lock files are generated artifacts; manual edits create checksum mismatches "
            "and broken dependency graphs.\n\n"
            "**Blocked files**: `composer.lock`, `package-lock.json`, `yarn.lock`, "
            "`pnpm-lock.yaml`, `Gemfile.lock`, `Cargo.lock`, `go.sum`, "
            "`Package.resolved`, `Pipfile.lock`, and others.\n\n"
            "**Use package manager commands instead**:\n"
            "- PHP: `composer install` / `composer require package`\n"
            "- Node: `npm install` / `yarn add package`\n"
            "- Ruby: `bundle install` / `bundle add gem`\n"
            "- Rust: `cargo add crate`\n"
            "- Go: `go get module`"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for lock file edit blocker handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

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
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
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
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
