#!/usr/bin/env python3
"""
Debug Info Generator for Claude Code Hooks Daemon

Generates comprehensive debug information for bug reports.
Auto-detects all project-specific paths and tests daemon health.

Usage:
    ./scripts/debug_info.py [output_file]

If output_file not specified, writes to stdout.
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class DebugInfoGenerator:
    """Generate debug information for daemon troubleshooting."""

    def __init__(self, output_file: str | None = None):
        """Initialize generator.

        Args:
            output_file: Optional file path to write output (None = stdout)
        """
        self.output_file = output_file
        self.output_lines: list[str] = []

        # Detect project root
        script_dir = Path(__file__).parent
        self.project_root = script_dir.parent

        # Colors (disabled if writing to file)
        if output_file:
            self.BOLD = ""
            self.GREEN = ""
            self.RED = ""
            self.YELLOW = ""
            self.RESET = ""
        else:
            self.BOLD = "\033[1m"
            self.GREEN = "\033[32m"
            self.RED = "\033[31m"
            self.YELLOW = "\033[33m"
            self.RESET = "\033[0m"

    def output(self, line: str = "") -> None:
        """Add line to output buffer."""
        self.output_lines.append(line)

    def flush_output(self) -> None:
        """Write buffered output to file or stdout."""
        text = "\n".join(self.output_lines)
        if self.output_file:
            with open(self.output_file, "w") as f:
                f.write(text)
            print(f"Debug information written to: {self.output_file}")
        else:
            print(text)

    def run_command(self, cmd: list[str], check: bool = False) -> tuple[str, int]:
        """Run command and return output + exit code."""
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=check, cwd=self.project_root
            )
            return result.stdout + result.stderr, result.returncode
        except subprocess.CalledProcessError as e:
            return e.stdout + e.stderr, e.returncode
        except Exception as e:
            return f"ERROR: {e}", 1

    def get_daemon_paths(self) -> dict[str, str] | None:
        """Get daemon paths by sourcing init.sh."""
        init_sh = self.project_root / ".claude" / "init.sh"
        if not init_sh.exists():
            return None

        cmd = f"cd {self.project_root} && source .claude/init.sh 2>&1 && echo PROJECT_PATH=$PROJECT_PATH && echo HOOKS_DAEMON_ROOT_DIR=$HOOKS_DAEMON_ROOT_DIR && echo PYTHON_CMD=$PYTHON_CMD && echo SOCKET_PATH=$SOCKET_PATH && echo PID_PATH=$PID_PATH"
        output, code = self.run_command(["bash", "-c", cmd])
        if code != 0:
            return None

        paths = {}
        for line in output.splitlines():
            if "=" in line and not line.startswith("++"):
                key, _, value = line.partition("=")
                paths[key.strip()] = value.strip()

        return paths if len(paths) >= 5 else None

    def generate(self) -> None:
        """Generate full debug report."""
        self.output(f"{self.BOLD}# Claude Code Hooks Daemon - Debug Information{self.RESET}")
        self.output()
        self.output(
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        self.output()

        # System Information
        self.output(f"{self.BOLD}## System Information{self.RESET}")
        self.output()
        self.output("```")
        hostname, _ = self.run_command(["hostname"])
        self.output(f"Hostname: {hostname.strip()}")
        uname_s, _ = self.run_command(["uname", "-s"])
        self.output(f"OS: {uname_s.strip()}")
        uname_r, _ = self.run_command(["uname", "-r"])
        self.output(f"Kernel: {uname_r.strip()}")
        uname_m, _ = self.run_command(["uname", "-m"])
        self.output(f"Architecture: {uname_m.strip()}")
        which_py, _ = self.run_command(["which", "python3"])
        self.output(f"Python: {which_py.strip() or 'not found'}")
        py_ver, _ = self.run_command(["python3", "--version"])
        self.output(f"Python Version: {py_ver.strip() or 'N/A'}")
        self.output("```")
        self.output()

        # Project Paths
        self.output(f"{self.BOLD}## Project Paths{self.RESET}")
        self.output()
        self.output("```")
        self.output(f"Project Root: {self.project_root}")
        self.output(f"Working Directory: {Path.cwd()}")
        self.output("```")
        self.output()

        # Daemon Configuration
        self.output(f"{self.BOLD}## Daemon Configuration{self.RESET}")
        self.output()

        paths = self.get_daemon_paths()
        if not paths:
            self.output(
                f"{self.RED}ERROR: Could not detect daemon paths (.claude/init.sh missing or failed){self.RESET}"
            )
            self.output()
            self.flush_output()
            return

        self.output("```")
        self.output(f"Daemon Root: {paths.get('HOOKS_DAEMON_ROOT_DIR', 'N/A')}")
        self.output(f"Python Command: {paths.get('PYTHON_CMD', 'N/A')}")
        self.output(f"Socket Path: {paths.get('SOCKET_PATH', 'N/A')}")
        self.output(f"PID Path: {paths.get('PID_PATH', 'N/A')}")
        self.output("```")
        self.output()

        python_cmd = paths.get("PYTHON_CMD", "")
        socket_path = paths.get("SOCKET_PATH", "")
        pid_path = paths.get("PID_PATH", "")

        if not Path(python_cmd).exists():
            self.output(f"{self.RED}ERROR: Python venv not found at {python_cmd}{self.RESET}")
            self.output()
            self.flush_output()
            return

        # Daemon Status
        self.output(f"{self.BOLD}## Daemon Status{self.RESET}")
        self.output()
        self.output("```")
        status_out, _ = self.run_command(
            [python_cmd, "-m", "claude_code_hooks_daemon.daemon.cli", "status"]
        )
        self.output(status_out.strip())
        self.output("```")
        self.output()

        # File System State
        self.output(f"{self.BOLD}## File System State{self.RESET}")
        self.output()
        self.output("### Socket File")
        self.output("```")
        socket_p = Path(socket_path)
        if socket_p.exists() and socket_p.is_socket():
            self.output(f"{self.GREEN}EXISTS{self.RESET} (socket)")
            ls_out, _ = self.run_command(["ls", "-l", socket_path])
            self.output(ls_out.strip())
        else:
            self.output(f"{self.RED}NOT FOUND{self.RESET}")
        self.output("```")
        self.output()

        self.output("### PID File")
        self.output("```")
        pid_p = Path(pid_path)
        if pid_p.exists():
            self.output(f"{self.GREEN}EXISTS{self.RESET}")
            ls_out, _ = self.run_command(["ls", "-l", pid_path])
            self.output(ls_out.strip())
            try:
                pid_content = pid_p.read_text().strip()
                self.output(f"PID: {pid_content}")
            except Exception:
                self.output("PID: unable to read")
        else:
            self.output(f"{self.RED}NOT FOUND{self.RESET}")
        self.output("```")
        self.output()

        # Process State
        self.output(f"{self.BOLD}## Process State{self.RESET}")
        self.output()
        self.output("### Python Daemon Processes")
        self.output("```")
        ps_out, _ = self.run_command(["ps", "aux"])
        daemon_procs = [
            line
            for line in ps_out.splitlines()
            if "claude_code_hooks_daemon" in line and "grep" not in line
        ]
        if daemon_procs:
            self.output("\n".join(daemon_procs))
        else:
            self.output("No daemon processes found")
        self.output("```")
        self.output()

        # Check if PID is running
        if pid_p.exists():
            try:
                pid = int(pid_p.read_text().strip())
                self.output(f"### Process {pid} Details")
                self.output("```")
                _, kill_code = self.run_command(["kill", "-0", str(pid)])
                if kill_code == 0:
                    self.output(f"{self.GREEN}Process {pid} is RUNNING{self.RESET}")
                    ps_detail, _ = self.run_command(
                        ["ps", "-p", str(pid), "-o", "pid,ppid,cmd,etime,stat"]
                    )
                    self.output(ps_detail.strip())
                else:
                    self.output(
                        f"{self.RED}Process {pid} is NOT RUNNING (stale PID file){self.RESET}"
                    )
                self.output("```")
                self.output()
            except Exception:
                pass

        # Configuration Files
        self.output(f"{self.BOLD}## Configuration Files{self.RESET}")
        self.output()

        config_file = self.project_root / ".claude" / "hooks-daemon.yaml"
        if config_file.exists():
            self.output(f"### {config_file}")
            self.output("```yaml")
            self.output(config_file.read_text())
            self.output("```")
        else:
            self.output(f"{self.RED}Configuration file not found: {config_file}{self.RESET}")
        self.output()

        env_file = self.project_root / ".claude" / "hooks-daemon.env"
        if env_file.exists():
            self.output(f"### {env_file}")
            self.output("```bash")
            self.output(env_file.read_text())
            self.output("```")
            self.output()

        # Hook Tests
        self.output(f"{self.BOLD}## Hook Test{self.RESET}")
        self.output()

        pre_tool_use = self.project_root / ".claude" / "hooks" / "pre-tool-use"
        if pre_tool_use.exists():
            self.output("### Testing PreToolUse hook with simple command")
            self.output("```")
            test_input = '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'
            test_out, _ = self.run_command(
                ["bash", "-c", f"echo '{test_input}' | {pre_tool_use}"]
            )
            self.output(test_out.strip())
            self.output("```")
            self.output()

            self.output("### Testing PreToolUse hook with destructive git command")
            self.output("```")
            test_input = '{"tool_name":"Bash","tool_input":{"command":"git reset --hard HEAD"}}'
            test_out, _ = self.run_command(
                ["bash", "-c", f"echo '{test_input}' | {pre_tool_use}"]
            )
            self.output(test_out.strip())
            self.output("```")
            self.output()

        # Daemon Logs
        self.output(f"{self.BOLD}## Daemon Logs{self.RESET}")
        self.output()
        self.output("### Memory Logs (via CLI)")
        self.output("```")
        logs_out, _ = self.run_command(
            [python_cmd, "-m", "claude_code_hooks_daemon.daemon.cli", "logs"]
        )
        log_lines = logs_out.strip().splitlines()
        self.output("\n".join(log_lines[-50:]))
        self.output("```")
        self.output()

        # Installed Handlers
        self.output(f"{self.BOLD}## Installed Handlers{self.RESET}")
        self.output()
        self.output("```")

        handlers_script = f"""
