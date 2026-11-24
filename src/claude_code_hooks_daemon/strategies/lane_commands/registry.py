"""LaneCommandStrategyRegistry - every language's lane commands, as one flat list."""

from claude_code_hooks_daemon.strategies.lane_commands.protocol import LaneCommandStrategy


class LaneCommandStrategyRegistry:
    """Maps language_name to a lane-command strategy and merges their patterns.

    Every registered language is always active: a host seat does not run a
    test suite in any language, so there is no per-project language filter.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, LaneCommandStrategy] = {}

    def register(self, strategy: LaneCommandStrategy) -> None:
        """Register ``strategy`` under its language_name, replacing any earlier one."""
        self._strategies[strategy.language_name] = strategy

    def get_lane_patterns(self) -> tuple[str, ...]:
        """Every registered strategy's patterns, in registration order."""
        patterns: list[str] = []
        for strategy in self._strategies.values():
            patterns.extend(strategy.lane_patterns)
        return tuple(patterns)

    def strategies(self) -> list[LaneCommandStrategy]:
        """The registered strategy instances, in registration order."""
        return list(self._strategies.values())

    @property
    def registered_languages(self) -> list[str]:
        """Names of the registered languages, in registration order."""
        return list(self._strategies.keys())

    @classmethod
    def create_default(cls) -> "LaneCommandStrategyRegistry":
        """A registry holding every built-in lane-command strategy."""
        from claude_code_hooks_daemon.strategies.lane_commands.dotnet_strategy import (
            DotNetLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.go_strategy import (
            GoLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.java_strategy import (
            JavaLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.javascript_strategy import (
            JavaScriptLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.php_strategy import (
            PhpLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.python_strategy import (
            PythonLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.ruby_strategy import (
            RubyLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.rust_strategy import (
            RustLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.shell_strategy import (
            ShellLaneCommandStrategy,
        )
        from claude_code_hooks_daemon.strategies.lane_commands.universal_strategy import (
            UniversalLaneCommandStrategy,
        )

        registry = cls()
        registry.register(UniversalLaneCommandStrategy())
        registry.register(PythonLaneCommandStrategy())
        registry.register(JavaScriptLaneCommandStrategy())
        registry.register(ShellLaneCommandStrategy())
        registry.register(GoLaneCommandStrategy())
        registry.register(RustLaneCommandStrategy())
        registry.register(JavaLaneCommandStrategy())
        registry.register(RubyLaneCommandStrategy())
        registry.register(PhpLaneCommandStrategy())
        registry.register(DotNetLaneCommandStrategy())
        return registry
