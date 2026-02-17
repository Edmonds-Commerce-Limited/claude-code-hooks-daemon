---
name: hooks-daemon
description: Manage Claude Code Hooks Daemon - upgrade versions, check health, and develop project-level handlers
argument-hint: "[upgrade|health|dev-handlers|logs] [args...]"
disable-model-invocation: true
user-invocable: true
allowed-tools: Bash, Read, Write, Edit
---

# Hooks Daemon Management

Manage your Claude Code Hooks Daemon installation with these commands.

## Available Commands

### Upgrade Daemon
Update to a new version of the hooks daemon:
```bash
/hooks-daemon upgrade          # Auto-detect and upgrade to latest version
/hooks-daemon upgrade 2.14.0   # Upgrade to specific version
/hooks-daemon upgrade --force  # Force reinstall current version
```

See [upgrade.md](upgrade.md) for detailed upgrade documentation.

### Check Health & Status
Verify daemon is running correctly:
```bash
/hooks-daemon health           # Quick health check
/hooks-daemon logs             # View last 50 lines of logs
/hooks-daemon logs --follow    # Stream logs in real-time
```

See [health.md](health.md) for health check details.

### Develop Project Handlers
Scaffold new project-level handlers:
```bash
/hooks-daemon dev-handlers     # Interactive handler scaffolding
```

See [dev-handlers.md](dev-handlers.md) for handler development guide.

## Quick Start

If you're experiencing issues:
```bash
# 1. Check daemon status
/hooks-daemon health

# 2. View recent logs
/hooks-daemon logs

# 3. If needed, restart manually
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

## Troubleshooting

See [references/troubleshooting.md](references/troubleshooting.md) for common issues and solutions.

## Implementation

Parse subcommand and route to appropriate script:

```bash
# Get skill directory (where this SKILL.md is located)
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse subcommand from $ARGUMENTS
SUBCOMMAND="${1:-help}"
shift || true  # Remove subcommand from arguments

# Route to appropriate script
case "$SUBCOMMAND" in
    upgrade)
        bash "$SKILL_DIR/scripts/upgrade.sh" "$@"
        ;;

    health)
        bash "$SKILL_DIR/scripts/health-check.sh" "$@"
        ;;

    dev-handlers)
        bash "$SKILL_DIR/scripts/init-handlers.sh" "$@"
        ;;

    logs|status|restart|handlers|validate-config)
        # Forward to daemon CLI wrapper
        bash "$SKILL_DIR/scripts/daemon-cli.sh" "$SUBCOMMAND" "$@"
        ;;

    help|--help|-h|"")
        # Show help (this SKILL.md content)
        echo "Usage: /hooks-daemon <command> [args...]"
        echo ""
        echo "Available commands:"
        echo "  upgrade [VERSION]     Upgrade daemon to new version"
        echo "  health                Check daemon health and status"
        echo "  dev-handlers          Scaffold new project handlers"
        echo "  logs [--follow]       View daemon logs"
        echo "  status                Show daemon status"
        echo "  restart               Restart daemon"
        echo "  handlers              List loaded handlers"
        echo ""
        echo "For detailed documentation, see the skill files or run:"
        echo "  /hooks-daemon <command> --help"
        ;;

    *)
        echo "Error: Unknown subcommand: $SUBCOMMAND"
        echo ""
        echo "Usage: /hooks-daemon <command> [args...]"
        echo "Run '/hooks-daemon help' for available commands."
        exit 1
        ;;
esac
```

**Note**: All daemon management commands require manual user approval. The daemon will not auto-invoke these operations.
