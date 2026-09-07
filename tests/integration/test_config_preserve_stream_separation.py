"""A CLI's stderr must not reach a caller that parses its stdout as JSON.

Plan 00340 Phase 3. ``config_preserve.sh`` captured the daemon CLI with
``2>&1``, folding diagnostics into the payload::

    merge_output=$("$venv_python" -m ...daemon.cli config-merge ... 2>&1)

The exit code is checked first, so this never bit on a FAILING run — the
failure was reported correctly. It bites when the CLI SUCCEEDS and also writes
to stderr: a single deprecation notice or warning line prefixes the JSON,
``json.loads`` rejects it, and the upgrade reports "Failed to write merged
config" for a run that actually worked. The user is told their customisations
were lost when they were not.

The tests drive the real shell functions against a CLI stub that does exactly
that — succeeds, warns on stderr, prints valid JSON on stdout — because the
defect only exists in the combination.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PRESERVE_SH = REPO_ROOT / "scripts" / "install" / "config_preserve.sh"
BASH = shutil.which("bash") or "/bin/bash"

#: What the stub writes to stderr on an otherwise-successful run.
STDERR_NOTICE = "NOTE: config-merge is reading a legacy schema"

_DEFAULT_CONFIG: dict[str, object] = {
    "version": "3.0",
    "daemon": {"log_level": "INFO"},
    "handlers": {"pre_tool_use": {}},
}

_MERGED_CONFIG: dict[str, object] = {
    "version": "3.0",
    "daemon": {"log_level": "DEBUG"},
    "handlers": {"pre_tool_use": {}},
}

# A stand-in for the venv Python. A daemon-CLI invocation succeeds while
# writing to BOTH streams; anything else (the `-c` blocks the shell pipes JSON
# into) is delegated to the real interpreter, so the code under test is
# exercised rather than mocked.
_STUB_TEMPLATE = """#!/usr/bin/env python3
import json
import subprocess
import sys

REAL_PYTHON = {real_python!r}
NOTICE = {notice!r}
PAYLOAD = {payload!r}

argv = sys.argv[1:]
if "claude_code_hooks_daemon.daemon.cli" in argv:
    print(NOTICE, file=sys.stderr)
    print(PAYLOAD)
    sys.exit(0)

sys.exit(subprocess.run([REAL_PYTHON, *argv], check=False).returncode)
"""


def _write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _make_stub(tmp_path: Path, payload: object) -> Path:
    """A venv-Python stand-in that succeeds while writing to both streams."""
    stub = tmp_path / "python-stub"
    stub.write_text(
        _STUB_TEMPLATE.format(
            real_python=sys.executable,
            notice=STDERR_NOTICE,
            payload=json.dumps(payload),
        )
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return stub


def _run(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


class TestTheMergePayloadSurvivesADiagnosticOnStderr:
    """``merge_custom_config`` is the site that aborts a real upgrade."""

    def _merge(self, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
        user_path = tmp_path / "user.yaml"
        old_default_path = tmp_path / "old-default.yaml"
        new_default_path = tmp_path / "new-default.yaml"
        merged_path = tmp_path / "merged.yaml"

        _write_yaml(user_path, _DEFAULT_CONFIG)
        _write_yaml(old_default_path, _DEFAULT_CONFIG)
        _write_yaml(new_default_path, _DEFAULT_CONFIG)

        stub = _make_stub(
            tmp_path,
            {"merged_config": _MERGED_CONFIG, "conflicts": [], "is_clean": True},
        )
        result = _run(f"""
            set -uo pipefail
            source "{CONFIG_PRESERVE_SH}"
            merge_custom_config "{stub}" "{user_path}" \\
                "{old_default_path}" "{new_default_path}" "{merged_path}"
            """)
        return result, merged_path

    def test_the_merged_config_is_written(self, tmp_path: Path) -> None:
        """The reported failure: a working merge announced as a failed one."""
        result, merged_path = self._merge(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Failed to write merged config" not in result.stderr
        assert merged_path.exists(), "merged config was never written"
        assert yaml.safe_load(merged_path.read_text()) == _MERGED_CONFIG

    def test_stdout_is_json_and_nothing_else(self, tmp_path: Path) -> None:
        """The function's stdout IS the payload — its caller parses it again.

        ``preserve_config_for_upgrade`` feeds this straight to
        ``report_incompatibilities``, so a diagnostic line riding along breaks
        the conflict report as well as the write.
        """
        result, _ = self._merge(tmp_path)

        parsed = json.loads(result.stdout)
        assert parsed["merged_config"] == _MERGED_CONFIG

    def test_the_diagnostic_is_still_shown_to_the_user(self, tmp_path: Path) -> None:
        """Separating the streams must not mean discarding one of them.

        Keeping the payload clean by throwing the CLI's own warnings away
        would trade a loud wrong answer for a silent one.
        """
        result, _ = self._merge(tmp_path)

        assert STDERR_NOTICE in result.stderr, (
            "the CLI's stderr vanished — it must reach the user, just not the " "JSON payload"
        )


class TestTheDiffPayloadSurvivesADiagnosticOnStderr:
    """``extract_custom_config`` has the same contract and had the same flaw."""

    def _extract(self, tmp_path: Path) -> subprocess.CompletedProcess[str]:
        user_path = tmp_path / "user.yaml"
        default_path = tmp_path / "default.yaml"
        _write_yaml(user_path, _DEFAULT_CONFIG)
        _write_yaml(default_path, _DEFAULT_CONFIG)

        stub = _make_stub(tmp_path, {"custom_daemon_settings": {"log_level": "DEBUG"}})
        return _run(f"""
            set -uo pipefail
            source "{CONFIG_PRESERVE_SH}"
            extract_custom_config "{stub}" "{user_path}" "{default_path}"
            """)

    def test_stdout_is_json_and_nothing_else(self, tmp_path: Path) -> None:
        result = self._extract(tmp_path)

        assert result.returncode == 0, result.stdout + result.stderr
        parsed = json.loads(result.stdout)
        assert parsed["custom_daemon_settings"] == {"log_level": "DEBUG"}

    def test_the_diagnostic_is_still_shown_to_the_user(self, tmp_path: Path) -> None:
        result = self._extract(tmp_path)

        assert STDERR_NOTICE in result.stderr


class TestAFailingCliStillReportsWhyItFailed:
    """The regression guard on the other side: stderr is the error detail.

    ``2>&1`` was there for a reason — the failure messages read
    ``Config merge failed: <stderr>``. Splitting the streams must keep that
    message informative, or the fix trades one silent failure for another.
    """

    _FAILING_STUB = """#!/usr/bin/env python3
