"""The class-14 Detector — `fetch-then-execute-unpinned` (Plan 00412).

The class: a fetch whose response is executed, where the destination is not
fully determined by the shipped code, the bytes are not verified against a
digest carried independently of them, and the scheme is not forced. Plus the
adjacent case that shares its cause — a flag that turns a protection OFF on a
production path.

**Every rule here is paired with a control that a sloppier pattern would fail.**
That is the whole content of these tests. The worklist calls the downgrade-flag
rule "the cheapest rule in this report and I would ship it first", and cheap
rules are exactly the ones that ship with a `-k` pattern matching `sort -k2`
and get switched off inside a week. `--insecure` and `-k` are therefore scoped
to a line that actually fetches, and the documented install one-liner sitting
in a COMMENT is not a command.

The instances this was built against, all three verified live in the tree
before a line of it was written:

- `scripts/upgrade.sh` builds a URL from `${HOOKS_DAEMON_UPGRADE_BASE_URL:-…}`
  with no scheme check and fetches it, so `http://` is accepted.
- `install.sh` pipes a third-party installer into `sh` with both streams
  discarded.
- `scripts/upgrade.sh` sets `protocol.file.allow=always` on the clone that
  produces the installed daemon.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_security_downgrade_flags.py"


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_security_downgrade_flags", _CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(root: Path, relative: str, body: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return path


def _rules_for(checker: ModuleType, root: Path) -> set[str]:
    return {violation.rule for violation in checker.scan(root)}


class TestDowngradeFlag:
    @pytest.mark.parametrize(
        "line",
        [
            'git -c protocol.file.allow=always clone --quiet "$URL" "$DIR"',
            "GIT_ALLOW_PROTOCOL=file git clone $URL",
            'git commit --no-verify -m "skip the hooks"',
            "PYTHONHTTPSVERIFY=0 python3 fetch.py",
        ],
    )
    def test_a_protection_turned_off_is_reported(
        self, checker: ModuleType, tmp_path: Path, line: str
    ) -> None:
        _write(tmp_path, "scripts/install.sh", f"#!/usr/bin/env bash\n{line}\n")

        assert checker.RULE_DOWNGRADE_FLAG in _rules_for(checker, tmp_path)

    def test_verify_false_in_python_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "src/fetch.py", "import requests\nrequests.get(url, verify=False)\n")

        assert checker.RULE_DOWNGRADE_FLAG in _rules_for(checker, tmp_path)

    @pytest.mark.parametrize(
        "line",
        [
            "sort -k2 results.txt",
            "cut -d, -f2 data.csv | sort -k 1",
            "kubectl get pods -k ./overlay",
        ],
    )
    def test_a_k_flag_on_a_line_that_fetches_nothing_is_untouched(
        self, checker: ModuleType, tmp_path: Path, line: str
    ) -> None:
        """The control that decides whether this rule survives contact.

        `-k` means `--insecure` to curl and `--key` to sort. A rule that cannot
        tell them apart fires on ordinary text processing, and a rule that
        fires on ordinary text processing gets switched off — at which point it
        protects nothing, which is the failure this whole plan exists to avoid.
        """
        _write(tmp_path, "scripts/report.sh", f"#!/usr/bin/env bash\n{line}\n")

        assert checker.RULE_DOWNGRADE_FLAG not in _rules_for(checker, tmp_path)

    def test_insecure_on_a_line_that_does_fetch_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "scripts/get.sh", '#!/usr/bin/env bash\ncurl -k -o out "$URL"\n')

        assert checker.RULE_DOWNGRADE_FLAG in _rules_for(checker, tmp_path)


class TestCommentsAreNotCommands:
    """The documented install one-liner is text, and this repo ships several.

    `install.sh` and `scripts/upgrade.sh` both carry the published
    `curl … | bash` invocation in their header comments so a reader can see how
    the script is meant to be run. Flagging those would make the Detector's
    first run mostly noise about its own documentation.
    """

    @pytest.mark.parametrize(
        ("relative", "body"),
        [
            (
                "scripts/upgrade.sh",
                "#!/usr/bin/env bash\n"
                "# Install with:\n"
                "#   curl -fsSL https://example.test/install.sh | bash\n"
                "echo ready\n",
            ),
            (
                "src/notes.py",
                '"""Docs.\n\nRun `curl https://example.test/i.sh | sh` to install.\n"""\n',
            ),
        ],
    )
    def test_a_fetch_inside_a_comment_is_not_a_fetch(
        self, checker: ModuleType, tmp_path: Path, relative: str, body: str
    ) -> None:
        _write(tmp_path, relative, body)

        assert checker.scan(tmp_path) == []

    def test_a_trailing_comment_does_not_hide_a_real_command(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """Stripping comments must not become a way to launder the line.

        The strip removes what follows a `#`, so a real command carrying an
        explanatory comment after it is still judged on the command half.
        """
        _write(
            tmp_path,
            "scripts/go.sh",
            "#!/usr/bin/env bash\ncurl -fsSL $U | sh  # best effort\n",
        )

        assert checker.RULE_FETCH_PIPED_TO_SHELL in _rules_for(checker, tmp_path)


class TestFetchPipedToShell:
    @pytest.mark.parametrize(
        "line",
        [
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            'wget -qO- "$URL" | bash',
            "curl -fsSL $URL | sudo bash -s --",
        ],
    )
    def test_a_fetch_executed_by_a_shell_is_reported(
        self, checker: ModuleType, tmp_path: Path, line: str
    ) -> None:
        _write(tmp_path, "install.sh", f"#!/usr/bin/env bash\n{line}\n")

        assert checker.RULE_FETCH_PIPED_TO_SHELL in _rules_for(checker, tmp_path)

    @pytest.mark.parametrize(
        "line",
        [
            'curl -fsSL -o "$tmp" "$url"',
            'wget -O out.tar.gz "$URL"',
            'curl -fsSL "$URL" | jq .version',
            'curl -fsSL "$URL" | grep -c ok',
        ],
    )
    def test_a_fetch_that_is_not_executed_is_untouched(
        self, checker: ModuleType, tmp_path: Path, line: str
    ) -> None:
        """Downloading is not the defect; handing the bytes to an interpreter is.

        `| jq` and `| grep` are the discriminating controls — a rule keyed on
        "curl followed by a pipe" denies both, and reading a version out of a
        JSON endpoint is routine.
        """
        _write(tmp_path, "scripts/get.sh", f"#!/usr/bin/env bash\n{line}\n")

        assert checker.RULE_FETCH_PIPED_TO_SHELL not in _rules_for(checker, tmp_path)


class TestSuppressedFetch:
    @pytest.mark.parametrize(
        "line",
        [
            "curl -LsSf https://example.test/i.sh | sh >/dev/null 2>&1",
            'wget -qO- "$URL" &>/dev/null',
            'git clone --quiet "$URL" "$DIR" 2>/dev/null',
        ],
    )
    def test_a_fetch_whose_failure_is_discarded_is_reported(
        self, checker: ModuleType, tmp_path: Path, line: str
    ) -> None:
        _write(tmp_path, "install.sh", f"#!/usr/bin/env bash\n{line}\n")

        assert checker.RULE_SUPPRESSED_FETCH in _rules_for(checker, tmp_path)

    def test_a_fetch_whose_status_is_consumed_is_untouched(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The shape `upgrade.sh` deliberately adopted, and it must stay legal.

        `_fetch_python_discovery_lib` captures `command -v` into a variable
        precisely so nothing is discarded, and consumes curl's exit status in
        the `if`. A rule that flagged that would be telling the author to undo
        a fix made for this exact concern.
        """
        _write(
            tmp_path,
            "scripts/upgrade.sh",
            '#!/usr/bin/env bash\nif curl -fsSL -o "$tmp" "$url" && [ -s "$tmp" ]; then\n'
            "    echo ok\nfi\n",
        )

        assert checker.RULE_SUPPRESSED_FETCH not in _rules_for(checker, tmp_path)


