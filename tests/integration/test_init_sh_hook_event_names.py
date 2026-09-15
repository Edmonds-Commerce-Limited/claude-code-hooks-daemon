"""`init.sh` must never emit a `hookEventName` Claude Code rejects.

`emit_hook_error()` takes an event name as `$1` and embeds it verbatim:

    {"hookSpecificOutput": {"hookEventName": $event, "additionalContext": ...}}

Claude Code validates that field against a closed enum. A value outside it does
not degrade the response — it invalidates the whole document, so Claude Code
discards it and shows the human a schema error instead. The remedy prose
`emit_hook_error` exists to deliver is thrown away with the envelope it
travelled in.

Three call sites shipped the literal `Unknown`, and the function's own default
was `${1:-Unknown}`. The function is documented "CRITICAL: This ensures the
agent sees errors and can take action"; on those paths it guaranteed the
reverse. A collaborator's fresh clone hit it and got a raw JSON blob naming no
cause, plus a `SessionStart:startup hook error` banner.

Those three call sites are the guards that run at SOURCE time — before the
wrapper that sourced `init.sh` reaches its own body — so they genuinely do not
know which event is in flight. `Unknown` was an honest admission encoded in a
field with no room for one. The fix is to say it in a field that has room:
`systemMessage` is one of the five UNIVERSAL output fields defined on every
event (`core/response_schemas.py::_UNIVERSAL_OUTPUT_PROPERTIES`), so it needs
no event name and cannot name the wrong one.

The invariant is therefore behavioural, not lexical: **whatever `init.sh`
emits must be a document Claude Code will accept, and the guidance must survive
inside it.** Pinning only the spelling of the arguments would miss a future
path that reaches an invalid name some other way.
"""

from __future__ import annotations

import json
import re
import subprocess  # nosec B404 — runs the trusted system `git` and `bash`
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.constants.events import EventType

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

#: The installable source. `.claude/init.sh` is a tracked SYMLINK to it (git
#: mode 120000), so there is one file, not two — but the symlink is the reason,
#: and `TestTheDeployedPathIsNotAnIndependentCopy` below pins it rather than
#: leaving the single-file assumption implicit.
_INIT_SH: Final[Path] = _REPO_ROOT / "init.sh"

#: Every path a forwarder can reach `init.sh` through. Both are asserted so
#: that de-linking them (a real copy, a Windows checkout without symlink
#: support) is a named failure rather than a silently half-applied fix.
_INIT_SH_COPIES: Final[tuple[Path, ...]] = (
    _INIT_SH,
    _REPO_ROOT / ".claude" / "init.sh",
)

#: The deployed forwarders. `.claude/hooks/*` is the CANONICAL source for these
#: (`install/client_owned_assets.py` deploys them verbatim), so a bad event name
#: here reaches every client install.
_HOOKS_DIR: Final[Path] = _REPO_ROOT / ".claude" / "hooks"

_VALID_EVENT_NAMES: Final[frozenset[str]] = frozenset(event.value for event in EventType)

#: The documented marker for "the event is not knowable at this point". Empty
#: rather than a word, so it cannot be mistaken for an event name and cannot
#: accidentally validate against the enum.
_UNKNOWN_SENTINEL: Final[str] = ""

#: A call: `emit_hook_error "SessionStart" "code" \` — first argument's literal
#: text, including the empty sentinel.
_CALL_WITH_LITERAL: Final[re.Pattern[str]] = re.compile(
    r'^\s*emit_hook_error\s+"([^"$]*)"',
    re.MULTILINE,
)

#: The function's own fallback: `local event_name="${1:-}"`.
_DEFAULT_EVENT: Final[re.Pattern[str]] = re.compile(
    r'local\s+event_name="\$\{1:-([^}]*)\}"',
)

_HOOKS_DAEMON_REMOTE: Final[str] = (
    "git@github.com:Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"
)
_TIMEOUT_SECONDS: Final[int] = 30