import sys
sys.path.insert(0, '{paths.get('HOOKS_DAEMON_ROOT_DIR', '')}')

from claude_code_hooks_daemon.handlers.registry import HandlerRegistry
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.config.loader import ConfigLoader

try:
    config_file = '{config_file}'
    try:
        config = ConfigLoader.load(config_file)
        handler_config = config.get('handlers', {{}})
    except Exception as e:
        print(f'Warning: Could not load config: {{e}}')
        handler_config = {{}}

    router = EventRouter()
    registry = HandlerRegistry()
    num_discovered = registry.discover()
    print(f'Discovered {{num_discovered}} handler classes')
    print()

    num_registered = registry.register_all(router, config=handler_config)
    print(f'Total handlers registered: {{num_registered}}')
    print()

    for event_type in sorted(router._chains.keys(), key=lambda e: e.value):
        chain = router._chains[event_type]
        handlers = chain._handlers
        print(f'{{event_type.value}}: {{len(handlers)}} handlers')
        for h in sorted(handlers, key=lambda x: x.priority):
            term = 'terminal' if h.terminal else 'non-terminal'
            tags = ', '.join(h.tags) if h.tags else 'no tags'
            print(f'  [{{h.priority:2d}}] {{h.name:30s}} ({{term}}, {{tags}})')
        print()

