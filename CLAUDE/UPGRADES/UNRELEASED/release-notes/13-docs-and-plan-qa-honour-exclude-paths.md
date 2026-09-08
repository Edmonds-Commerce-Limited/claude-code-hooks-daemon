# Callout: docs QA and plan QA honour `daemon.exclude_paths`

**Plan**: 00362
**Audience**: operators

The project-wide `daemon.exclude_paths` list now reaches the documentation
and plan QA surfaces — `docs_qa_edit`, `docs_qa_commit_gate`,
`docs_qa_sweep`, `plan_qa_edit`, `plan_qa_commit_gate`, `plan_qa_sweep` and
the `docs-qa` / `plan-qa` CLIs — through the same glob matcher every content
blocker already uses. A markdown file or plan path matching one of its globs
is never linted at edit time, never gated at commit time and never reported
by a session sweep. Previously those two subsystems ignored the list
entirely, so a project that exempted a directory the way the shipped
guidance recommends still received documentation and plan findings for it.

Check your `daemon.exclude_paths` before upgrading: a fixture tree that
must keep producing documentation or plan findings has to stay out of that
list, because after this release listing it silences those findings too.
Docs QA's own narrower `documentation.qa.scope_exclude_globs` is unchanged
and still applies alongside.