#: A phrase from the guidance text, used to prove it SURVIVED the encoding
#: rather than merely that some JSON was produced.
#:
#: Deliberately NOT the raw `hooks_daemon_repo_detected` error code. That token
#: was the marker while the guard fell through to the generic message, which
#: pasted the code in verbatim; the dedicated branch explains the situation in
#: prose instead and keeps the code on stderr where a debugger can still find
#: it. Asserting on the token would therefore pin the very behaviour that was
#: wrong — an error code shown to a human who has no way to look it up.
_DIAGNOSIS_MARKER: Final[str] = "hooks-daemon repository"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=True,
    )


def _throwaway_repo(tmp_path: Path) -> Path:
    """A git repo that LOOKS like the hooks-daemon repo, carrying a COPY.

    A copy, deliberately: `init.sh` derives `PROJECT_PATH` from `BASH_SOURCE`,
    so sourcing the real file would resolve to the real repository — which is
    self-installed and would not trip the guard at all.
    """
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "init.sh").write_text(
        _read(_REPO_ROOT / ".claude" / "init.sh"), encoding="utf-8"
    )
    _git(project, "init", "-q")
    _git(project, "remote", "add", "origin", _HOOKS_DAEMON_REMOTE)
    return project


def _source(project: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 — fixed argv, no shell, trusted input
        ["bash", "-c", f'source "{project / ".claude" / "init.sh"}"'],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(project)},
        check=False,
    )


class TestWhatTheGuardActuallyEmits:
    """The behavioural half — the only half a human's screen agrees with."""

    def test_the_emitted_document_names_no_invalid_event(self, tmp_path: Path) -> None:
        """The reproduction: a fresh clone's SessionStart, end to end.

        This is the assertion that fails on the shipped code with
        `hookEventName: "Unknown"`, exactly as reported.
        """
        payload = json.loads(_source(_throwaway_repo(tmp_path)).stdout)

        emitted = payload.get("hookSpecificOutput", {}).get("hookEventName")
        assert emitted is None or emitted in _VALID_EVENT_NAMES, (
            f"init.sh emitted hookEventName={emitted!r}, which Claude Code's "
            "enum rejects — so it discards the ENTIRE response and the human "
            "sees a schema error instead of the remedy."
        )

    def test_the_guidance_survives_into_a_field_that_is_always_valid(self, tmp_path: Path) -> None:
        """Validity is not enough: the message has to still be in there.

        Separated from the check above because the cheapest way to satisfy that
        one is to stop emitting anything — which would swap a loud failure for
        a silent one and still leave the reader with no cause named.
        """
        payload = json.loads(_source(_throwaway_repo(tmp_path)).stdout)

        assert _DIAGNOSIS_MARKER in json.dumps(payload), (
            "the emitted document no longer carries the diagnosis. A response "
            "Claude Code accepts but that explains nothing is not a fix."
        )

    def test_the_refusal_still_fails_open(self, tmp_path: Path) -> None:
        """A hook must never block Claude Code, whatever else changes here."""
        assert _source(_throwaway_repo(tmp_path)).returncode == 0


