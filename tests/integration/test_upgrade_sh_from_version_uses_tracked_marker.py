"""`upgrade.sh` derives FROM_VERSION from the tracked marker (Plan 00386 T2.3).

Field report (GitHub issue #38): a leftover v3.15.1 clone sat under the
gitignored `.claude/hooks-daemon/` while the project's TRACKED assets had been
deployed from v3.60.0. `upgrade` reported `from_version=v3.15.1` — the CLONE's
version — so `check-truth-changes --from 3.15.1` emitted 73 entries of
already-reconciled history and `check-config-migrations` a wall of manifest
text. The true range was v3.60.0 -> v3.63.0: five truth-changes and one stale
config key. The reporter only caught it by reading `git log` for the last
upgrade commit.

FROM_VERSION answers "what does the PROJECT still owe?", and the project's docs
and config were last reconciled by whatever DEPLOYED them — the marker — not by
whatever code happens to be sitting in a disposable clone.

The marker was already read, but only on the branch where `upgrade.sh` had
itself just cloned the daemon dir. The reported case has a clone present, so it
took the other branch every time.

**The comparison is one-directional on purpose**, and the second class below
pins that: preferring the marker when it is NEWER can only shrink a range a
stale clone inflated. A clone AHEAD of the marker means the MARKER is the stale
half — an upgrade that never regenerated the docs — and preferring it there
would re-report work already done, which is this same defect mirrored.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 — runs the trusted system `bash`
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.utils.deployed_version import version_marker_in

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_UPGRADE_SH: Final[Path] = _REPO_ROOT / "scripts" / "upgrade.sh"
_INIT_SH: Final[Path] = _REPO_ROOT / ".claude" / "init.sh"
_BASH: Final[str] = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS: Final[int] = 60

#: Start of the FROM_VERSION derivation, and the first line past it. The block
#: is extracted from the REAL script rather than restated here — a copy would
#: keep passing after the script changed, which is the failure this guards.
_BLOCK_START: Final[str] = 'FROM_VERSION=""'
_BLOCK_END: Final[str] = "# Layer 2 reads this for its"


def _from_version_block() -> str:
    """The real FROM_VERSION derivation, lifted verbatim out of `upgrade.sh`."""
    source = _UPGRADE_SH.read_text(encoding="utf-8")
    start = source.index(_BLOCK_START)
    end = source.index(_BLOCK_END, start)
    return source[start:end]


def _version_lt_function() -> str:
    """`_version_lt`'s real definition, which the block above depends on."""
    source = _UPGRADE_SH.read_text(encoding="utf-8")
    start = source.index("_version_lt() {")
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


def _marker_line(version: str) -> str:
    """The exact header `docs_generator._render_header()` emits."""
    return (
        f"> Generated on 2026-09-11 (v{version}) by `generate-docs`. "
        f"Regenerate: `.claude/hooks-daemon/bin/hooks-daemon generate-docs`"
    )


def _run_derivation(
    tmp_path: Path,
    *,
    clone_version: str | None,
    tracked_version: str | None,
    cloned_here: bool = False,
) -> str:
    """Build a client-shaped tree and run the script's own derivation over it."""
    project = tmp_path / "project"
    daemon_dir = project / ".claude" / "hooks-daemon"
    daemon_dir.mkdir(parents=True)

    if tracked_version is not None:
        (project / ".claude" / "HOOKS-DAEMON.md").write_text(
            f"# Hooks Daemon - Active Configuration\n\n{_marker_line(tracked_version)}\n",
            encoding="utf-8",
        )
    if clone_version is not None:
        (daemon_dir / "pyproject.toml").write_text(
            f'[project]\nname = "x"\nversion = "{clone_version}"\n', encoding="utf-8"
        )

    script = "\n".join(
        [
            "set -uo pipefail",
            '_ok()   { echo "OK $1"; }',
            '_warn() { echo "WARN $1"; }',
            _version_lt_function(),
            f'PROJECT_ROOT="{project}"',
            f'DAEMON_DIR="{daemon_dir}"',
            f'_DAEMON_DIR_CLONED_HERE="{"true" if cloned_here else "false"}"',
            _from_version_block(),
            'echo "FROM_VERSION=$FROM_VERSION"',
        ]
    )
    result = subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        [_BASH, "-c", script],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _from_version(output: str) -> str:
    match = re.search(r"^FROM_VERSION=(.*)$", output, re.MULTILINE)
    assert match is not None, output
    return match.group(1).strip()


