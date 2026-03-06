"""SecurityStrategyRegistry - maps file extensions to strategy implementations.

Supports universal strategies (e.g. secret detection) that apply to all file types
in addition to language-specific strategies mapped by file extension.
"""

from claude_code_hooks_daemon.strategies.security.common import UNIVERSAL_EXTENSION
from claude_code_hooks_daemon.strategies.security.protocol import SecurityStrategy


class SecurityStrategyRegistry:
    """Registry mapping file extensions to security strategy implementations.

    Supports:
    - Registering strategies by their declared extensions
    - Universal strategies that apply to ALL file types (extensions = ("*",))
    - Looking up all applicable strategies for a file path
    - Filtering to a subset of languages
    - Creating a default registry with all built-in strategies
    """

    def __init__(self) -> None:
        self._extension_strategies: dict[str, SecurityStrategy] = {}
        self._universal_strategies: list[SecurityStrategy] = []

    def register(self, strategy: SecurityStrategy) -> None:
        """Register a strategy for all its declared extensions.

        Strategies with extensions = ("*",) are registered as universal
        and will match all file types.
        """
        if UNIVERSAL_EXTENSION in strategy.extensions:
            self._universal_strategies.append(strategy)
        else:
            for ext in strategy.extensions:
                self._extension_strategies[ext.lower()] = strategy

    def get_strategies(self, file_path: str) -> list[SecurityStrategy]:
        """Return all strategies applicable to a file path.

        Returns universal strategies plus any extension-matched strategy.
        """
        result: list[SecurityStrategy] = list(self._universal_strategies)
        file_path_lower = file_path.lower()
        seen: set[str] = set()
        for ext, strategy in self._extension_strategies.items():
            if file_path_lower.endswith(ext) and strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy)
        return result

    def filter_by_languages(self, language_names: list[str]) -> None:
        """Remove strategies whose language_name is not in the given list.

        Matching is case-insensitive.  If language_names is empty, no filtering
        is applied (all strategies remain).
        """
        if not language_names:
            return
        allowed = {name.lower() for name in language_names}
        # Filter universal strategies
        self._universal_strategies = [
            s for s in self._universal_strategies if s.language_name.lower() in allowed
        ]
        # Filter extension strategies
        to_remove = [
            ext
            for ext, strategy in self._extension_strategies.items()
            if strategy.language_name.lower() not in allowed
        ]
        for ext in to_remove:
            del self._extension_strategies[ext]

    @property
    def registered_languages(self) -> list[str]:
        """Return de-duplicated list of language names for all registered strategies."""
        seen: set[str] = set()
        result: list[str] = []
        for strategy in self._universal_strategies:
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy.language_name)
        for strategy in self._extension_strategies.values():
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy.language_name)
        return result

    @property
    def all_strategies(self) -> list[SecurityStrategy]:
        """Return de-duplicated list of all registered strategies."""
        seen: set[str] = set()
        result: list[SecurityStrategy] = []
        for strategy in self._universal_strategies:
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy)
        for strategy in self._extension_strategies.values():
            if strategy.language_name not in seen:
                seen.add(strategy.language_name)
                result.append(strategy)
        return result

    @classmethod
    def create_default(cls) -> "SecurityStrategyRegistry":
        """Create a registry with ALL built-in security strategies."""
        from claude_code_hooks_daemon.strategies.security.csharp_strategy import (
            CSharpSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.dart_strategy import (
            DartSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.go_strategy import (
            GoSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.java_strategy import (
            JavaSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.javascript_strategy import (
            JavaScriptSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.kotlin_strategy import (
            KotlinSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.php_strategy import (
            PhpSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.python_strategy import (
            PythonSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.ruby_strategy import (
            RubySecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.rust_strategy import (
            RustSecurityStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.secret_strategy import (
            SecretDetectionStrategy,
        )
        from claude_code_hooks_daemon.strategies.security.swift_strategy import (
            SwiftSecurityStrategy,
        )

        registry = cls()
        registry.register(SecretDetectionStrategy())
        registry.register(PhpSecurityStrategy())
        registry.register(JavaScriptSecurityStrategy())
        registry.register(PythonSecurityStrategy())
        registry.register(GoSecurityStrategy())
        registry.register(RubySecurityStrategy())
        registry.register(JavaSecurityStrategy())
        registry.register(KotlinSecurityStrategy())
        registry.register(CSharpSecurityStrategy())
        registry.register(RustSecurityStrategy())
        registry.register(SwiftSecurityStrategy())
        registry.register(DartSecurityStrategy())
        return registry