class TestTheRemedyIsOneThatCanActuallySucceed:
    """A valid envelope carrying wrong advice is still a failed diagnosis.

    The standard error text says "restart the daemon", which is right for the
    case it was written for and useless here: a fresh clone has no virtualenv,
    and restarting cannot build one. A reader who follows advice that cannot
    work concludes the repository is broken rather than unconfigured — which is
    exactly what the VERSION_MISMATCH branch was added to prevent, for the same
    reason.
    """

    def test_it_names_the_bootstrap_script(self, tmp_path: Path) -> None:
        message = json.loads(_source(_throwaway_repo(tmp_path)).stdout)["systemMessage"]

        assert "scripts/bootstrap-self-install.sh" in message, (
            "the fresh-clone message no longer names the command that fixes "
            f"it. Message was:\n{message}"
        )

    def test_the_named_script_exists_and_is_executable(self) -> None:
        """A remedy naming a script that is not there is worse than none.

        Pinned because the message is a string: renaming or moving the script
        cannot break it, so nothing else would notice.
        """
        script = _REPO_ROOT / "scripts" / "bootstrap-self-install.sh"

        assert script.is_file(), f"{script} does not exist, but init.sh tells readers to run it."
        assert script.stat().st_mode & 0o111, f"{script} is not executable."

    def test_it_warns_off_the_client_installer_rather_than_recommending_it(
        self, tmp_path: Path
    ) -> None:
        """`install.py --self-install` is DESTRUCTIVE in this repository.

        `create_daemon_config` and `create_settings_json` do not skip an
        existing file — they rename it to `.bak` and write a default template
        over it, and `--force` only decides whether the backup is taken. On a CI
        runner this replaced the repository's own 1188-line hooks-daemon.yaml
        with a template invalid against the current schema, after which the
        daemon refused to start. The message used to RECOMMEND it.
        """
        message = json.loads(_source(_throwaway_repo(tmp_path)).stdout)["systemMessage"]

        if "install.py" not in message:
            return
        assert "Do NOT run install.py" in message, (
            "the message mentions install.py without warning that it "
            "overwrites this repository's tracked config. Either drop the "
            f"mention or keep the warning. Message was:\n{message}"
        )

    def test_it_says_outright_that_a_restart_cannot_help(self, tmp_path: Path) -> None:
        """Pinned separately: naming the right fix does not withdraw the wrong one.

        Both sentences were present at once in the shipped text — the remedy
        was buried mid-paragraph under a "TO FIX: restart" heading, so a
        skimming reader acted on the restart and never reached the installer.
        """
        message = json.loads(_source(_throwaway_repo(tmp_path)).stdout)["systemMessage"]

        assert "RESTART CANNOT FIX THIS" in message, (
            "the message no longer rules out the remedy that cannot work, so a "
            f"reader can still act on it. Message was:\n{message}"
        )

    def test_it_never_recommends_an_interpreter_that_is_not_installed(self, tmp_path: Path) -> None:
        """`python` is absent by default on modern Fedora, Debian 12+ and Ubuntu.

        `install.py`'s own shebang is `python3`. Instructing a reader to type
        `python` earns them `command not found`, which reads as a broken
        repository rather than a wrong instruction.
        """
        message = json.loads(_source(_throwaway_repo(tmp_path)).stdout)["systemMessage"]

        assert not re.search(r"(?<!3)\bpython install\.py", message), (
            "the message tells the reader to run `python install.py`, but bare "
            "`python` is not installed on the platforms this project targets. "
            f"Message was:\n{message}"
        )


class TestNoCallSiteCanNameAnEventClaudeCodeWouldReject:
    """The static half: what the sources are CAPABLE of emitting."""

    def test_every_init_sh_call_site_is_valid_or_the_explicit_sentinel(self) -> None:
        offenders: list[str] = []
        for init_sh in _INIT_SH_COPIES:
            body = _read(init_sh)
            for match in _CALL_WITH_LITERAL.finditer(body):
                name = match.group(1)
                if name == _UNKNOWN_SENTINEL or name in _VALID_EVENT_NAMES:
                    continue
                line = body.count("\n", 0, match.start()) + 1
                offenders.append(f"{init_sh.relative_to(_REPO_ROOT)}:{line} -> {name!r}")

        assert not offenders, (
            "emit_hook_error call sites name events Claude Code does not "
            "accept, so its ENTIRE response is discarded and the agent sees "
            "nothing. Use a real event name, or the empty sentinel if the "
            "event genuinely is not knowable there:\n  " + "\n  ".join(offenders)
        )

    def test_every_forwarder_call_site_names_a_real_event(self) -> None:
        """The forwarders DO know their event, so the sentinel is not for them.

        `.claude/hooks/*` is the canonical source deployed verbatim into every
        client install — a wrong name here ships outward.
        """
        offenders: list[str] = []
        for wrapper in sorted(_HOOKS_DIR.iterdir()):
            if not wrapper.is_file():
                continue
            body = _read(wrapper)
            for match in _CALL_WITH_LITERAL.finditer(body):
                if match.group(1) in _VALID_EVENT_NAMES:
                    continue
                line = body.count("\n", 0, match.start()) + 1
                offenders.append(f"{wrapper.relative_to(_REPO_ROOT)}:{line} -> {match.group(1)!r}")

        assert not offenders, "hook forwarders name events Claude Code does not accept:\n  " + (
            "\n  ".join(offenders)
        )

    def test_the_fallback_event_name_is_valid_or_the_sentinel(self) -> None:
        """`${1:-X}` must not smuggle in the value the sweeps above forbid.

        Pinned separately because it is reachable without any call site being
        wrong: a caller that omits the argument lands here, and a default
        nobody reads is exactly where an invalid value survives.
        """
        for init_sh in _INIT_SH_COPIES:
            body = _read(init_sh)
            match = _DEFAULT_EVENT.search(body)
            assert match is not None, (
                f"{init_sh.relative_to(_REPO_ROOT)}: could not find "
                'emit_hook_error\'s `local event_name="${1:-...}"` default. If '
                "it was restructured, restructure this guard with it rather "
                "than deleting it — an unconstrained default is how `Unknown` "
                "shipped."
            )
            default = match.group(1)
            assert default == _UNKNOWN_SENTINEL or default in _VALID_EVENT_NAMES, (
                f"{init_sh.relative_to(_REPO_ROOT)}: emit_hook_error defaults "
                f"its event name to {default!r}, which Claude Code rejects."
            )


