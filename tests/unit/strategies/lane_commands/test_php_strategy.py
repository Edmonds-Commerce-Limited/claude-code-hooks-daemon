"""Tests for the PHP lane-command strategy."""

import pytest

from claude_code_hooks_daemon.strategies.lane_commands.common import runs_any
from claude_code_hooks_daemon.strategies.lane_commands.php_strategy import PhpLaneCommandStrategy

STRATEGY = PhpLaneCommandStrategy()


def test_language_name() -> None:
    assert STRATEGY.language_name == "PHP"


@pytest.mark.parametrize(
    "command",
    [
        "composer test",
        "composer run test",
        "composer run-script test:unit",
        "phpunit",
        "vendor/bin/phpunit",
        "phpstan analyse",
        "psalm",
        "phpcs",
    ],
)
def test_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is True


@pytest.mark.parametrize(
    "command",
    [
        "composer install",
        "composer require x",
        "php artisan serve",
        "composer test-deploy",
        "phpunit-x",
        "phpunit-watcher watch",
    ],
)
def test_not_lane(command: str) -> None:
    assert runs_any(command, STRATEGY.lane_patterns) is False
