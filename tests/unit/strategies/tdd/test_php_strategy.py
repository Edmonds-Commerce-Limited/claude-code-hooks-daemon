"""Tests for PHP TDD Strategy."""

from claude_code_hooks_daemon.strategies.tdd.php_strategy import PhpTddStrategy
from claude_code_hooks_daemon.strategies.tdd.protocol import TddStrategy


def test_php_strategy_implements_protocol() -> None:
    """PhpTddStrategy should implement TddStrategy protocol."""
    strategy = PhpTddStrategy()
    assert isinstance(strategy, TddStrategy)


def test_language_name() -> None:
    """Language name should be 'PHP'."""
    strategy = PhpTddStrategy()
    assert strategy.language_name == "PHP"


def test_extensions() -> None:
    """Extensions should be ('.php',)."""
    strategy = PhpTddStrategy()
    assert strategy.extensions == (".php",)


def test_is_test_file_with_test_suffix() -> None:
    """Files with stem ending in 'Test' should be recognized as test files."""
    strategy = PhpTddStrategy()
    assert strategy.is_test_file("/workspace/src/UserTest.php") is True
    assert strategy.is_test_file("/workspace/src/UserControllerTest.php") is True


def test_is_test_file_without_test_suffix() -> None:
    """Files without 'Test' suffix should NOT be test files (unless in test dir)."""
    strategy = PhpTddStrategy()
    assert strategy.is_test_file("/workspace/src/User.php") is False
    assert strategy.is_test_file("/workspace/src/UserController.php") is False


def test_is_test_file_in_common_test_directories() -> None:
    """Files in common test directories should be recognized as test files."""
    strategy = PhpTddStrategy()
    assert strategy.is_test_file("/workspace/tests/Unit/Helper.php") is True
    assert strategy.is_test_file("/workspace/test/Integration/Service.php") is True


def test_is_production_source_in_source_directories() -> None:
    """Files in PHP source directories should be production source."""
    strategy = PhpTddStrategy()
    assert strategy.is_production_source("/workspace/src/User.php") is True
    assert strategy.is_production_source("/workspace/app/Controller/UserController.php") is True


def test_is_production_source_outside_source_directories() -> None:
    """Files outside source directories should NOT be production source."""
    strategy = PhpTddStrategy()
    assert strategy.is_production_source("/workspace/config/database.php") is False
    assert strategy.is_production_source("/workspace/public/index.php") is False


def test_should_skip_fixtures_directory() -> None:
    """Files in tests/fixtures/ should be skipped."""
    strategy = PhpTddStrategy()
    assert strategy.should_skip("/workspace/tests/fixtures/sample_data.php") is True


def test_should_skip_vendor_directory() -> None:
    """Files in vendor/ should be skipped."""
    strategy = PhpTddStrategy()
    assert strategy.should_skip("/workspace/vendor/composer/autoload.php") is True


def test_should_skip_normal_source_files() -> None:
    """Normal source files should NOT be skipped."""
    strategy = PhpTddStrategy()
    assert strategy.should_skip("/workspace/src/User.php") is False
    assert strategy.should_skip("/workspace/app/Controller.php") is False


def test_should_skip_interface_files_by_filename() -> None:
    """Interface files should be skipped based on *Interface.php naming convention."""
    strategy = PhpTddStrategy()
    assert (
        strategy.should_skip("/workspace/src/Service/TransactionManagementServiceInterface.php")
        is True
    )
    assert strategy.should_skip("/workspace/app/Repository/UserRepositoryInterface.php") is True
    assert strategy.should_skip("/workspace/src/Contract/PaymentGatewayInterface.php") is True


def test_should_skip_interface_filename_not_triggered_by_substring() -> None:
    """Files with 'Interface' in the name but not as suffix should NOT be skipped."""
    strategy = PhpTddStrategy()
    assert strategy.should_skip("/workspace/src/Service/InterfaceManager.php") is False
    assert strategy.should_skip("/workspace/src/Service/InterfaceValidator.php") is False


def test_should_skip_interface_by_content() -> None:
    """Files containing only interface declarations should be skipped via content inspection."""
    strategy = PhpTddStrategy()
    content = (
        "<?php\n\nnamespace App\\Service;\n\n"
        "interface PaymentGateway\n{\n    public function charge(): void;\n}\n"
    )
    assert (
        strategy.should_skip("/workspace/src/Service/PaymentGateway.php", content=content) is True
    )


def test_should_not_skip_class_by_content() -> None:
    """Files containing class declarations should NOT be skipped."""
    strategy = PhpTddStrategy()
    content = (
        "<?php\n\nnamespace App\\Service;\n\n"
        "class PaymentService\n{\n    public function process(): void {}\n}\n"
    )
    assert (
        strategy.should_skip("/workspace/src/Service/PaymentService.php", content=content) is False
    )


def test_should_not_skip_file_with_both_interface_and_class() -> None:
    """Files containing both interface and class should NOT be skipped (class needs testing)."""
    strategy = PhpTddStrategy()
    content = (
        "<?php\n\ninterface Loggable\n{\n    public function log(): void;\n}\n\n"
        "class Logger implements Loggable\n{\n    public function log(): void {}\n}\n"
    )
    assert strategy.should_skip("/workspace/src/Logger.php", content=content) is False


def test_should_not_skip_abstract_class_by_content() -> None:
    """Abstract classes are not interfaces — they should NOT be skipped."""
    strategy = PhpTddStrategy()
    content = (
        "<?php\n\nabstract class BaseService\n{\n"
        "    abstract public function execute(): void;\n}\n"
    )
    assert strategy.should_skip("/workspace/src/Service/BaseService.php", content=content) is False


def test_should_not_match_interface_in_implements_clause() -> None:
    """The word 'interface' in an implements clause should NOT trigger skip."""
    strategy = PhpTddStrategy()
    content = (
        "<?php\n\nclass PaymentService implements PaymentInterface\n{\n"
        "    public function pay(): void {}\n}\n"
    )
    assert (
        strategy.should_skip("/workspace/src/Service/PaymentService.php", content=content) is False
    )


def test_compute_test_filename() -> None:
    """Should compute test filename with 'Test' suffix before extension."""
    strategy = PhpTddStrategy()
    assert strategy.compute_test_filename("User.php") == "UserTest.php"
    assert strategy.compute_test_filename("UserController.php") == "UserControllerTest.php"
    assert strategy.compute_test_filename("Service.php") == "ServiceTest.php"
