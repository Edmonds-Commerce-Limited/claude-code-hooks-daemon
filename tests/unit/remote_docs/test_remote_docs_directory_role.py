"""Every install deploys a `remote-docs` directory role (Plan 00326 Task 1.5).

The remote tree's contract is the inverse of every other markdown tree in the
project: do NOT author here, do NOT reword, capture with the CLI, and the
provenance frontmatter is mandatory. An agent that wanders in without that
framing will helpfully "improve" upstream prose, which destroys the very
property (`fidelity: verbatim`) the tree exists to preserve.
"""

from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.install.directory_role_rules import (
    HUMAN_DOCS_RULE_KEY,
    REMOTE_DOCS_RULE_KEY,
    SHIPPED_RULES,
)


def _spec(key: str):
    return next(spec for spec in SHIPPED_RULES if spec.key == key)


class TestRemoteDocsRole:
    def test_the_role_ships(self) -> None:
        assert any(spec.key == REMOTE_DOCS_RULE_KEY for spec in SHIPPED_RULES)

    def test_globs_are_derived_from_the_layout_axis(self) -> None:
        layout = ProjectLayout.built_in_default()

        globs = _spec(REMOTE_DOCS_RULE_KEY).glob_resolver(layout)

        assert globs == ("remote-docs/**/*.md",)

    def test_globs_follow_a_reconfigured_tree(self) -> None:
        layout = ProjectLayout.built_in_default()
        moved = ProjectLayout(
            source_dirs=layout.source_dirs,
            test_dirs=layout.test_dirs,
            config_dirs=layout.config_dirs,
            vendor_dirs=layout.vendor_dirs,
            agent_docs_dir=layout.agent_docs_dir,
            human_docs_dir=layout.human_docs_dir,
            plan_dir=layout.plan_dir,
            plan_archive_dirs=layout.plan_archive_dirs,
            remote_docs_dir="upstream-docs",
        )

        globs = _spec(REMOTE_DOCS_RULE_KEY).glob_resolver(moved)

        assert globs == ("upstream-docs/**/*.md",)

    def test_the_human_docs_rule_does_not_also_match_the_remote_tree(self) -> None:
        """The two must not overlap, or the terseness rule reaches the tree.

        This is the whole point of D12: `docs/**/*.md` instructing "keep it
        terse, summarise" is the opposite of verbatim capture.
        """
        layout = ProjectLayout.built_in_default()

        human_globs = _spec(HUMAN_DOCS_RULE_KEY).glob_resolver(layout)

        assert all(not glob.startswith(layout.remote_docs_dir) for glob in human_globs)

    def test_the_body_tells_the_agent_not_to_author_here(self) -> None:
        body = _spec(REMOTE_DOCS_RULE_KEY).body_template.lower()

        assert "captur" in body
        assert "frontmatter" in body
