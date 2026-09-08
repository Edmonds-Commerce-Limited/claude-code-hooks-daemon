r"""``create_venv_at_path`` must sync from the lockfile, not re-resolve it.

Plan 00346 Task 2.3. The plan's Phase 1 removed the same defect one function
over: ``install_deps`` provisioned the QA venv with ``pip install -e ".[dev]"``,
which never reads ``uv.lock`` at all. ``create_venv_at_path`` (the install and
upgrade path) does better — it runs ``uv sync``, which does consult the lock —
but without ``--frozen``.

That flag is the whole difference between installing what the lock says and
letting uv rewrite it. A bare ``uv sync`` treats ``uv.lock`` as a cache: when
it disagrees with ``pyproject.toml``, uv re-locks against PyPI and installs the
new resolution. So a checkout whose two files have drifted apart silently gets
a toolchain nobody recorded, and a rewritten lockfile to match — the failure
mode ``.pre-commit-config.yaml``'s header calls "two years of silent rot".

Adding ``--frozen`` does not make a working install fail. uv only re-locks when
``pyproject.toml`` and ``uv.lock`` disagree, and this repository gates exactly
that with ``uv lock --check`` in ``run_dependency_check.sh``. In other words the
flag converts a state CI already treats as a defect from a silent wrong install
into a legible error.

Stubs ``uv`` and ``stat`` on PATH, mirroring
``test_venv_sh_container_proactive_copy.py`` — the point is which arguments the
function constructs, so a real uv would only add network and nondeterminism.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
VENV_SH: Final[Path] = REPO_ROOT / "scripts" / "install" / "venv.sh"
BASH: Final[str] = shutil.which("bash") or "/bin/bash"

_TIMEOUT_SECONDS: Final[int] = 30


def _write_stub_dir(tmp_path: Path, uv_log: Path) -> Path:
    """PATH dir with a `uv` that records its full argv, and a `stat` for the fs probe."""
    stub_dir = tmp_path / "stubs"
    stub_dir.mkdir()

    uv_stub = stub_dir / "uv"
    uv_stub.write_text(textwrap.dedent(f"""\
        #!/bin/bash
        printf '%s\\n' "$*" >> "{uv_log}"
        if [ -n "${{UV_PROJECT_ENVIRONMENT:-}}" ]; then
            mkdir -p "$UV_PROJECT_ENVIRONMENT/bin"
            : > "$UV_PROJECT_ENVIRONMENT/bin/python"
            chmod +x "$UV_PROJECT_ENVIRONMENT/bin/python"
        fi
        exit 0
        """))
    uv_stub.chmod(0o755)

    stat_stub = stub_dir / "stat"
    stat_stub.write_text("#!/bin/bash\nprintf '%s\\n' 'ext2/ext3'\nexit 0\n")
    stat_stub.chmod(0o755)

    return stub_dir


def _run_create_venv(tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    (daemon_dir / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.0.0"\n')
    venv_path = daemon_dir / "untracked" / "venv-test"

    uv_log = tmp_path / "uv_calls.log"
    uv_log.write_text("")
    stub_dir = _write_stub_dir(tmp_path, uv_log)

    # PATH is exported AFTER sourcing, and that order is load-bearing. Sourcing
    # venv.sh PREPENDS the daemon's own tool directory (~/.local/bin) to PATH,
    # which shadows the stub — so the pre-source ordering silently runs the REAL
    # uv against this throwaway project and reports success with an empty log.
    harness = textwrap.dedent(f"""\
        set -euo pipefail
        . "{VENV_SH}"
        export PATH="{stub_dir}:$PATH"
        create_venv_at_path "{daemon_dir}" "{venv_path}"
        """)

    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env.pop("UV_LINK_MODE", None)

    result = subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    return result, [ln for ln in uv_log.read_text().splitlines() if ln.strip()]


def _create_venv_at_path_body() -> str:
    match = re.search(r"create_venv_at_path\(\)\s*\{.*?\n\}", VENV_SH.read_text(), re.DOTALL)
    assert match is not None, "create_venv_at_path() not found in venv.sh"
    return match.group(0)


class TestTheFixtureIsNotVacuous:
    def test_the_stub_uv_is_actually_invoked(self, tmp_path: Path) -> None:
        """Every assertion below reads the stub's log.

        If the function never reached the stub, an empty log would make
        "``--frozen`` is absent" and "``--frozen`` is present" equally
        unfalsifiable, so this pins that the call happened at all.
        """
        result, log = _run_create_venv(tmp_path)

        assert result.returncode == 0, (
            f"create_venv_at_path failed outright: stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert log, "the stub uv was never called, so the argv assertions test nothing"


class TestTheSyncIsFrozen:
    def test_the_invocation_passes_frozen(self, tmp_path: Path) -> None:
        """Without it, a pyproject/lock disagreement re-resolves against PyPI."""
        _result, log = _run_create_venv(tmp_path)

        assert any("--frozen" in line for line in log), (
            "create_venv_at_path ran `uv sync` without --frozen, so a checkout "
            "whose pyproject.toml and uv.lock disagree gets its lockfile "
            f"rewritten and re-resolved against PyPI: {log!r}"
        )

    def test_it_is_still_a_sync(self, tmp_path: Path) -> None:
        """Guards against satisfying the flag assertion by changing the verb.

        ``uv lock --frozen`` would contain both tokens and install nothing.
        """
        _result, log = _run_create_venv(tmp_path)

        assert any("sync" in line for line in log), f"no `uv sync` invocation recorded: {log!r}"


class TestEverySyncBranchIsCovered:
    def test_all_uv_sync_call_sites_are_frozen(self) -> None:
        """The stub exercises ONE of three branches, and that is the gap.

        ``create_venv_at_path`` syncs from three places — the hardlink branch,
        the proactive copy branch, and the hardlink-failure retry. A behavioural
        test picks whichever the environment selects, so a missed ``--frozen``
        in either of the other two would ship green. This reads the source and
        requires all of them.
        """
        body = _create_venv_at_path_body()

        sync_lines = [
            line
            for line in body.splitlines()
            if re.search(r"\buv\s+sync\b", line) and not line.strip().startswith("#")
        ]
        assert sync_lines, "no `uv sync` call sites found — has the function been rewritten?"

        unfrozen = [line.strip() for line in sync_lines if "--frozen" not in line]
        assert not unfrozen, (
            "these `uv sync` call sites in create_venv_at_path do not pass "
            f"--frozen, so they may re-resolve against PyPI: {unfrozen!r}"
        )
