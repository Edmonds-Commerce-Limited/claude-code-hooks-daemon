#!/usr/bin/env python3
"""
Handler Status Reporter for Claude Code Hooks Daemon

Generates a comprehensive report of all available handlers and their
configuration status. Use after install/upgrade to verify setup.

Usage:
    # From daemon project root:
    ./scripts/handler_status.py

    # From client project:
    .claude/hooks-daemon/scripts/handler_status.py

Output:
    - Table of all handlers with enabled/disabled status
    - Handler-specific configuration options
    - Summary statistics
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


class HandlerStatusReporter:
    """Generate handler status report."""

    def __init__(self):
        """Initialize reporter and detect paths."""
        # Detect project root (walks up from script location)
        script_dir = Path(__file__).parent
        self.daemon_root = script_dir.parent

        # Determine if this is self-install mode by checking config
        self_install_mode = self._detect_self_install_mode()

        # Check if we're in daemon project or client project
        if self_install_mode:
            # Running from daemon project (self-install mode)
            self.project_root = self.daemon_root
            self.config_path = self.daemon_root / ".claude" / "hooks-daemon.yaml"
        else:
            # Running from client project
            self.project_root = self.daemon_root.parent.parent  # .claude/hooks-daemon -> project
            self.config_path = self.daemon_root.parent / "hooks-daemon.yaml"

        # Ensure we can import daemon modules
        if str(self.daemon_root / "src") not in sys.path:
            sys.path.insert(0, str(self.daemon_root / "src"))

    def _detect_self_install_mode(self) -> bool:
        """Detect if running in self-install mode.

        Returns:
            True if self-install mode, False if client project
        """
        # First, check config in potential self-install location
        self_install_config = self.daemon_root / ".claude" / "hooks-daemon.yaml"
        if self_install_config.exists():
            try:
                with open(self_install_config, "r") as f:
                    config = yaml.safe_load(f)
                    if config and config.get("daemon", {}).get("self_install_mode"):
                        return True
            except Exception:
                pass

        # If not self-install, it must be a client project
        # (daemon is installed at .claude/hooks-daemon/)
        return False

    def load_config(self) -> dict[str, Any]:
        """Load config from hooks-daemon.yaml."""
        if not self.config_path.exists():
            print(f"⚠️  Config not found: {self.config_path}", file=sys.stderr)
            return {"handlers": {}}

        try:
            with open(self.config_path, "r") as f:
                config = yaml.safe_load(f)
                return config or {"handlers": {}}
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}", file=sys.stderr)
            return {"handlers": {}}

    def discover_handlers(self) -> dict[str, list[dict[str, Any]]]:
        """Discover all available handlers using HandlerRegistry."""
        try:
            from claude_code_hooks_daemon.handlers.registry import (
                EVENT_TYPE_MAPPING,
            )
            from claude_code_hooks_daemon.core.handler import Handler
        except ImportError as e:
            print(f"ERROR: Cannot import daemon modules: {e}", file=sys.stderr)
            sys.exit(1)

        handlers_dir = self.daemon_root / "src" / "claude_code_hooks_daemon" / "handlers"
        result: dict[str, list[dict[str, Any]]] = {}

        for dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_dir = handlers_dir / dir_name
            if not event_dir.is_dir():
                continue

            handlers = []
            for py_file in event_dir.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue

                mod = f"claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}"
                try:
                    module = importlib.import_module(mod)
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, Handler)
                            and attr is not Handler
                        ):
                            instance = attr()
                            handlers.append(
                                {
                                    "class": attr.__name__,
                                    "handler_id": instance.handler_id,
                                    "name": instance.name,
                                    "priority": instance.priority,
                                    "terminal": instance.terminal,
                                    "tags": list(instance.tags) if hasattr(instance, "tags") else [],
                                    "doc": (
                                        (attr.__doc__ or "").strip().split("\n")[0]
                                        if attr.__doc__
                                        else ""
                                    ),
                                }
                            )
                except Exception as e:
                    handlers.append({"module": mod, "error": str(e)})

            if handlers:
                result[dir_name] = sorted(handlers, key=lambda h: h.get("priority", 99))

        return result

    def generate_report(self) -> str:
        """Generate handler status report."""
        config = self.load_config()
        handlers_config = config.get("handlers", {})
        all_handlers = self.discover_handlers()

        lines = []
        lines.append("=" * 100)
        lines.append("CLAUDE CODE HOOKS DAEMON - HANDLER STATUS REPORT")
        lines.append("=" * 100)
        lines.append("")
        lines.append(f"Config: {self.config_path}")
        lines.append(f"Daemon: {self.daemon_root}")
        lines.append("")

        # Statistics
        total_handlers = sum(len(handlers) for handlers in all_handlers.values())
        enabled_count = 0
        disabled_count = 0

        for event_type, handlers in all_handlers.items():
            event_config = handlers_config.get(event_type, {})
            for handler in handlers:
                if "error" in handler:
                    continue
                handler_config = event_config.get(handler["name"], {})
                if handler_config.get("enabled", False):
                    enabled_count += 1
                else:
                    disabled_count += 1

        lines.append(f"Total Handlers: {total_handlers}")
        lines.append(f"Enabled: {enabled_count}")
        lines.append(f"Disabled: {disabled_count}")
        lines.append("")
        lines.append("=" * 100)
        lines.append("")

        # Handler tables by event type
        for event_type, handlers in sorted(all_handlers.items()):
            event_config = handlers_config.get(event_type, {})

            lines.append("")
            lines.append(f"{'=' * 100}")
            lines.append(f"EVENT TYPE: {event_type}")
            lines.append(f"{'=' * 100}")
            lines.append("")

            if not handlers:
                lines.append("  (No handlers)")
                continue

            # Table header
            lines.append(
                f"{'Handler':<30} {'Enabled':<8} {'Priority':<9} {'Terminal':<9} {'Tags':<30}"
            )
            lines.append("-" * 100)

            # Handler rows
            for handler in handlers:
                if "error" in handler:
                    lines.append(f"  ERROR: {handler['module']} - {handler['error']}")
                    continue

                handler_config = event_config.get(handler["name"], {})
                enabled = "✓ YES" if handler_config.get("enabled", False) else "✗ NO"
                terminal = "YES" if handler["terminal"] else "NO"
                tags = ", ".join(handler["tags"][:3])  # Show first 3 tags
                if len(handler["tags"]) > 3:
                    tags += "..."

                lines.append(
                    f"{handler['name']:<30} {enabled:<8} {handler['priority']:<9} "
                    f"{terminal:<9} {tags:<30}"
                )

                # Show handler-specific config options (if enabled and has options)
                if handler_config.get("enabled", False):
                    # Filter out standard keys
                    standard_keys = {"enabled", "priority", "terminal"}
                    custom_options = {
                        k: v for k, v in handler_config.items() if k not in standard_keys
                    }

                    if custom_options:
                        lines.append(f"  Config: {json.dumps(custom_options, indent=2)}")

            lines.append("")

        # Summary
        lines.append("")
        lines.append("=" * 100)
        lines.append("SUMMARY")
        lines.append("=" * 100)
        lines.append("")
        lines.append(f"✓ {enabled_count} handlers enabled")
        lines.append(f"✗ {disabled_count} handlers disabled")
        lines.append("")

        # Tag filtering info
        enable_tags = []
        disable_tags = []
        for event_type, event_config in handlers_config.items():
            if "enable_tags" in event_config:
                enable_tags.extend(event_config["enable_tags"])
            if "disable_tags" in event_config:
                disable_tags.extend(event_config["disable_tags"])

        if enable_tags or disable_tags:
            lines.append("TAG FILTERING:")
            if enable_tags:
                lines.append(f"  Enabled tags: {', '.join(set(enable_tags))}")
            if disable_tags:
                lines.append(f"  Disabled tags: {', '.join(set(disable_tags))}")
            lines.append("")

        lines.append("=" * 100)

        return "\n".join(lines)


def main() -> None:
    """Main entry point."""
    reporter = HandlerStatusReporter()
    report = reporter.generate_report()
    print(report)


if __name__ == "__main__":
    main()