import sys

print("boom: the config is not valid YAML", file=sys.stderr)
sys.exit(3)
"""

    def _failing_stub(self, tmp_path: Path) -> Path:
        stub = tmp_path / "python-failing-stub"
        stub.write_text(self._FAILING_STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        return stub

    def test_the_error_message_carries_the_clis_stderr(self, tmp_path: Path) -> None:
        user_path = tmp_path / "user.yaml"
        default_path = tmp_path / "default.yaml"
        _write_yaml(user_path, _DEFAULT_CONFIG)
        _write_yaml(default_path, _DEFAULT_CONFIG)
        stub = self._failing_stub(tmp_path)

        result = _run(f"""
            set -uo pipefail
            source "{CONFIG_PRESERVE_SH}"
            extract_custom_config "{stub}" "{user_path}" "{default_path}"
            """)

        assert result.returncode == 1
        assert "boom: the config is not valid YAML" in result.stderr, (
            "the failure was reported without the reason — splitting the "
            f"streams dropped the diagnostic: {result.stderr}"
        )


class TestNoCapturedCliFoldsStderrIntoItsPayload:
    """Static guard over the whole file, not a patch for the known sites.

    A behavioural test can only cover the invocations a test happens to
    exercise; the rule is general, and the next `2>&1` added to a captured
    daemon-CLI call would be the same defect wearing a different function name.
    """

    def test_config_preserve_never_captures_a_cli_with_2_to_1(self) -> None:
        offenders: list[str] = []
        for number, line in enumerate(CONFIG_PRESERVE_SH.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "2>&1" in stripped and "$(" in stripped:
                offenders.append(f"{CONFIG_PRESERVE_SH.name}:{number}: {stripped}")

        assert not offenders, (
            "A command substitution that folds stderr into stdout produces a "
            "payload no JSON parser can read the moment the command warns. "
            "Capture the two streams separately:\n  " + "\n  ".join(offenders)
        )


class TestTheStubItselfBehavesAsTheTestsAssume:
    """A stub that did not write to both streams would make every test above
    pass against the unfixed code, so its own behaviour is pinned."""

    def test_it_succeeds_while_writing_to_both_streams(self, tmp_path: Path) -> None:
        stub = _make_stub(tmp_path, {"is_clean": True})

        result = subprocess.run(
            [str(stub), "-m", "claude_code_hooks_daemon.daemon.cli", "config-merge"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ},
        )

        assert result.returncode == 0
        assert STDERR_NOTICE in result.stderr
        assert json.loads(result.stdout) == {"is_clean": True}
