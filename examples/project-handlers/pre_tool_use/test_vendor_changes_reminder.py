"""Tests for vendor changes reminder handler."""

from vendor_changes_reminder import VendorChangesReminderHandler
from claude_code_hooks_daemon.core.hook_result import Decision


class TestVendorChangesReminderHandler:
    """Tests for VendorChangesReminderHandler."""

    def setup_method(self) -> None:
        self.handler = VendorChangesReminderHandler()

    def test_init(self) -> None:
        assert self.handler.name == "vendor-changes-reminder"
        assert self.handler.priority == 45
        assert self.handler.terminal is False

    def test_matches_vendor_git_add(self, bash_hook_input) -> None:
        hook_input = bash_hook_input("git add vendor/my-org/package/src/file.php")
        assert self.handler.matches(hook_input) is True

    def test_matches_vendor_git_commit(self, bash_hook_input) -> None:
        hook_input = bash_hook_input("git commit -m 'update' vendor/my-org/package/")
        assert self.handler.matches(hook_input) is True

    def test_no_match_non_vendor_git_add(self, bash_hook_input) -> None:
        hook_input = bash_hook_input("git add src/Entity/Order.php")
        assert self.handler.matches(hook_input) is False

    def test_no_match_non_git_command(self, bash_hook_input) -> None:
        hook_input = bash_hook_input("ls vendor/")
        assert self.handler.matches(hook_input) is False

    def test_no_match_write_tool(self, write_hook_input) -> None:
        hook_input = write_hook_input("vendor/my-org/package/file.php")
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_advisory(self, bash_hook_input) -> None:
        hook_input = bash_hook_input("git add vendor/my-org/package/src/file.php")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert any("VENDOR WORKFLOW REMINDER" in ctx for ctx in result.context)

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
