"""Tests for the sensitive-content QA checker (Plan 00201).

Whole-tree backstop for the ``sensitive_content`` handler: same two sources
(public patterns, secret word list), same no-echo rule for the secret list.

NOTE: this repo's own dogfood config enables a real public path pattern (see
``.claude/hooks-daemon.yaml``). The example path below is therefore built via
string concatenation at runtime, never written as one contiguous literal
anywhere in this file (including comments/docstrings) — otherwise editing
this very file would trip that live handler.
"""

import json
import subprocess  # nosec B404 - subprocess used for running the QA checker only
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECKER = _REPO_ROOT / "scripts" / "qa" / "check_sensitive_content.py"
_JSON_OUTPUT = _REPO_ROOT / "untracked" / "qa" / "sensitive_content.json"
_ARTEFACT_NAME = "sensitive_content.json"

# Split across concatenated literals so this FILE's own on-disk text never
# contains the contiguous trigger string this repo's dogfood config blocks.
_EXAMPLE_PATH = "/var/www" + "/vh" + "osts"


def _run_checker(scan_path: Path, config_path: Path) -> dict[str, Any]:
    subprocess.run(  # nosec B603 - trusted first-party checker script
        [
            sys.executable,
            str(_CHECKER),
            "--json",
            "--path",
            str(scan_path),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # A scoped scan reports BESIDE what it scanned. Reading the repository-wide
    # artefact here would make every test below depend on a file the whole QA
    # suite also writes, and would leave this fixture's verdict standing as the
    # repository's own.
    scoped = scan_path / _ARTEFACT_NAME
    assert scoped.exists(), f"Expected JSON output at {scoped}"
    return json.loads(scoped.read_text())


def _write_config(
    config_path: Path,
    *,
    public_patterns=None,
    secret_word_list_path=None,
    exclude_paths=None,
) -> None:
    options_lines = []
    if public_patterns is not None:
        options_lines.append("        public_patterns:")
        for entry in public_patterns:
            options_lines.append(f"          - name: {entry['name']}")
            options_lines.append(f"            pattern: '{entry['pattern']}'")
            options_lines.append(f"            description: '{entry.get('description', '')}'")
    if secret_word_list_path is not None:
        options_lines.append(f"        secret_word_list_path: {secret_word_list_path}")
    if exclude_paths is not None:
        options_lines.append("        exclude_paths:")
        for glob in exclude_paths:
            options_lines.append(f"          - '{glob}'")

    options_block = "\n".join(options_lines) if options_lines else "        {}"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "handlers:\n"
        "  pre_tool_use:\n"
        "    sensitive_content:\n"
        "      enabled: true\n"
        "      options:\n" + options_block + "\n"
    )


class TestPublicPatternScanning:
    def test_no_config_no_violations(self, tmp_path: Path) -> None:
        (tmp_path / "file.txt").write_text("nothing sensitive here\n")
        data = _run_checker(tmp_path, tmp_path / "nonexistent.yaml")
        assert data["summary"]["passed"] is True
        assert data["summary"]["total_violations"] == 0

    def test_matching_content_is_flagged(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[
                {"name": "example-path", "pattern": _EXAMPLE_PATH, "description": "server path"}
            ],
        )
        (tmp_path / "file.txt").write_text(f"deploy to {_EXAMPLE_PATH}/app\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        assert data["summary"]["total_violations"] == 1
        violation = data["violations"][0]
        assert violation["rule"] == "public-pattern:example-path"
        assert _EXAMPLE_PATH in violation["message"]

    def test_reports_file_and_line(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config, public_patterns=[{"name": "alpha", "pattern": "alpha", "description": ""}]
        )
        target = tmp_path / "file.txt"
        target.write_text("line one\nline two has alpha in it\nline three\n")

        data = _run_checker(tmp_path, config)

        violation = data["violations"][0]
        assert violation["file"] == str(target)
        assert violation["line"] == 2

    def test_clean_content_passes(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config, public_patterns=[{"name": "alpha", "pattern": "alpha", "description": ""}]
        )
        (tmp_path / "file.txt").write_text("nothing to see here\n")

        data = _run_checker(tmp_path, config)
        assert data["summary"]["passed"] is True


class TestSecretWordListScanning:
    def test_missing_secret_file_is_inert(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "file.txt").write_text("anything at all\n")

        data = _run_checker(tmp_path, config)
        assert data["summary"]["passed"] is True

    def test_matching_secret_term_is_flagged_without_revealing_it(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "file.txt").write_text("contains zzqx-nonsense-term here\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        violation = data["violations"][0]
        assert violation["rule"] == "secret-word-list"
        assert "zzqx-nonsense-term" not in violation["message"]
        assert "entry 1 of 1" in violation["message"]

    def test_secret_term_absent_from_full_json_output(self, tmp_path: Path) -> None:
        """THE core security property: scan the entire response, not just one field."""
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "file.txt").write_text("contains zzqx-nonsense-term here\n")

        data = _run_checker(tmp_path, config)

        assert "zzqx-nonsense-term" not in json.dumps(data)

    def test_matching_is_case_insensitive(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "file.txt").write_text("CONTAINS ZZQX-NONSENSE-TERM HERE\n")

        data = _run_checker(tmp_path, config)
        assert data["summary"]["passed"] is False

    def test_regex_metacharacter_term_matches_literally(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("a.b*c\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "match.txt").write_text("has a.b*c literally\n")
        (tmp_path / "nomatch.txt").write_text("has axbyc instead\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["total_violations"] == 1
        assert data["violations"][0]["file"].endswith("match.txt")

    def test_secret_file_itself_never_scanned(self, tmp_path: Path) -> None:
        """The secret list is gitignored — it must never appear as a scan target."""
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)

        data = _run_checker(tmp_path, config)

        scanned_files = {v["file"] for v in data["violations"]}
        assert str(secret_file) not in scanned_files


class TestFileNamesAreScannedNotJustContent:
    """A NAME leaks as loudly as a body.

    ``git filter-repo --replace-text`` rewrites blob contents only; renaming a
    file that carries an identifier in its NAME needs ``--path-rename``. A
    content-only scanner has exactly that blind spot, so it can report a clean
    tree while a tracked path still spells the term out.
    """

    def test_term_in_file_name_is_flagged(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "report-zzqx-nonsense-term-v1.md").write_text("wholly innocent body\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        violation = data["violations"][0]
        assert violation["rule"] == "secret-word-list"
        assert violation["line"] == 0

    def test_term_in_directory_name_is_flagged(self, tmp_path: Path) -> None:
        """The directory is part of the path, so ``path.name`` alone is not enough."""
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        nested = tmp_path / "zzqx-nonsense-term"
        nested.mkdir()
        (nested / "notes.md").write_text("wholly innocent body\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        assert data["violations"][0]["rule"] == "secret-word-list"

    def test_file_name_violation_never_reveals_the_term(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "report-zzqx-nonsense-term-v1.md").write_text("wholly innocent body\n")

        data = _run_checker(tmp_path, config)

        # The FILE field necessarily carries the path — that is the whole point
        # of reporting it — but the MESSAGE must still name only an index.
        assert "zzqx-nonsense-term" not in data["violations"][0]["message"]
        assert "entry 1 of 1" in data["violations"][0]["message"]

    def test_public_pattern_in_file_name_is_flagged(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config, public_patterns=[{"name": "alpha", "pattern": "alpha", "description": ""}]
        )
        (tmp_path / "alpha-notes.md").write_text("wholly innocent body\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        violation = data["violations"][0]
        assert violation["rule"] == "public-pattern:alpha"
        assert violation["line"] == 0

    def test_match_in_the_scan_root_itself_is_ignored(self, tmp_path: Path) -> None:
        """THE negative control.

        Names are matched RELATIVE to the scan root. Matching the absolute path
        would flag every file in a checkout that merely happens to live beneath
        a directory whose name contains a listed term — an unfixable false
        positive that would force the whole guard to be disabled.
        """
        root = tmp_path / "zzqx-nonsense-term"
        root.mkdir()
        secret_file = root / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = root / "hooks-daemon.yaml"
        _write_config(config)
        (root / "notes.md").write_text("wholly innocent body\n")

        data = _run_checker(root, config)

        assert data["summary"]["passed"] is True

    def test_clean_name_and_clean_body_still_passes(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "notes.md").write_text("wholly innocent body\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is True


class TestExcludePaths:
    def test_excluded_path_is_not_scanned(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[{"name": "alpha", "pattern": "alpha", "description": ""}],
            exclude_paths=["fixtures/**"],
        )
        excluded_dir = tmp_path / "fixtures"
        excluded_dir.mkdir()
        (excluded_dir / "sample.txt").write_text("alpha appears here\n")
        # Something left to scan, or the run fails as an empty scan (00466 N26).
        (tmp_path / "clean.txt").write_text("nothing to report\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is True
        assert data["summary"]["total_violations"] == 0

    def test_excluding_every_file_is_not_a_pass(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config, exclude_paths=["fixtures/**"])
        excluded_dir = tmp_path / "fixtures"
        excluded_dir.mkdir()
        (excluded_dir / "sample.txt").write_text("clean\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        assert "examined 0 of" in data["summary"]["vacuous_scan"]

    def test_non_excluded_path_still_scanned(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[{"name": "alpha", "pattern": "alpha", "description": ""}],
            exclude_paths=["fixtures/**"],
        )
        (tmp_path / "other.txt").write_text("alpha appears here\n")

        data = _run_checker(tmp_path, config)

        assert data["summary"]["passed"] is False
        assert data["summary"]["total_violations"] == 1


class TestFilesScannedCount:
    def test_reports_files_scanned(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "a.txt").write_text("x\n")
        (tmp_path / "b.txt").write_text("y\n")

        data = _run_checker(tmp_path, config)
        assert data["summary"]["files_scanned"] == 2


class TestAScopedScanNeverPublishesTheRepositoryVerdict:
    """``untracked/qa/sensitive_content.json`` means "this REPOSITORY is clean".

    A ``--path`` scan answers a different question — "is this directory clean"
    — and writing its answer to the repository artefact states something the
    scan never established. The artefact is what ``llm_qa.py`` produces for an
    agent to read, so the wrong verdict is consumed as fact rather than noticed.

    This was not hypothetical. A test fixture named with a blocked term left
    the artefact reading ``passed: false, files_scanned: 1`` against a path
    under ``/tmp``, while the repository itself was clean across 3,514 tracked
    files — and it was believed, in session, before being checked.
    """

    def test_the_repository_artefact_is_untouched_by_a_scoped_scan(self, tmp_path: Path) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "harmless.txt").write_text("nothing to see\n")
        before = _JSON_OUTPUT.read_bytes() if _JSON_OUTPUT.exists() else None

        _run_checker(tmp_path, config)

        after = _JSON_OUTPUT.read_bytes() if _JSON_OUTPUT.exists() else None
        assert after == before, (
            "a --path scan overwrote the repository-wide QA artefact; its "
            "verdict describes the scanned directory, not this repository"
        )

    def test_the_scoped_verdict_is_written_beside_what_was_scanned(self, tmp_path: Path) -> None:
        """It still has to land somewhere — the caller asked for --json."""
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(config)
        (tmp_path / "harmless.txt").write_text("nothing to see\n")

        _run_checker(tmp_path, config)

        assert (tmp_path / _ARTEFACT_NAME).is_file()


# Assembled at runtime so this file's own text never matches the dogfood
# session-uuid public pattern: an upstream documentation example UUID.
_DOC_UUID = "-".join(("550e8400", "e29b", "41d4", "a716", "446655440000"))
_UUID_REGEX = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_VENDORED_REL = Path("remote-docs") / "example.com" / "docs" / "hooks.md"


def _vendored(body: str) -> str:
    """A document exactly as ``remote-docs add`` writes it."""
    from datetime import UTC, datetime

    from claude_code_hooks_daemon.remote_docs.capture import capture

    return capture(
        "https://example.com/docs/hooks",
        fetch_fn=lambda _url: body.encode("utf-8"),
        now=datetime(2026, 9, 24, tzinfo=UTC),
    ).content


class TestFaithfulVendoredCopiesStandPublicPatternsDown:
    """Plan 00468: the tree scan agrees with the handler about vendored copies.

    Public patterns stand down for the body of a remote-docs file whose
    provenance is valid and whose body still hashes to ``source_sha256``. An
    edited copy, a non-vendored file and the secret word list are unaffected.
    """

    def _scan(self, tmp_path: Path, relpath: Path, content: str) -> dict[str, Any]:
        terms_file = tmp_path / "temporary-terms.txt"
        terms_file.write_text("zzqx-nonsense-term\n")
        config = tmp_path / "hooks-daemon.yaml"
        _write_config(
            config,
            public_patterns=[{"name": "session-uuid", "pattern": _UUID_REGEX}],
            secret_word_list_path=terms_file.name,
        )
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return _run_checker(tmp_path, config)

    def test_a_faithful_vendored_file_is_not_flagged(self, tmp_path: Path) -> None:
        data = self._scan(tmp_path, _VENDORED_REL, _vendored(f"# Hooks\n\nid {_DOC_UUID}\n"))

        assert data["summary"]["passed"] is True, data["violations"]

    def test_a_vendored_file_edited_after_capture_is_flagged(self, tmp_path: Path) -> None:
        content = _vendored("# Hooks\n\nupstream\n") + f"ours {_DOC_UUID}\n"

        data = self._scan(tmp_path, _VENDORED_REL, content)

        assert [v["rule"] for v in data["violations"]] == ["public-pattern:session-uuid"]

    def test_a_faithful_vendored_file_with_a_secret_term_is_flagged(self, tmp_path: Path) -> None:
        data = self._scan(tmp_path, _VENDORED_REL, _vendored("# Hooks\n\nzzqx-nonsense-term\n"))

        assert [v["rule"] for v in data["violations"]] == ["secret-word-list"]

    def test_a_non_vendored_markdown_file_is_flagged(self, tmp_path: Path) -> None:
        content = _vendored(f"# Hooks\n\nid {_DOC_UUID}\n")

        data = self._scan(tmp_path, Path("docs") / "hooks.md", content)

        assert [v["rule"] for v in data["violations"]] == ["public-pattern:session-uuid"]