class TestTheReportedCase:
    """A leftover clone beside newer tracked assets — issue #38 verbatim."""

    def test_the_tracked_version_wins_over_a_stale_clone(self, tmp_path: Path) -> None:
        output = _run_derivation(tmp_path, clone_version="3.15.1", tracked_version="3.60.0")
        assert _from_version(output) == "v3.60.0", (
            "FROM_VERSION still comes from the clone, so check-truth-changes "
            "would replay history the project has already reconciled"
        )

    def test_the_substitution_is_announced_not_silent(self, tmp_path: Path) -> None:
        """The reporter had to read `git log` to discover the range was wrong.
        A silent correction would leave the next person doing the same."""
        output = _run_derivation(tmp_path, clone_version="3.15.1", tracked_version="3.60.0")
        assert "WARN" in output
        assert "3.15.1" in output and "3.60.0" in output


class TestTheGuardIsOneDirectional:
    def test_a_clone_ahead_of_the_marker_keeps_the_clone(self, tmp_path: Path) -> None:
        """The marker is the stale half here — an upgrade that never regenerated
        the docs. Preferring it would re-report work already done."""
        output = _run_derivation(tmp_path, clone_version="3.63.0", tracked_version="3.60.0")
        assert _from_version(output) == "v3.63.0"

    def test_equal_versions_change_nothing(self, tmp_path: Path) -> None:
        output = _run_derivation(tmp_path, clone_version="3.60.0", tracked_version="3.60.0")
        assert _from_version(output) == "v3.60.0"
        assert "WARN" not in output, "the healthy case must stay quiet"


class TestFallbacks:
    def test_no_marker_falls_back_to_the_clone(self, tmp_path: Path) -> None:
        output = _run_derivation(tmp_path, clone_version="3.15.1", tracked_version=None)
        assert _from_version(output) == "v3.15.1"

    def test_a_freshly_cloned_daemon_dir_still_uses_the_marker(self, tmp_path: Path) -> None:
        """The pre-existing behaviour, which this change must not regress: with
        no prior clone, its pyproject.toml is the new HEAD and says nothing
        about the FROM side."""
        output = _run_derivation(
            tmp_path, clone_version="3.63.0", tracked_version="3.60.0", cloned_here=True
        )
        assert _from_version(output) == "v3.60.0"

    def test_neither_source_leaves_it_empty_rather_than_guessing(self, tmp_path: Path) -> None:
        output = _run_derivation(tmp_path, clone_version=None, tracked_version=None)
        assert _from_version(output) == ""


@pytest.mark.parametrize("version", ["3.60.0", "3.15.1", "10.0.1", "3.7.12"])
class TestEveryMarkerParserAgrees:
    """Three extractors read this one header line and cannot be shared.

    `utils/deployed_version.py` needs a working Python import; `init.sh` runs
    when the clone is too broken to provide one; `upgrade.sh` is fetched
    standalone and exec'd from a temp file, so it can source nothing. Each copy
    is structurally required — so the contract between them is asserted here
    rather than assumed, and none of the three moves without this test noticing.
    """

    def _shell_extract(self, script_body: str, line: str, tmp_path: Path) -> str:
        doc = tmp_path / "HOOKS-DAEMON.md"
        doc.write_text(f"# Header\n\n{line}\n", encoding="utf-8")
        result = subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
            [_BASH, "-c", script_body.replace("@DOC@", str(doc))],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_python_init_sh_and_upgrade_sh_return_the_same_version(
        self, version: str, tmp_path: Path
    ) -> None:
        line = _marker_line(version)

        from_python = version_marker_in(line)

        # upgrade.sh's awk, lifted verbatim from the real script.
        awk_line = next(
            raw.strip()
            for raw in _UPGRADE_SH.read_text(encoding="utf-8").splitlines()
            if "_TRACKED_VERSION=\"$(awk 'match($0" in raw
        )
        from_upgrade = self._shell_extract(
            awk_line.replace('"$_DOCS_STAMP_FILE"', '"@DOC@"') + '\necho "$_TRACKED_VERSION"',
            line,
            tmp_path,
        ).lstrip("v")

        # init.sh's grep, via its real function.
        init_body = _INIT_SH.read_text(encoding="utf-8")
        start = init_body.index("_tracked_deployed_version() {")
        end = init_body.index("\n}\n", start) + len("\n}\n")
        from_init = self._shell_extract(
            f'PROJECT_PATH="{tmp_path}"\n'
            + init_body[start:end].replace('"$PROJECT_PATH/.claude/HOOKS-DAEMON.md"', '"@DOC@"')
            + "\n_tracked_deployed_version",
            line,
            tmp_path,
        )

        assert from_python == version
        assert from_upgrade == version, "upgrade.sh's awk disagrees with the canonical parser"
        assert from_init == version, "init.sh's grep disagrees with the canonical parser"