except Exception as e:
    import traceback
    print(f'ERROR: {{e}}')
    traceback.print_exc()
"""

        handlers_out, _ = self.run_command([python_cmd, "-c", handlers_script])
        self.output(handlers_out.strip())
        self.output("```")
        self.output()

        # Summary
        self.output(f"{self.BOLD}## Summary{self.RESET}")
        self.output()

        daemon_running = "RUNNING" in status_out
        hooks_working = "decision" in test_out if pre_tool_use.exists() else False
        handlers_loaded = (
            "Total handlers registered:" in handlers_out and "Traceback" not in handlers_out
        )

        self.output("| Check | Status |")
        self.output("|-------|--------|")
        self.output(
            f"| Daemon Running | {self.GREEN + 'YES' + self.RESET if daemon_running else self.RED + 'NO' + self.RESET} |"
        )
        self.output(
            f"| Hooks Working | {self.GREEN + 'YES' + self.RESET if hooks_working else self.RED + 'NO' + self.RESET} |"
        )
        self.output(
            f"| Handlers Loaded | {self.GREEN + 'YES' + self.RESET if handlers_loaded else self.RED + 'NO' + self.RESET} |"
        )
        self.output()


def main() -> None:
    """Main entry point."""
    output_file = sys.argv[1] if len(sys.argv) > 1 else None

    if output_file:
        print(f"Writing debug info to: {output_file}")

    generator = DebugInfoGenerator(output_file)
    generator.generate()
    generator.flush_output()

    if output_file:
        print("You can now copy/paste this file into GitHub issues.")


if __name__ == "__main__":
    main()
