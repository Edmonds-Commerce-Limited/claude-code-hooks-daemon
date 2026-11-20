# Handoff: Plan 00621 Tasks 2.2 and 2.3

Written by the builder of Task 1.1, at a context budget, for the next builder. Worktree
`/workspace/.claude/worktrees/agent-aac077842fc4cd262-5b95f273`, branch
`agent-aac077842fc4cd262-5b95f273`. Do not merge.

## Done

- Task 1.1: the real `actions-qa` v0.2.0 was run from the release bundle (not installed on
  this host). Facts, fixes and the open flags are in DESIGN.md sections 1 and 4.1 and the
  journal entry `JOURNAL/2026-11-20/062442Z-finding-10aba9.md`.
- The unpacked bundle is at `untracked/scratch/aqa-dl/bundle/bin/actions-qa`, and a directory
  with only that binary on it is `untracked/scratch/aqa-only-bin/`. Put that directory first
  on PATH to run `TestProbesAgainstTheRealLinter`. Do not use `bundle/bin`, because its
  `shellcheck` would shadow the Shell strategy's.

## Task 2.2: the `workflow_linter_advisor` SessionStart handler

DESIGN.md section 2.4 is the spec. Copy the registration points from commit `afb74bb20`
(`unproven_venv_advisor`):

- `constants/handlers.py` (HandlerIDMeta)
- `constants/priority.py`: share a slot of 72 or less; `session_actions_directive` (73) must
  stay last.
- `handlers/session_start/__init__.py`
- `daemon/init_config.py`
- `.claude/hooks-daemon.yaml` and `.claude/hooks-daemon.yaml.example`
- `CLAUDE/UPGRADES/UNRELEASED/config-changes/` (look at the existing files there for the
  shape)
- Then regenerate `.claude/HOOKS-DAEMON.md` with `bin/hooks-daemon generate-docs`; do not
  edit it by hand.

The base is `SessionStartHandlerBase`, returning an `AdvisoryResult`. Handler template:
`handlers/session_start/unproven_venv_advisor.py`; test template:
`tests/unit/handlers/session_start/test_unproven_venv_advisor.py`.

The handler's behaviour:

- **When it fires:** only for files directly in `<root>/.github/workflows/` with a `.yml` or
  `.yaml` extension, and only when there is at least one and no file has a `uses:` line naming
  `actions-qa-ci`.
- **Once per session:** that probably means `source == "startup"` only. Check how a sibling
  limits itself (`unproven_venv_advisor` fires on resume too, so it is the wrong model).
- **Unreadable files:** handle them explicitly.
- **Its text:** name the tool, give one line on what it checks, and link
  `https://github.com/LongTermSupport/actions-qa-ci/releases`. Print no install command.

## Task 2.3: guidance, config documentation and a release note

Stale text that says workflows are not linted:

- `handlers/post_tool_use/lint_on_edit.py` `get_claude_md()`:
  - "Ansible YAML is covered too, and only Ansible YAML … left alone: `.github/workflows/`"
  - "A linter that is not installed never blocks. You get an advisory saying it was not
    found". This is now false for the optional workflow linter, which is silent when missing.
  - Document a non-findings exit: the edit is allowed with a "NOT checked" advisory.
  - Document the key `options.timeouts."GitHub Workflow"`.
- `handlers/pre_tool_use/staged_lint_gate.py` `get_claude_md()`: it says "cheap syntax check"
  only, but it now also runs `actions-qa` on staged workflows (DESIGN.md 4.1).
- `docs/guides/HANDLER_REFERENCE.md`: the `#### lint_on_edit` section, around line 3993,
  repeats the Ansible "left alone (`.github/workflows/`…)" text.
- Before editing, search the whole tree for "only Ansible", "left alone" and "workflows".
  Exclude `tests/fixtures/cyber-flag` (a flaggable-content guard blocks a recursive search
  that reaches it). Also check `docs/guides/handlers/`, the README, and tests that pin the
  guidance text.
- The generated CLAUDE.md guidance (the `<hooksdaemon>` block) is built from
  `get_claude_md()`, so fixing the source fixes it.
- Release note: add one under `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, copying the
  numbering and shape of the existing notes.

After that, tick the PLAN.md success criteria. The holding-area line must cite the release
note.

## QA state at handoff

The commit for Task 1.1 was made after a targeted `llm_qa.py changed` run. Its result is in
that commit's message or the journal.
