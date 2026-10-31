"""Plan 00555 Task 2.5 (b): while the daemon is unreachable, init.sh's fail-closed
PreToolUse guard permits an exact-shape read-only set plus ``diagnose``.

Drives the REAL init.sh (``_hooks_daemon_stdin_judge``), never a re-implementation.
Everything not listed stays DENIED: protected paths, shell metacharacters,
unlisted commands, anything outside the project.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.utils.secret_file_matching import DEFAULT_PROTECTED_PATTERNS

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"
SNAPSHOT_NAME = ".protected-paths.snapshot"

# Protected names are assembled so this file itself names no protected path.
_PROTECTED = {
    "@PROT@": ".claude/block-words" + "." + "secret",
    "@BAK@": "foo" + "." + "secret.bak",
    "@VPASS@": "." + "vault-" + "pass",
    "@VPW@": "deploy." + "vault-" + "password",
    "@VUND@": "my_vault" + "_pass.txt",
    "@RSA@": "id" + "_rsa",
    "@ED@": "id_" + "ed25519",
}


def _x(text: str) -> str:
    for placeholder, value in _PROTECTED.items():
        text = text.replace(placeholder, value)
    return text


def _make_project(root: Path) -> Path:
    """A client project: init.sh, both launchers, a daemon root with a snapshot."""
    daemon_root = root / ".claude" / "hooks-daemon"
    (daemon_root / "untracked").mkdir(parents=True)
    (daemon_root / "bin").mkdir()
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    launcher = daemon_root / "bin" / "hooks-daemon"
    launcher.write_text("#!/bin/bash\n")
    (root / "bin").mkdir()
    (root / "bin" / "hooks-daemon").symlink_to(launcher)
    (root / "README.md").write_text("hello\n")
    (root / "src").mkdir()
    (root / _x("@PROT@")).write_text("x\n")
    (root / ".claude" / "notes.txt").write_text("n\n")
    (root / ".claude" / "hooks-daemon.yaml").write_text("version: '1.0'\n")
    (daemon_root / "untracked" / SNAPSHOT_NAME).write_text(
        "\n".join(DEFAULT_PROTECTED_PATTERNS) + "\n"
    )
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _make_project(tmp_path / "proj")


def _judge(project: Path, hook_input: dict[str, Any], mode: str = "permitted") -> bool:
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
    env["PROJECT_PATH"] = str(project)
    env["HOOKS_DAEMON_ROOT_DIR"] = str(project / ".claude" / "hooks-daemon")
    result = subprocess.run(
        [BASH, "-c", f"source .claude/init.sh; _hooks_daemon_stdin_judge {mode}"],
        cwd=project,
        env=env,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


def _bash(project: Path, command: str, cwd: Path | None = None) -> bool:
    return _judge(
        project,
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(cwd or project),
        },
    )


def _read(project: Path, file_path: str) -> bool:
    return _judge(
        project,
        {"tool_name": "Read", "tool_input": {"file_path": file_path}, "cwd": str(project)},
    )


class TestPermittedReadOnlyShapes:
    @pytest.mark.parametrize(
        "command",
        [
            "ls",
            "ls -la",
            "ls -ltr .claude",
            "ls -l README.md src",
            "ls ROOT",
            "cat README.md",
            "cat README.md .claude/notes.txt",
            "head -n 5 README.md",
            "tail -n 20 README.md",
            "  git log --oneline -n 5  ",
            "git log",
            "git log -5 --stat --no-pager",
            "git log --format=%H main..HEAD",
            "git log --since=2.days -- README.md",
            "git status",
            "git status -sb",
            "git status --porcelain=v2 --untracked-files=no",
            "bin/hooks-daemon diagnose",
            ".claude/hooks-daemon/bin/hooks-daemon diagnose",
            "cat .claude/hooks-daemon.yaml",
        ],
    )
    def test_is_permitted(self, project: Path, command: str) -> None:
        assert _bash(project, command.replace("ROOT", str(project))) is True

    def test_read_of_a_regular_project_file(self, project: Path) -> None:
        assert _read(project, str(project / "README.md")) is True


class TestDeniedShapes:
    @pytest.mark.parametrize(
        "command",
        [
            "cat README.md; rm -rf x",
            "cat README.md && echo hi",
            "cat README.md | cat",
            "cat $(echo README.md)",
            "cat `echo README.md`",
            "cat *",
            "cat READM?.md",
            "cat [R]EADME.md",
            "cat ~/x",
            "cat 'README.md'",
            'cat "README.md"',
            "cat README.md > out",
            "cat < README.md",
            "cat README.md\nrm x",
            "cat \\README.md",
            "cat {README.md,x}",
            "cat (README.md)",
            "cat README.md &",
            "ls\t-la",
            "ls -R",
            "ls --all",
            "ls -lR",
            "cat -n README.md",
            "cat",
            "head -5 README.md",
            "head -n x README.md",
            "head -n 5",
            "tail -f README.md",
            "git log -p",
            "git log --patch",
            "git log -u",
            "git log --output=/tmp/x",
            "git log -c",
            "git log -C",
            "git log --git-dir=/x",
            "git -c core.pager=x log",
            "git -C /tmp log",
            "GIT_DIR=/x git log",
            "git status --bogus",
            "git diff",
            "git show",
            "git grep x",
            "git blame README.md",
            "rm README.md",
            "echo hi",
            "python3 -c 1",
            "ls /etc",
            "cat /etc/passwd",
            "cat missing.txt",
            "cat src",
            "bin/hooks-daemon upgrade",
        ],
    )
    def test_is_denied(self, project: Path, command: str) -> None:
        assert _bash(project, command) is False

    @pytest.mark.parametrize("tool", ["Grep", "Glob", "Write", "Edit", "NotebookEdit", "Task"])
    def test_other_tools_are_denied(self, project: Path, tool: str) -> None:
        hook_input = {
            "tool_name": tool,
            "tool_input": {"file_path": str(project / "README.md"), "pattern": "x"},
            "cwd": str(project),
        }
        assert _judge(project, hook_input) is False

    def test_unparseable_input_is_denied(self, project: Path) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("HOOKS_DAEMON_")}
        env["PROJECT_PATH"] = str(project)
        result = subprocess.run(
            [BASH, "-c", "source .claude/init.sh; _hooks_daemon_stdin_judge permitted"],
            cwd=project,
            env=env,
            input="not json",
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
            check=False,
        )
        assert result.returncode == 1


class TestProtectedPathsStayDenied:
    @pytest.mark.parametrize(
        "command",
        [
            "cat @PROT@",
            "cat ./src/../@PROT@",
            "cat PROJECT/@PROT@",
            "head -n 3 @PROT@",
            "tail -n 3 @PROT@",
            "ls @PROT@",
            "cat @BAK@",
            "cat @VPASS@",
            "cat @VPW@",
            "cat @VUND@",
            "cat @RSA@",
            "cat @ED@",
            "cat .claude/hooks-daemon.env",
            "cat .claude/hooks-daemon/untracked/events/x.json",
            "cat .claude/hooks-daemon/pyproject.toml",
            "cat untracked/events/x.json",
            "cat daemon.sock",
        ],
    )
    def test_cat_of_a_protected_path_is_denied(self, project: Path, command: str) -> None:
        for name in ("@BAK@", "@VPASS@", "@VPW@", "@VUND@", "@RSA@", "@ED@"):
            (project / _x(name)).write_text("s\n")
        (project / "untracked" / "events").mkdir(parents=True)
        (project / "untracked" / "events" / "x.json").write_text("{}")
        events = project / ".claude" / "hooks-daemon" / "untracked" / "events"
        events.mkdir()
        (events / "x.json").write_text("{}")
        (project / ".claude" / "hooks-daemon" / "pyproject.toml").write_text("x")
        if command.endswith("daemon.sock"):
            short = Path(tempfile.mkdtemp(prefix="hd-"))
            sock = socket.socket(socket.AF_UNIX)
            try:
                sock.bind(str(short / "d.sock"))
                (project / "daemon.sock").symlink_to(short / "d.sock")
                assert _bash(project, command) is False
            finally:
                sock.close()
                shutil.rmtree(short, ignore_errors=True)
            return
        assert _bash(project, _x(command).replace("PROJECT", str(project))) is False

    def test_read_of_a_protected_path_is_denied(self, project: Path) -> None:
        assert _read(project, str(project / _x("@PROT@"))) is False

    def test_a_symlink_to_a_protected_file_is_denied(self, project: Path) -> None:
        (project / "innocent.txt").symlink_to(project / _x("@PROT@"))
        assert _bash(project, "cat innocent.txt") is False
        assert _read(project, str(project / "innocent.txt")) is False

    def test_a_symlink_out_of_the_project_is_denied(self, project: Path) -> None:
        (project / "out.txt").symlink_to("/etc/hostname")
        assert _bash(project, "cat out.txt") is False
        assert _read(project, str(project / "out.txt")) is False

    def test_a_custom_snapshot_glob_is_honoured(self, project: Path) -> None:
        (project / "k.pem").write_text("k")
        assert _bash(project, "cat k.pem") is True
        snapshot = project / ".claude" / "hooks-daemon" / "untracked" / SNAPSHOT_NAME
        snapshot.write_text("*.pem\n")
        assert _bash(project, "cat k.pem") is False
        assert _bash(project, _x("cat @PROT@")) is False  # defaults still apply

    def test_an_absent_snapshot_locks_down_dot_claude(self, project: Path) -> None:
        (project / ".claude" / "hooks-daemon" / "untracked" / SNAPSHOT_NAME).unlink()
        assert _bash(project, "cat .claude/notes.txt") is False
        assert _read(project, str(project / ".claude" / "notes.txt")) is False
        assert _bash(project, "cat .claude/hooks-daemon.yaml") is True
        assert _bash(project, "cat README.md") is True
        (project / ".claude" / "settings.json").write_text("{}")
        assert _bash(project, "cat .claude/settings.json") is True
        assert _bash(project, _x("cat @PROT@")) is False

    def test_an_unreadable_snapshot_is_treated_as_absent(self, project: Path) -> None:
        snapshot = project / ".claude" / "hooks-daemon" / "untracked" / SNAPSHOT_NAME
        snapshot.unlink()
        snapshot.mkdir()
        assert _bash(project, "cat .claude/notes.txt") is False


class TestReadBoundaries:
    def test_outside_the_project_is_denied(self, project: Path) -> None:
        assert _read(project, "/etc/passwd") is False
        assert _read(project, "/proc/self/environ") is False

    def test_relative_path_is_denied(self, project: Path) -> None:
        assert _read(project, "README.md") is False

    def test_missing_file_is_denied(self, project: Path) -> None:
        assert _read(project, str(project / "nope.txt")) is False

    def test_directory_is_denied(self, project: Path) -> None:
        assert _read(project, str(project / "src")) is False

    def test_fifo_is_denied(self, project: Path) -> None:
        fifo = project / "pipe"
        os.mkfifo(fifo)
        assert _read(project, str(fifo)) is False
        assert _bash(project, "cat pipe") is False

    def test_non_string_file_path_is_denied(self, project: Path) -> None:
        assert (
            _judge(project, {"tool_name": "Read", "tool_input": {"file_path": 5}, "cwd": "/"})
            is False
        )

    def test_git_outside_the_project_cwd_is_denied(self, project: Path, tmp_path: Path) -> None:
        assert _bash(project, "git log", cwd=tmp_path) is False


class TestInitShProtectedDefaultsMatchTheDaemonConstant:
    def test_the_default_globs_are_pinned(self) -> None:
        # init.sh assembles the globs from parts, so the source text cannot be
        # parsed: evaluate the recovery python and read the tuple it builds.
        extracted = subprocess.run(
            [
                BASH,
                "-c",
                'source "$1"; _hooks_daemon_recovery_py src; printf %s "$src"',
                "_",
                str(INIT_SH),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        program = extracted.stdout + "\nimport json\nprint(json.dumps(list(_PROTECTED_DEFAULTS)))\n"
        evaluated = subprocess.run(
            [sys.executable, "-c", program], check=True, capture_output=True, text=True
        )
        assert tuple(json.loads(evaluated.stdout)) == DEFAULT_PROTECTED_PATTERNS


class TestEndToEndThroughTheTransport:
    """The transport's PreToolUse deny uses the same judgement when the daemon
    was never reached."""

    @pytest.fixture
    def dead_socket(self) -> Iterator[Path]:
        short = Path(tempfile.mkdtemp(prefix="hd-"))
        try:
            yield short / "none.sock"
        finally:
            shutil.rmtree(short, ignore_errors=True)

    def _send(self, project: Path, sock: Path, hook_input: dict[str, Any]) -> dict[str, Any]:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
        }
        env["CLAUDE_HOOKS_SOCKET_PATH"] = str(sock)
        env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = "0.4"
        script = (
            "source .claude/init.sh; "
            f"printf '%s' '{json.dumps(hook_input)}' | send_request_stdin 'PreToolUse'"
        )
        result = subprocess.run(
            [BASH, "-c", script],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            timeout=Timeout.REQUEST_LONG,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        parsed: dict[str, Any] = json.loads(result.stdout.strip())
        return parsed

    def test_cat_is_allowed_when_never_reached(self, project: Path, dead_socket: Path) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "cat README.md"},
            "cwd": str(project),
        }
        response = self._send(project, dead_socket, hook_input)
        assert "permissionDecision" not in response["hookSpecificOutput"]

    def test_a_protected_cat_is_denied_when_never_reached(
        self, project: Path, dead_socket: Path
    ) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": _x("cat @PROT@")},
            "cwd": str(project),
        }
        response = self._send(project, dead_socket, hook_input)
        assert response["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_a_write_is_denied_when_never_reached(self, project: Path, dead_socket: Path) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(project / "x"), "content": "x"},
            "cwd": str(project),
        }
        response = self._send(project, dead_socket, hook_input)
        assert response["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_the_deny_text_names_what_is_permitted(self, project: Path, dead_socket: Path) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "rm README.md"},
            "cwd": str(project),
        }
        response = self._send(project, dead_socket, hook_input)
        text = json.dumps(response)
        assert "diagnose" in text
        assert "read-only diagnostics" in text


def _snapshot(project: Path, *globs: str) -> None:
    path = project / ".claude" / "hooks-daemon" / "untracked" / SNAPSHOT_NAME
    path.write_text("".join(f"{glob}\n" for glob in globs))


class TestConfiguredGlobsWithASlash:
    """Review C1: a configured glob is matched in the daemon's dialect, against the
    project-relative path, not only against the basename."""

    @pytest.fixture
    def slashed(self, project: Path) -> Path:
        for rel in (
            "config/credentials.yml",
            "secrets/db.txt",
            "deploy/key.json",
            "deploy/ok.json",
        ):
            target = project / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("s\n")
        (project / "sub" / "config").mkdir(parents=True)
        (project / "sub" / "config" / "credentials.yml").write_text("s\n")
        (project / "private.txt").write_text("s\n")
        _snapshot(
            project,
            "config/credentials.yml",
            "secrets/**",
            "/deploy/key.json",
            f"{project}/private.txt",
        )
        return project

    @pytest.mark.parametrize(
        "command",
        [
            "cat config/credentials.yml",
            "cat secrets/db.txt",
            "cat deploy/key.json",
            "cat private.txt",
            "head -n 2 secrets/db.txt",
            "tail -n 2 config/credentials.yml",
            "cat sub/config/credentials.yml",
            "cat ./secrets/../secrets/db.txt",
            "git log -- secrets/db.txt",
        ],
    )
    def test_bash_is_denied(self, slashed: Path, command: str) -> None:
        assert _bash(slashed, command) is False

    @pytest.mark.parametrize(
        "rel", ["config/credentials.yml", "secrets/db.txt", "deploy/key.json", "private.txt"]
    )
    def test_read_is_denied(self, slashed: Path, rel: str) -> None:
        assert _read(slashed, str(slashed / rel)) is False

    def test_unrelated_files_stay_readable(self, slashed: Path) -> None:
        assert _bash(slashed, "cat deploy/ok.json") is True
        assert _bash(slashed, "cat README.md") is True
        assert _read(slashed, str(slashed / "deploy" / "ok.json")) is True

    def test_an_anchored_glob_does_not_match_deeper(self, slashed: Path) -> None:
        (slashed / "sub" / "deploy").mkdir()
        (slashed / "sub" / "deploy" / "key.json").write_text("s\n")
        assert _bash(slashed, "cat sub/deploy/key.json") is True


def _recovery_namespace() -> str:
    extracted = subprocess.run(
        [
            BASH,
            "-c",
            'source "$1"; _hooks_daemon_recovery_py src; printf %s "$src"',
            "_",
            str(INIT_SH),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return extracted.stdout


class TestGlobMatcherParityWithTheDaemon:
    CASES = (
        ("config/credentials.yml", "config/credentials.yml"),
        ("config/credentials.yml", "a/b/config/credentials.yml"),
        ("config/credentials.yml", "xconfig/credentials.yml"),
        ("/deploy/key.json", "deploy/key.json"),
        ("/deploy/key.json", "a/deploy/key.json"),
        ("secrets/**", "secrets/a.txt"),
        ("secrets/**", "secrets/a/b/c.txt"),
        ("secrets/**", "x/secrets/a.txt"),
        ("secrets/**", "secrets"),
        ("**/keys/*.pem", "keys/a.pem"),
        ("**/keys/*.pem", "a/b/keys/a.pem"),
        ("**/keys/*.pem", "a/b/keys/c/a.pem"),
        ("**/keys/*.pem", "xkeys/a.pem"),
        ("*.pem", "a/b/k.pem"),
        ("*.pem", "k.pem.bak"),
        ("k?.pem", "k1.pem"),
        ("k?.pem", "k/.pem"),
        ("a/*/c", "a/b/c"),
        ("a/*/c", "a/b/d/c"),
        ("a/**/c", "a/c"),
        ("a/**/c", "a/b/d/c"),
        ("/a/**", "a/b"),
        ("**", "anything/at/all"),
    )

    def test_matches_the_daemon_over_a_shared_table(self) -> None:
        from claude_code_hooks_daemon.utils.path_exclusion import _glob_fullmatch

        program = (
            _recovery_namespace()
            + "\nimport json\nprint(json.dumps([_glob_fullmatch(g, t) for g, t in "
            + repr(self.CASES)
            + "]))\n"
        )
        evaluated = subprocess.run(
            [sys.executable, "-c", program], check=True, capture_output=True, text=True
        )
        init_sh = json.loads(evaluated.stdout)
        daemon = [_glob_fullmatch(g, t) for g, t in self.CASES]
        assert init_sh == daemon


class TestSymlinkBeforeDotDot:
    """Review I1: the shell resolves a symlink before it applies a following `..`."""

    def test_dotdot_after_a_symlinked_directory_cannot_leave_the_project(
        self, project: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere"
        (outside / "inner").mkdir(parents=True)
        (outside / "README.md").write_text("OUTSIDE\n")
        (project / "lnk").symlink_to(outside / "inner")
        assert _bash(project, "cat lnk/../README.md") is False
        assert _bash(project, "head -n 1 lnk/../README.md") is False

    def test_a_plain_dotdot_inside_the_project_still_works(self, project: Path) -> None:
        assert _bash(project, "cat src/../README.md") is True

    def test_dotdot_after_a_symlink_cannot_reach_a_configured_glob(
        self, project: Path, tmp_path: Path
    ) -> None:
        (project / "secrets").mkdir()
        (project / "secrets" / "db.txt").write_text("s\n")
        _snapshot(project, "secrets/**")
        (project / "sub").mkdir()
        (project / "sub" / "secrets").symlink_to(project / "secrets")
        assert _bash(project, "cat sub/secrets/db.txt") is False


class TestQuarantineArtefactStaysDenied:
    """Review I3: quarantine_artefact_read_guard's artefact is unreadable while down."""

    @pytest.fixture
    def detail(self, project: Path) -> Path:
        target = project / "CLAUDE" / "reports" / "x-opus-security-DETAIL.md"
        target.parent.mkdir(parents=True)
        target.write_text("raw\n")
        (target.parent / "x-opus-security-SUMMARY.md").write_text("ok\n")
        return target

    def test_bash_cat_is_denied(self, detail: Path, project: Path) -> None:
        assert _bash(project, "cat CLAUDE/reports/x-opus-security-DETAIL.md") is False
        assert _bash(project, "tail -n 3 CLAUDE/reports/x-opus-security-DETAIL.md") is False

    def test_read_is_denied(self, detail: Path, project: Path) -> None:
        assert _read(project, str(detail)) is False

    def test_denied_with_the_snapshot_absent(self, detail: Path, project: Path) -> None:
        (project / ".claude" / "hooks-daemon" / "untracked" / SNAPSHOT_NAME).unlink()
        assert _read(project, str(detail)) is False

    def test_the_summary_stays_readable(self, detail: Path, project: Path) -> None:
        assert _bash(project, "cat CLAUDE/reports/x-opus-security-SUMMARY.md") is True


class TestDaemonRuntimeArtefactsStayDenied:
    """Review I4 (self-install half): payload capture and the verdict and stop-event
    logs under untracked/ are known-sensitive, so they are denied in either layout."""

    @pytest.mark.parametrize(
        "rel",
        [
            "untracked/payload-capture/p.json",
            "untracked/logs/hooks/verdicts.jsonl",
            "untracked/stop-events.jsonl",
        ],
    )
    def test_denied(self, project: Path, rel: str) -> None:
        target = project / rel
        target.parent.mkdir(parents=True)
        target.write_text("{}\n")
        assert _bash(project, "cat " + rel) is False
        assert _read(project, str(target)) is False

    def test_an_ordinary_daemon_log_stays_readable(self, project: Path) -> None:
        target = project / "untracked" / "logs" / "daemon.log"
        target.parent.mkdir(parents=True)
        target.write_text("log\n")
        assert _bash(project, "tail -n 5 untracked/logs/daemon.log") is True
