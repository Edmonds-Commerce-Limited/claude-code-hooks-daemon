#!/usr/bin/env python3
"""
Debug Info Generator for Claude Code Hooks Daemon

Generates comprehensive debug information for bug reports.
Auto-detects all project-specific paths and tests daemon health.

Usage:
    ./scripts/debug_info.py [output_file]

If output_file not specified, writes to stdout.
"""

import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType


class DebugInfoGenerator:
    """Generate debug information for daemon troubleshooting."""

    def __init__(self, output_file: str | None = None, project_root: Path | None = None):
        """Initialize generator.

        Args:
            output_file: Optional file path to write output (None = stdout)
            project_root: Optional explicit project root (testability seam).
                When omitted it is detected via :meth:`_detect_project_root`.
        """
        self.output_file = output_file
        self.output_lines: list[str] = []
        self._flushed = False

        # Plan 00122 BUG 4: detect the CLIENT project root, not the daemon's own
        # clone. Previously this was Path(__file__).parent.parent which, in a
        # client install, points at {client}/.claude/hooks-daemon — the clone —
        # so every path below resolved against the wrong directory.
        self.project_root = (
            project_root if project_root is not None else self._detect_project_root()
        )

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

    def _emit_env_summary(self, env_file: Path) -> None:
        """Report which env settings are SET, never what they are set to.

        This file used to be copied into the report verbatim, under a guide
        whose next instruction was to paste the report into a GitHub issue. An
        ``.env`` file is a conventional home for credentials, the tracker is
        public, and a public issue cannot be retracted afterwards.

        Which keys are present is the diagnostic fact that actually helps —
        a value never is. A comment line is dropped entirely rather than listed,
        because a comment is free text and can say anything, including why a
        credential is there.
        """
        if not env_file.exists():
            return

        self.output(f"### {env_file}")
        try:
            raw = env_file.read_text()
        except OSError as exc:
            # The report IS the log here. A file that exists but cannot be read
            # is itself a diagnostic fact — a permission problem on
            # `.claude/` is a plausible cause of the daemon misbehaving — so it
            # is recorded where whoever reads the report will see it.
            self.output(f"(could not be read: {exc})")
        else:
            keys = [
                line.split("=", 1)[0].strip()
                for line in raw.splitlines()
                if "=" in line and not line.lstrip().startswith("#")
            ]
            if keys:
                self.output("Keys set (values withheld — this report may be shared):")
                self.output("```")
                for key in keys:
                    self.output(f"{key}=<set>")
                self.output("```")
            else:
                # "Present but empty" and "absent" are different diagnostic
                # facts; the early return above already covers the second.
                self.output("(present, no settings)")
        self.output()

    def _scrub(self, text: str) -> str:
        """Replace the client's identifiers with placeholders.

        The daemon package is imported HERE rather than at module scope, and
        the failure is announced rather than swallowed. This script's whole
        value is running when the daemon is broken, so it must not refuse to
        produce a report just because the package will not import — but a
        report that silently skipped redaction would look exactly like one that
        did not need it, which is the worse outcome of the two.
        """
        scrubber = self._load_daemon_util("report_scrubbing")
        if scrubber is None:
            return (
                "> **NOT REDACTED.** `utils/report_scrubbing.py` could not be "
                "loaded, so absolute paths, hostname and secret terms are still "
                "present below. Redact this by hand before sharing it.\n\n"
                f"{text}"
            )

        # The secret word list is a SEPARATE, best-effort layer: resolving it
        # reads project config. Path and hostname scrubbing must not be lost
        # just because that fails — surviving a broken daemon is the whole
        # reason this script exists.
        terms = self._secret_terms()

        scrubbed = str(
            scrubber.scrub_report(
                text,
                project_root=self.project_root,
                home=Path.home(),
                hostname=os.environ.get("HOSTNAME") or socket.gethostname(),
                secret_terms=terms or (),
            )
        )
        if terms is None:
            scrubbed = (
                "> **Secret word list not applied.** Paths and hostname are "
                "redacted below, but this project's declared secret terms could "
                "not be loaded on this interpreter. Check for them by hand "
                "before sharing.\n\n"
            ) + scrubbed
        return scrubbed

    def _secret_terms(self) -> tuple[str, ...] | None:
        """The project's declared secret terms, or ``None`` if unobtainable.

        Resolving them reads project config through `ProjectContext`, which
        needs the daemon's dependencies — so this fails on a bare interpreter
        even though the redaction module itself does not. Returning ``None``
        rather than raising is the point: failing to load a word list must
        degrade the report to a warned, partially-scrubbed one, never abort it.
        A missing report helps nobody diagnose anything.
        """
        secrets = self._load_daemon_util("secret_redaction")
        if secrets is None:
            return None
        try:
            return tuple(secrets.get_active_secret_terms())
        except (ImportError, OSError, ValueError) as exc:
            print(f"warning: secret word list unavailable: {exc}", file=sys.stderr)
            return None

    @staticmethod
    def _load_daemon_util(name: str) -> ModuleType | None:
        """Load one daemon util BY PATH, without importing the package.

        `claude_code_hooks_daemon/__init__.py` pulls in the front controller and
        therefore pydantic, so `import claude_code_hooks_daemon.utils.x` fails on
        a bare interpreter — which is the ordinary way this script is run, and
        the run during which a report most needs redacting. Both modules loaded
        here are pure stdlib at import time, so loading the FILE sidesteps the
        dependency without duplicating the logic into this script.

        The package sits beside this script in both layouts: `<repo>/src/` when
        self-installed, `<project>/.claude/hooks-daemon/src/` in a client.
        """
        import importlib.util

        path = (
            Path(__file__).resolve().parent.parent
            / "src"
            / "claude_code_hooks_daemon"
            / "utils"
            / f"{name}.py"
        )
        if not path.is_file():
            print(f"warning: {path} not found; not redacting with it", file=sys.stderr)
            return None

        spec = importlib.util.spec_from_file_location(f"_debug_info_{name}", path)
        if spec is None or spec.loader is None:
            print(f"warning: {path} could not be prepared for import", file=sys.stderr)
            return None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            # Reported, never swallowed: the caller turns a None into a banner
            # on the report itself, so an unredacted report can never look like
            # a redacted one.
            print(f"warning: could not load {name}: {exc}", file=sys.stderr)
            return None
        return module

    def flush_output(self) -> None:
        """Write buffered output to file or stdout, scrubbed either way.

        Idempotent. `generate()` flushes and returns on each of its early-exit
        paths, and `main()` flushes again afterwards — so the degraded report,
        the one produced when something is already wrong, was written twice and
        announced twice.
        """
        if self._flushed:
            return
        self._flushed = True
        text = self._scrub("\n".join(self.output_lines))
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

    def _detect_project_root(self) -> Path:
        """Locate the CLIENT project root: the nearest ancestor containing
        ``.claude/hooks-daemon.yaml``.

        Searches up from the cwd first (the operator runs this from their
        project), then from the script's own location, and finally falls back
        to the script's grandparent (legacy behaviour) so the tool still
        produces something even in an unconfigured tree.
        """
        marker = Path(".claude") / "hooks-daemon.yaml"
        for start in (Path.cwd(), Path(__file__).resolve().parent):
            current = start
            while True:
                if (current / marker).is_file():
                    return current
                if current.parent == current:
                    break
                current = current.parent
        return Path(__file__).resolve().parent.parent

    def _untracked_dir(self) -> Path:
        """Daemon runtime dir for ``self.project_root``.

        Mirrors ``daemon.paths._get_untracked_dir``: ``{root}/untracked`` in
        self-install mode, else ``{root}/.claude/hooks-daemon/untracked``.
        """
        if (self.project_root / "src" / "claude_code_hooks_daemon").is_dir():
            return self.project_root / "untracked"
        return self.project_root / ".claude" / "hooks-daemon" / "untracked"

    def _emit_degraded_diagnostics(self) -> None:
        """Dump init.sh-independent state when path detection fails.

        These are exactly the things needed to diagnose the macOS socket bug
        (Plan 00122 BUG 1): runtime files (mismatched suffixes are the tell),
        venv state, and live daemon processes. Previously the report stopped at
        a single error line and emitted none of this.
        """
        untracked = self._untracked_dir()

        self.output(f"{self.BOLD}## Runtime Files (degraded){self.RESET}")
        self.output()
        self.output("```")
        self.output(f"Untracked dir: {untracked}")
        if untracked.is_dir():
            entries = sorted(p.name for p in untracked.iterdir() if p.name.startswith("daemon-"))
            self.output("\n".join(entries) if entries else "(no daemon-* runtime files)")
        else:
            self.output("(untracked dir does not exist)")
        self.output("```")
        self.output()

        self.output(f"{self.BOLD}## Virtualenv State (degraded){self.RESET}")
        self.output()
        self.output("```")
        if untracked.is_dir():
            venvs = sorted(
                p.name for p in untracked.iterdir() if p.is_dir() and p.name.startswith("venv")
            )
            self.output("\n".join(venvs) if venvs else "(no venv-* directories)")
        else:
            self.output("(untracked dir does not exist)")
        self.output("```")
        self.output()

        self.output(f"{self.BOLD}## Process State (degraded){self.RESET}")
        self.output()
        self.output("```")
        ps_out, _ = self.run_command(["ps", "aux"])
        daemon_procs = [
            line
            for line in ps_out.splitlines()
            if "claude_code_hooks_daemon" in line and "grep" not in line
        ]
        self.output("\n".join(daemon_procs) if daemon_procs else "No daemon processes found")
        self.output("```")
        self.output()

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
        self.output(f"Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
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
            # Plan 00122 BUG 4: degrade gracefully instead of bailing. The
            # init.sh-independent diagnostics below (runtime files, venv state,
            # daemon processes) are precisely what's needed to diagnose the
            # macOS socket bug — emit them rather than a bare error line.
            self.output(
                f"{self.YELLOW}NOTE: Could not detect daemon paths "
                f"(.claude/init.sh missing or failed). Emitting degraded "
                f"diagnostics below.{self.RESET}"
            )
            self.output()
            self._emit_degraded_diagnostics()
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

        # A blank PYTHON_CMD must be rejected BEFORE the exists() check:
        # Path("") is PosixPath('.'), the current directory, which always
        # exists — so a blank value passed the guard and every section below
        # then ran subprocess.run([""], ...), reporting
        # "[Errno 13] Permission denied: ''" in place of the real problem.
        if not python_cmd.strip() or not Path(python_cmd).exists():
            self.output(
                f"{self.RED}ERROR: Python venv not found at "
                f"{python_cmd or '<unset>'}{self.RESET}"
            )
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
            except Exception as exc:
                # FAIL FAST (Plan 00200 Task 5.5): a bare `except: pass` here
                # previously dropped the whole "Process Details" section with
                # no trace of why -- silent in a tool whose entire purpose is
                # producing a diagnostic report. Mirrors the sibling PID-read
                # failure above (line ~286), which already surfaces its error.
                self.output(f"Unable to determine process details: {exc}")

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

        self._emit_env_summary(self.project_root / ".claude" / "hooks-daemon.env")

        # Hook Tests
        self.output(f"{self.BOLD}## Hook Test{self.RESET}")
        self.output()

        pre_tool_use = self.project_root / ".claude" / "hooks" / "pre-tool-use"
        test_out = ""
        if pre_tool_use.exists():
            self.output("### Testing PreToolUse hook with simple command")
            self.output("```")
            test_input = '{"tool_name":"Bash","tool_input":{"command":"echo hello"}}'
            test_out, _ = self.run_command(["bash", "-c", f"echo '{test_input}' | {pre_tool_use}"])
            self.output(test_out.strip())
            self.output("```")
            self.output()

            self.output("### Testing PreToolUse hook with destructive git command")
            self.output("```")
            test_input = '{"tool_name":"Bash","tool_input":{"command":"git reset --hard HEAD"}}'
            test_out, _ = self.run_command(["bash", "-c", f"echo '{test_input}' | {pre_tool_use}"])
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
        print(
            "This report is for YOU to read. Absolute paths, hostname and any\n"
            "declared secret terms have been replaced with placeholders, but\n"
            "nothing else has: config values, log lines and command output are\n"
            "as captured. Before sharing it, see BUG_REPORTING.md — the tracker\n"
            "is PUBLIC and an issue cannot be retracted once posted."
        )


if __name__ == "__main__":
    main()
