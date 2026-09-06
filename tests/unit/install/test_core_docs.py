"""Core-document deployment: refresh the daemon's, never touch the project's.

Plan 00334. Two documents per subject, and the split is the design under test:

- ``CLAUDE/core/<Name>.core.md`` is DAEMON-owned and replaced wholesale on
  every deploy, so an upstream fix reaches installs set up long ago.
- ``CLAUDE/<Name>.md`` is CLIENT-owned and written once, so customisation
  survives every upgrade.

Each half fails a different way if it drifts, and both failures are silent, so
both directions are asserted here rather than assumed:

- if the core stops being overwritten, clients are frozen on whatever they were
  seeded with and no upstream correction ever arrives;
- if the override is ever overwritten, a project's own work is destroyed by an
  upgrade -- the failure that makes an unconditional write unacceptable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.core_docs import (
    CORE_DOC_NAMES,
    CORE_DOCS_DIR,
    CORE_SUFFIX,
    core_reference_line,
    core_template_path,
    deploy_core_docs,
    override_seed_content,
)


class TestTheBundleIsComplete:
    """A manifest entry with no template ships a promise the daemon cannot keep."""

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_every_manifest_entry_has_a_bundled_template(self, name: str) -> None:
        assert core_template_path(name).is_file(), (
            f"{name} is in CORE_DOC_NAMES but no template ships for it, so the "
            "deploy cannot produce the document guidance names."
        )

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_bundled_template_is_not_empty(self, name: str) -> None:
        assert core_template_path(name).read_text(encoding="utf-8").strip()


class TestAFreshProjectGetsBothDocuments:
    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_core_document_is_deployed(self, tmp_path: Path, name: str) -> None:
        deploy_core_docs(tmp_path)

        assert (tmp_path / CORE_DOCS_DIR / f"{name}{CORE_SUFFIX}").is_file()

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_override_document_is_seeded(self, tmp_path: Path, name: str) -> None:
        deploy_core_docs(tmp_path)

        assert (tmp_path / "CLAUDE" / f"{name}.md").is_file()

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_override_references_its_core(self, tmp_path: Path, name: str) -> None:
        """The link is the entire point: without it the seeded document is an
        empty stub and the core it was meant to surface is never read."""
        deploy_core_docs(tmp_path)

        text = (tmp_path / "CLAUDE" / f"{name}.md").read_text(encoding="utf-8")

        assert core_reference_line(name) in text

    def test_it_reports_what_it_did(self, tmp_path: Path) -> None:
        result = deploy_core_docs(tmp_path)

        assert result.success
        assert len(result.refreshed_core) == len(CORE_DOC_NAMES)
        assert len(result.seeded_overrides) == len(CORE_DOC_NAMES)


class TestDeployedPermissionsAreReadable:
    """A 644 file inside a 700 directory is still unreadable.

    The mode a `mkdir` lands on is the process umask, not a decision, and a
    daemon installing as one user while a developer works as another is the
    normal case rather than an exotic one. Setting the file mode and leaving
    the directory to chance produces documents that are correct, present, and
    inaccessible -- a failure that reads as "the deploy did not run".
    """

    def test_the_core_directory_is_traversable(self, tmp_path: Path) -> None:
        deploy_core_docs(tmp_path)

        mode = (tmp_path / CORE_DOCS_DIR).stat().st_mode & 0o777

        assert mode & 0o055 == 0o055, (
            f"CLAUDE/core/ deployed as {mode:o}: group and other cannot "
            "traverse it, so the documents inside are unreadable regardless "
            "of their own mode."
        )

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_the_documents_are_world_readable(self, tmp_path: Path, name: str) -> None:
        deploy_core_docs(tmp_path)

        core = tmp_path / CORE_DOCS_DIR / f"{name}{CORE_SUFFIX}"
        override = tmp_path / "CLAUDE" / f"{name}.md"

        assert core.stat().st_mode & 0o044 == 0o044
        assert override.stat().st_mode & 0o044 == 0o044


class TestTheCoreIsRefreshedOnEveryDeploy:
    """Daemon-owned: an upgrade MUST replace it, or upstream fixes never land."""

    def test_a_stale_core_document_is_overwritten(self, tmp_path: Path) -> None:
        name = CORE_DOC_NAMES[0]
        core_file = tmp_path / CORE_DOCS_DIR / f"{name}{CORE_SUFFIX}"
        core_file.parent.mkdir(parents=True)
        core_file.write_text("# stale content from an old release\n", encoding="utf-8")

        deploy_core_docs(tmp_path)

        assert "stale content" not in core_file.read_text(encoding="utf-8")

    def test_the_refreshed_core_matches_the_bundle(self, tmp_path: Path) -> None:
        name = CORE_DOC_NAMES[0]

        deploy_core_docs(tmp_path)

        deployed = (tmp_path / CORE_DOCS_DIR / f"{name}{CORE_SUFFIX}").read_text(encoding="utf-8")
        assert deployed == core_template_path(name).read_text(encoding="utf-8")


class TestTheOverrideIsNeverTouched:
    """Client-owned: the customisation path must never lose to the refresh path."""

    def test_an_existing_override_is_left_byte_identical(self, tmp_path: Path) -> None:
        name = CORE_DOC_NAMES[0]
        docs = tmp_path / "CLAUDE"
        docs.mkdir(parents=True)
        override = docs / f"{name}.md"
        original = "# ours\n\nHard-won project-specific guidance.\n"
        override.write_text(original, encoding="utf-8")

        deploy_core_docs(tmp_path)

        assert override.read_text(encoding="utf-8") == original

    def test_a_pre_existing_document_without_the_reference_is_still_kept(
        self, tmp_path: Path
    ) -> None:
        """The case that makes an unconditional write unacceptable: a project
        that wrote this document ITSELF, before the daemon ever shipped a core
        version. It does not reference anything, and it is still not ours."""
        name = CORE_DOC_NAMES[0]
        docs = tmp_path / "CLAUDE"
        docs.mkdir(parents=True)
        override = docs / f"{name}.md"
        override.write_text("# written by the project long ago\n", encoding="utf-8")

        deploy_core_docs(tmp_path)

        assert override.read_text(encoding="utf-8") == "# written by the project long ago\n"

    def test_a_second_deploy_seeds_nothing_new(self, tmp_path: Path) -> None:
        deploy_core_docs(tmp_path)

        second = deploy_core_docs(tmp_path)

        assert second.seeded_overrides == []
        assert len(second.refreshed_core) == len(CORE_DOC_NAMES)


class TestIdempotence:
    def test_running_twice_leaves_the_same_tree(self, tmp_path: Path) -> None:
        deploy_core_docs(tmp_path)
        first = {
            path.relative_to(tmp_path): path.read_bytes()
            for path in sorted(tmp_path.rglob("*"))
            if path.is_file()
        }

        deploy_core_docs(tmp_path)
        second = {
            path.relative_to(tmp_path): path.read_bytes()
            for path in sorted(tmp_path.rglob("*"))
            if path.is_file()
        }

        assert first == second


class TestTheSeedContent:
    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_it_names_the_core_as_not_editable(self, name: str) -> None:
        """A reader who edits the core loses the edit on the next upgrade, so
        the seed has to say so where they will actually see it."""
        assert "overwritten" in override_seed_content(name)

    @pytest.mark.parametrize("name", CORE_DOC_NAMES)
    def test_it_invites_project_content(self, name: str) -> None:
        assert "Project-specific" in override_seed_content(name)
