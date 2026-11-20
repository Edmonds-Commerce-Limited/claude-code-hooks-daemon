# Callout: GitHub workflow files are linted on edit by the optional actions-qa linter

**Plan**: 00621
**Audience**: client projects

A write or edit of a file directly in `.github/workflows/` now runs the external `actions-qa check --file` linter ([actions-qa-ci](https://github.com/LongTermSupport/actions-qa-ci/releases)) where it is installed. Only its findings exit (1) is reported as a lint failure; any other exit allows the edit with a "NOT checked" advisory, and a project without the linter sees nothing on an edit. The commit gate `staged_lint_gate` runs the same linter on staged workflows; in its shipped `mode: warn` a finding is an advisory naming the file. The budget is `lint_on_edit`'s `options.timeouts."GitHub Workflow"`.

A new session-start advisory, `workflow_linter_advisor` (on by default), suggests the linter once per new session when a project has workflows and none uses it. It links the release page and prints no install command; set `enabled: false` to silence it.