class TestTheGuardsAreNotVacuous:
    """A pattern that matches nothing passes every sweep above."""

    def test_init_sh_call_sites_are_actually_found(self) -> None:
        for init_sh in _INIT_SH_COPIES:
            assert _CALL_WITH_LITERAL.findall(_read(init_sh)), (
                f"{init_sh.relative_to(_REPO_ROOT)}: the call-site pattern "
                "matched nothing, so the checks above assert nothing."
            )

    def test_forwarder_call_sites_are_actually_found(self) -> None:
        total = sum(
            len(_CALL_WITH_LITERAL.findall(_read(wrapper)))
            for wrapper in _HOOKS_DIR.iterdir()
            if wrapper.is_file()
        )
        assert total, (
            "no emit_hook_error call site was found in any forwarder, so the "
            "forwarder sweep asserts nothing."
        )

    def test_the_two_tracked_init_paths_agree(self) -> None:
        """Whether linked or copied, both paths must say the same thing.

        Tautological while the symlink holds — deliberately so. It stops being
        tautological the moment someone replaces the link with a real file, and
        that is exactly when a fix applied to one path and not the other would
        otherwise ship half-done.
        """
        per_copy = {
            init_sh.relative_to(_REPO_ROOT).as_posix(): _CALL_WITH_LITERAL.findall(_read(init_sh))
            for init_sh in _INIT_SH_COPIES
        }
        assert len({tuple(names) for names in per_copy.values()}) == 1, (
            "the two tracked init.sh paths name different events at their "
            f"emit_hook_error call sites: {per_copy}"
        )


class TestTheDeployedPathIsNotAnIndependentCopy:
    """`.claude/init.sh` is a symlink, and that is load-bearing.

    The forwarders source `$SCRIPT_DIR/../init.sh`, i.e. the `.claude/` path.
    If that became a real file, every future `init.sh` fix would have to be
    applied twice, and the failure mode of forgetting is silent: the repository
    would keep running the stale deployed half while its tests read the fixed
    source.
    """

    def test_the_claude_path_is_a_symlink_to_the_source(self) -> None:
        deployed = _REPO_ROOT / ".claude" / "init.sh"

        assert deployed.is_symlink(), (
            f"{deployed.relative_to(_REPO_ROOT)} is no longer a symlink. If "
            "that was deliberate, the two paths are now independently "
            "maintained and every init.sh change must be applied to both."
        )
        assert deployed.resolve() == _INIT_SH.resolve(), (
            f"{deployed.relative_to(_REPO_ROOT)} resolves to "
            f"{deployed.resolve()}, not the tracked source {_INIT_SH}."
        )
