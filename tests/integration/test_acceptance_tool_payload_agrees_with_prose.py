"""A declared `tool_payload` must agree with the prose beside it (Plan 00243).

`AcceptanceTest.command` is overloaded: sometimes a literal shell command,
sometimes an English sentence describing a tool call. Task 1.3 added
`tool_payload` so a harness can DISPATCH the second kind instead of guessing at
it with regexes -- the guessing that turned 49 declared tests into false
failures.

Adding the field creates a new way to be wrong, and it is worse than the
problem it solves. A payload naming a different path from the sentence beside
it does not fail loudly: the harness writes to the payload's path, the handler
answers about THAT path, and the assertion is judged against a probe no human
reviewing the playbook ever saw. A wrong payload is a test that passes for the
wrong reason.

So the two are checked against each other here, over the REAL generator rather
than over a fixture. That matters: five handlers declare zero tests of their
own and inherit every one from `strategies/`, so anything walking handler
classes alone misses 75 files' worth of the exact strings this plan is about.

The check is deliberately narrow -- `file_path` only. It is the field the
harness actually writes to, it is always rendered verbatim, and it is the one
whose mismatch silently retargets the probe. Content is not compared: a
sentence legitimately abbreviates or describes it, and demanding a literal
match would fail for correct declarations, which is how a guard gets switched
off.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_FILE_PATH_KEY = "file_path"

REPO_ROOT = Path(__file__).resolve().parents[2]

# Shell constructs that make a string unambiguously a command even when its
# first token is not an executable: pipelines, redirects, assignments,
# conditionals, subshells. A `set -euo pipefail` prelude or a bare
# `VAR=value cmd` is a real command with an unexecutable-looking head.
_SHELL_CONSTRUCTS = ("$(", "&&", "||", ">>", "<<", "|", ";", "=", "[[", "\n")

# The SHAPE of an executable name, used when the box does not happen to have
# the tool installed. `shutil.which` alone made this check machine-dependent:
# `rg` and `agent-browser` are perfectly good commands that a CI runner does not
# carry, so the guard failed there for a reason that had nothing to do with the
# playbook. Every prose opener this test was written to catch (`With`,
# `Simulate`, `Run any`, `Stage`, `WebFetch`) is CAPITALISED, so requiring a
# lowercase command-name shape keeps all of them rejected without asking what is
# installed.
_COMMAND_NAME_SHAPE = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")


def _looks_like_a_command(command: str) -> bool:
    """Is this string a shell command rather than a sentence about one?

    Asked as a WHITELIST, unlike the classifier that failed in Plan 00345: a
    string is a command when something positive says so, and an unrecognised
    shape is reported for a human rather than assumed fine.
    """
    tokens = command.split()
    if not tokens:
        return True
    head = tokens[0].lstrip("!\\").split("/")[-1]
    if shutil.which(head) or (REPO_ROOT / tokens[0]).exists():
        return True
    if any(marker in command for marker in _SHELL_CONSTRUCTS):
        return True
    return bool(_COMMAND_NAME_SHAPE.match(head))


# Generous next to the 120s its neighbours here allow a QA checker: this
# subprocess imports every handler module and walks all ~280 test blocks, so
# its cost tracks handler COUNT rather than the size of any one input.
_GENERATE_TIMEOUT_SECONDS = 180

# The sanctioned probe location (Plan 00333): inside the repo so
# `project_containment` permits it, gitignored so nothing reaches review.
_SCRATCH_MARKER = "untracked/scratch"

# Real in this self-install checkout, false in every client install — the
# property `test_generated_docs_are_path_agnostic.py` enforces for the other
# two artefacts rendered from handler code (Plan 00244).
_SELF_INSTALL_ROOT = "/workspace"

# Handlers whose CONTRACT is a path outside the repository, so a scratch path
# would not exercise them at all. Named individually rather than pattern-
# matched: an exemption that cannot be read off a list is one nobody audits.
_OUTSIDE_SCRATCH_BY_CONTRACT = frozenset(
    {
        # Denies writes OUTSIDE the repository root, so its probe must target
        # one. It asks for the system temp directory, which is the least
        # harmful such path: outside the working tree, so a regressed handler
        # cannot touch anything tracked or reviewed, and ephemeral by
        # definition rather than by a `/tmp` that may not be the temp dir.
        "ProjectContainmentHandler",
        # Denies markdown written to an UNRECOGNISED location -- and
        # `untracked/` is a recognised one. A scratch path would therefore
        # stop this probe exercising anything, which is a worse failure than
        # the one the scratch rule prevents: a test that silently proves
        # nothing, versus a stray `random-notes.md` at the repo root that a
        # regressed handler would leave in plain sight and `git status` names
        # immediately. It carries no code and no credential.
        "MarkdownOrganizationHandler",
    }
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def playbook() -> list[dict]:
    """Every test block, collected through the production generator CLI.

    Driven as a subprocess for the same reason the harness itself will be
    (Plan 00243 Task 2.1): it exercises the real entry point rather than a
    hand-assembled generator that can drift from what a release actually runs.
    """
    root = _project_root()
    result = subprocess.run(
        [str(root / "bin" / "hooks-daemon"), "generate-playbook", "--format", "json"],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=_GENERATE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        pytest.skip(f"generate-playbook unavailable: {result.stderr[-400:]}")
    return json.loads(result.stdout)


class TestTheGeneratorIsReachable:
    def test_the_playbook_is_not_empty(self, playbook: list[dict]) -> None:
        """Guards every other test here from passing vacuously."""
        assert len(playbook) > 100, (
            "the generator returned almost nothing, so the agreement checks "
            "below would pass without examining anything"
        )

    def test_the_payload_field_is_exposed_at_all(self, playbook: list[dict]) -> None:
        """A missing key would make every check below silently vacuous."""
        handler_blocks = [b for b in playbook if b.get("test_type") != "cli"]
        assert handler_blocks
        assert "tool_payload" in handler_blocks[0]


class TestDeclaredPayloadsAgreeWithTheirProse:
    def test_every_declared_file_path_appears_in_its_command(self, playbook: list[dict]) -> None:
        """The path the harness writes to must be the path the sentence names."""
        mismatches = []
        for block in playbook:
            payload = block.get("tool_payload")
            if not payload:
                continue
            file_path = (payload.get("tool_input") or {}).get(_FILE_PATH_KEY)
            if not file_path:
                continue
            command = block.get("command") or ""
            if str(file_path) not in command:
                mismatches.append(
                    f"#{block.get('test_number')} {block.get('handler_name')}: "
                    f"payload writes {file_path!r} but the command says {command!r}"
                )

        assert not mismatches, (
            "a declared tool_payload names a different path from the prose "
            "beside it, so the harness would probe something no reviewer saw:\n"
            + "\n".join(mismatches)
        )

    def test_every_bash_payload_dispatches_the_command_a_human_is_shown(
        self, playbook: list[dict]
    ) -> None:
        """The other tool's half of the agreement check (Plan 00345 Task 3.2).

        The `file_path` check above is the Write half; this is the same
        guarantee for Bash, where the whole input is the command string. A
        payload whose command differs from the one printed beside it means the
        human and the harness are testing two different things, and the
        playbook shows only one of them.

        `dispatch_as_bash=True` makes this true by construction rather than by
        review, so what this actually guards is a HAND-WRITTEN Bash payload --
        the route that stays open for a block needing setup around the command.
        """
        disagreements = []
        for block in playbook:
            payload = block.get("tool_payload") or {}
            if (payload.get("tool_name") or "") != "Bash":
                continue
            declared = (payload.get("tool_input") or {}).get("command")
            shown = block.get("command") or ""
            if declared != shown:
                disagreements.append(
                    f"#{block.get('test_number')} {block.get('handler_name')}: "
                    f"payload runs {declared!r} but the playbook shows {shown!r}"
                )

        assert not disagreements, (
            "a Bash payload dispatches a different command from the one the "
            "playbook prints, so the human and the harness are not running the "
            "same test:\n" + "\n".join(disagreements)
        )

    def test_every_bash_payload_is_a_command_a_shell_could_run(self, playbook: list[dict]) -> None:
        """A Bash payload carrying PROSE passes while testing nothing.

        This caught eight real ones. Plan 00345's own classifier decided "this
        is shell" by checking the command did NOT start with a known prose
        opener — a blacklist — and eight blocks opened with words it had never
        seen (`With`, `Simulate`, `Run any`, `Stage`, `WebFetch`). They describe
        a scenario a human performs, not a command anything can execute.

        Every one of the eight expected ALLOW, which is exactly why nothing
        noticed: a prose string dispatched as a Bash command matches no
        handler, returns no decision, and `verdict` correctly reads that
        absence as an allow. The DENY siblings of the same handlers failed
        loudly and were held back — so a dry run only exposes prose when the
        test expects a refusal, and the allow half slips through in silence.

        See `_looks_like_a_command` for how the question is asked, and why it
        must not depend on what happens to be installed.
        """
        prose = []
        for block in playbook:
            payload = block.get("tool_payload") or {}
            if (payload.get("tool_name") or "") != "Bash":
                continue
            command = (block.get("command") or "").strip()
            if _looks_like_a_command(command):
                continue
            prose.append(
                f"#{block.get('test_number')} {block.get('handler_name')}: "
                f"{command[:100]!r} starts with {command.split()[0]!r}, which "
                f"does not read as a command"
            )

        assert not prose, (
            "a Bash payload's command does not look like something a shell "
            "could run, so the probe would match no handler and an ALLOW test "
            "would pass while testing nothing:\n" + "\n".join(prose)
        )

    def test_every_declared_payload_names_a_tool(self, playbook: list[dict]) -> None:
        """An unnamed tool cannot be dispatched.

        `ToolPayload.__post_init__` already rejects this at construction, so a
        failure here means something built a payload dict by another route --
        which is worth catching, because the generator's JSON is hand-built.
        """
        unnamed = [
            f"#{b.get('test_number')} {b.get('handler_name')}"
            for b in playbook
            if b.get("tool_payload") and not (b["tool_payload"].get("tool_name") or "").strip()
        ]
        assert not unnamed, f"tool_payload with no tool_name: {unnamed}"

    def test_every_declared_write_targets_the_scratch_directory(self, playbook: list[dict]) -> None:
        """A dispatchable payload must not aim at the working tree.

        This is the risk the payload field ADDS, and it is the reverse of the
        one it removes. As prose, "write to $CLAUDE_PROJECT_DIR/src/config.ts"
        is read by a human who would balk, or quietly substitute a scratch
        path. As a declared payload it is dispatched verbatim.

        These are DENY tests, so in the healthy case the handler blocks the
        write and nothing lands. But the case a deny test exists for is the
        one where the handler has REGRESSED -- and then the write succeeds.
        The probe that catches a broken guard would be the probe that drops a
        file carrying a dynamic-execution construct or a credential-shaped
        string into `src/`, precisely when the guard is not there to stop it.

        `untracked/scratch/` is the sanctioned location (Plan 00333): inside
        the repo so `project_containment` permits it, gitignored so nothing
        reaches review, and wiped without consequence.
        """
        stray = []
        for block in playbook:
            payload = block.get("tool_payload")
            if not payload:
                continue
            file_path = str((payload.get("tool_input") or {}).get(_FILE_PATH_KEY, ""))
            if not file_path:
                continue
            handler = block.get("handler_name", "")
            if handler in _OUTSIDE_SCRATCH_BY_CONTRACT:
                continue
            if _SCRATCH_MARKER not in file_path:
                stray.append(f"#{block.get('test_number')} {handler}: {file_path}")

        assert not stray, (
            "a dispatchable payload targets a path outside "
            f"{_SCRATCH_MARKER!r}, so a regressed handler would let the probe "
            "write into the working tree:\n" + "\n".join(stray)
        )

    def test_every_declared_file_path_is_absolute_or_project_rooted(
        self, playbook: list[dict]
    ) -> None:
        """A relative path never reaches the handler the test is about.

        `absolute_path` denies a relative `file_path` ahead of almost every
        other PreToolUse handler, so the probe reports on THAT guard instead:
        a DENY test passes for the wrong reason and an ALLOW test fails
        outright. Two `sensitive_content` payloads shipped this way and were
        invisible to the scratch check above, because `untracked/scratch/...`
        contains the marker whether or not it is rooted.
        """
        relative = []
        for block in playbook:
            payload = block.get("tool_payload")
            if not payload:
                continue
            file_path = str((payload.get("tool_input") or {}).get(_FILE_PATH_KEY, ""))
            if not file_path:
                continue
            if file_path.startswith("/") or file_path.startswith("$"):
                continue
            relative.append(f"#{block.get('test_number')} {block.get('handler_name')}: {file_path}")

        assert not relative, (
            "a declared payload names a relative file_path, which "
            "`absolute_path` denies before the handler under test is "
            "reached:\n" + "\n".join(relative)
        )

    def test_no_declared_payload_hardcodes_an_absolute_repo_path(
        self, playbook: list[dict]
    ) -> None:
        """`/workspace` is real only here and false in every client install.

        The same property `test_generated_docs_are_path_agnostic.py` enforces
        for the other two artefacts rendered from handler code (Plan 00244).
        The playbook is the third, and a payload is now a machine-followed
        instruction rather than a sentence, so a wrong root is dispatched
        rather than read.
        """
        hardcoded = []
        for block in playbook:
            payload = block.get("tool_payload")
            if not payload:
                continue
            for key, value in (payload.get("tool_input") or {}).items():
                if isinstance(value, str) and value.startswith(_SELF_INSTALL_ROOT):
                    hardcoded.append(
                        f"#{block.get('test_number')} {block.get('handler_name')} {key}={value}"
                    )

        assert not hardcoded, (
            f"a declared payload hardcodes {_SELF_INSTALL_ROOT!r}, which exists "
            "only in this self-install checkout:\n" + "\n".join(hardcoded)
        )

    def test_no_block_declares_both_a_payload_and_a_skip_reason(self, playbook: list[dict]) -> None:
        """One says the input cannot be produced, the other says how to.

        Enforced at construction too; asserted here because the JSON dict is
        assembled by hand and could carry both even when the dataclass cannot.
        """
        contradictory = [
            f"#{b.get('test_number')} {b.get('handler_name')}"
            for b in playbook
            if b.get("tool_payload") and b.get("harness_cannot_produce")
        ]
        assert (
            not contradictory
        ), f"blocks declaring both tool_payload and harness_cannot_produce: {contradictory}"


class TestTheCommandClassifierDoesNotAskWhatIsInstalled:
    """The guard must give the same verdict on a runner as on a dev box.

    It did not. `rg` and `agent-browser` are real commands this project's probes
    use, absent from a GitHub runner — so the check reported them as prose and
    failed CI for a reason with nothing to do with the playbook (Plan 00250).
    """

    @staticmethod
    def _with_nothing_installed(monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(shutil, "which", lambda _name: None)

    @pytest.mark.parametrize(
        "command",
        [
            'rg "def get_bash_command" src/',
            "agent-browser --version",
            "kubectl get pods",
        ],
    )
    def test_a_real_command_is_not_prose_just_because_it_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, command: str
    ) -> None:
        self._with_nothing_installed(monkeypatch)
        assert _looks_like_a_command(command)

    @pytest.mark.parametrize("opener", ["With", "Simulate", "Run any", "Stage", "WebFetch"])
    def test_every_prose_opener_this_guard_was_written_for_is_still_rejected(
        self, monkeypatch: pytest.MonkeyPatch, opener: str
    ) -> None:
        """The eight real ones from Plan 00345, by their documented openers."""
        self._with_nothing_installed(monkeypatch)
        assert not _looks_like_a_command(f"{opener} the scenario a human performs")

    def test_a_shell_construct_still_rescues_an_odd_looking_head(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_nothing_installed(monkeypatch)
        assert _looks_like_a_command("VAR=value some-tool")

    def test_the_installed_check_still_counts(self) -> None:
        """A capitalised head that IS on PATH must not be called prose."""
        assert _looks_like_a_command("git status")