class TestUnvalidatedUrlExpansion:
    def test_an_env_overridable_base_url_with_no_scheme_check_is_reported(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """D-NET N5, reduced to its mechanism.

        The real chain is `curl -o "$tmp"` → `printf` → the caller's
        `discovery_lib` → `. "$discovery_lib"`. No token-following heuristic
        survives that many hops, which is why this rule keys on the URL's
        PROVENANCE instead: a base URL an attacker can set to `http://` is the
        defect whether or not the bytes are traceable to the `source`.
        """
        _write(
            tmp_path,
            "scripts/upgrade.sh",
            "#!/usr/bin/env bash\n"
            'base_url="${HOOKS_DAEMON_UPGRADE_BASE_URL:-https://raw.githubusercontent.com/o/r}"\n'
            'url="$base_url/$ref/scripts/lib/python_discovery.sh"\n'
            'curl -fsSL --max-time 30 -o "$tmp" "$url"\n',
        )

        assert checker.RULE_UNVALIDATED_URL_EXPANSION in _rules_for(checker, tmp_path)

    def test_a_scheme_checked_override_is_untouched(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """The remedy must actually clear the finding, or nobody applies it."""
        _write(
            tmp_path,
            "scripts/upgrade.sh",
            "#!/usr/bin/env bash\n"
            'base_url="${HOOKS_DAEMON_UPGRADE_BASE_URL:-https://raw.githubusercontent.com/o/r}"\n'
            'case "$base_url" in\n'
            "    https://*) ;;\n"
            '    *) _fail "refusing a non-https base URL: $base_url" ;;\n'
            "esac\n"
            'curl -fsSL -o "$tmp" "$base_url/x"\n',
        )

        assert checker.RULE_UNVALIDATED_URL_EXPANSION not in _rules_for(checker, tmp_path)

    def test_an_expansion_that_is_not_a_url_is_untouched(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(
            tmp_path,
            "scripts/upgrade.sh",
            '#!/usr/bin/env bash\nref="${HOOKS_DAEMON_UPGRADE_REF:-main}"\necho "$ref"\n',
        )

        assert checker.RULE_UNVALIDATED_URL_EXPANSION not in _rules_for(checker, tmp_path)

    def test_a_file_that_never_fetches_is_untouched(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """An unvalidated URL nobody retrieves is a string, not a fetch.

        Without this the rule fires on every default-endpoint constant in the
        tree, which is the noise that gets a cheap rule disabled.
        """
        _write(
            tmp_path,
            "scripts/report.sh",
            '#!/usr/bin/env bash\nbase="${DOCS_URL:-https://example.test}"\necho "see $base"\n',
        )

        assert checker.RULE_UNVALIDATED_URL_EXPANSION not in _rules_for(checker, tmp_path)


class TestScope:
    def test_test_directories_are_excluded(self, checker: ModuleType, tmp_path: Path) -> None:
        """Fixtures legitimately contain the constructs this hunts.

        `tests/acceptance/conftest.py` passes `protocol.file.allow=always` on
        purpose, so a local clone fixture works. Scanning tests would report
        the harness for doing its job.
        """
        _write(
            tmp_path,
            "tests/acceptance/conftest.py",
            'ARGS = ["-c", "protocol.file.allow=always"]\n',
        )

        assert checker.scan(tmp_path) == []

    def test_untracked_and_vendor_trees_are_excluded(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        _write(tmp_path, "untracked/scratch/probe.sh", "curl $U | sh\n")
        _write(tmp_path, "node_modules/pkg/install.sh", "curl $U | sh\n")

        assert checker.scan(tmp_path) == []

    def test_a_violation_names_its_file_and_line(
        self, checker: ModuleType, tmp_path: Path
    ) -> None:
        """A finding a reader cannot navigate to is a finding nobody acts on."""
        _write(
            tmp_path,
            "install.sh",
            "#!/usr/bin/env bash\necho one\ncurl -LsSf https://example.test/i.sh | sh\n",
        )

        violations = checker.scan(tmp_path)

        assert len(violations) == 1
        assert violations[0].path == "install.sh"
        assert violations[0].line == 3
