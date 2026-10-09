# Callout: a released CHANGELOG section is checked against its tag

**Plan**: 00474
**Audience**: everyone

`./scripts/qa/llm_qa.py changed` now runs `released_changelog`. It fails when a `## [X.Y.Z]` section of `CHANGELOG.md` whose version has a git tag `vX.Y.Z` differs from that section at the tag. Agents had been appending release notes to the newest published section.

New notes belong in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`. The release process writes `CHANGELOG.md` itself as a new section with no tag yet, which the check allows.
