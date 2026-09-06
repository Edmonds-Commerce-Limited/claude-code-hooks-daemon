# Plan 00334: core doc templates for client projects

**Status**: In Progress
**Created**: 2026-09-06
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct implementation, with one sub-agent per document
for the genericisation pass

## Overview

The daemon can be configured to enforce a workflow whose documentation it never
creates. `plan_workflow.enabled: true` sets `workflow_docs` to
`CLAUDE/PlanWorkflow.md` (`config/models.py:808-811`), handler guidance tells
the agent to read that file (`plan_workflow.py:78`), and nothing ever deploys
it. A freshly-installed client project therefore enforces a workflow against a
document that does not exist, and instructs its agent to read a path that
resolves to nothing.

Found in a real client install, not by inspection.

It is a class, not an instance:

| Surface                                                    | Names                    | Deployed |
| ---------------------------------------------------------- | ------------------------ | -------- |
| `handlers/pre_tool_use/plan_workflow.py:78`                | `CLAUDE/PlanWorkflow.md` | never    |
| `handlers/pre_tool_use/worktree_file_copy.py:57`           | `CLAUDE/Worktree.md`     | never    |
| `config/models.py:808-811`                                 | `CLAUDE/PlanWorkflow.md` | never    |
| `install/templates/agents/hooks-daemon-docs-qa.md:135-136` | `CLAUDE/PlanWorkflow.md` | never    |

The last is the sharpest: a file the daemon **does** ship cites one it does
**not**. And `plan_number_helper.py:499-503` guards the same kind of reference
with an `.exists()` check first, so the hazard is already known here and the
guard is applied inconsistently.

Two existing facts shape the fix rather than being incidental to it. The
ownership machinery already exists — `install/plan_workflow.py` deploys
`PlanJournalling.md` as a CLIENT-owned seed-once document (`:334-378`) beside
DAEMON-owned always-overwritten `mkplan.bash` (`:379-416`), so a shipped doc
template is not a new concept and `PlanWorkflow.md` is simply the one left out.
And this project's own document cannot ship verbatim: `CLAUDE/PlanWorkflow.md`
(34K) opens by naming "the Claude Code Hooks Daemon project", so shipping it
would push this repo's specifics into every client — the outcome the owner
ruled out.

## Goals

- No daemon-emitted guidance names a client document the daemon does not ensure
  exists.
- A client receives a usable core workflow document on install AND upgrade, and
  keeps its own customisations across both.
- Upstream improvements to a core document reach existing clients on upgrade
  without overwriting anything the client wrote.
- This repository consumes the templates it ships, verifiably rather than by
  convention, so a broken template breaks our own build first.

## Non-Goals

- **Rewriting the documents' content.** Genericisation removes project-specific
  claims; it is not a rewrite of guidance that already works.
- **Shipping every `CLAUDE/*.md` in this repo.** Several are genuinely
  project-specific (`ARCHITECTURE.md`, `AgentTeam.md`, `SELF_INSTALL.md`) and
  would be noise in a client. The set is chosen, not swept.
- **Making `@` a real import.** It is a CLAUDE.md feature; in a referenced
  document it is a convention. This plan VERIFIES the convention is followed
  rather than pretending the mechanism is something it is not (Decision 3).

## Tasks

### Phase 1: Reproduction (RED)

- [x] ✅ **Task 1.1**: Failing test proving a fresh client-mode deploy leaves
  `CLAUDE/PlanWorkflow.md` absent while `workflow_docs` points at it.
- [x] ✅ **Task 1.2**: Failing test for the general invariant — every client doc
  path named in handler guidance or a config default is either deployed or
  guarded by an existence check. Six tests, all RED, each naming a real defect.

### Phase 2: The core/override mechanism

- [x] ✅ **Task 2.1**: `install/templates/core/` as the home for genericised
  core documents, deployed DAEMON-owned and overwritten every run (mirroring
  `mkplan.bash`) into `<project>/CLAUDE/core/`.
- [x] ✅ **Task 2.2**: Seed the CLIENT-owned override document once, never
  clobbering it, carrying the reference to its core document plus an empty
  overrides section (mirroring `_TEMPLATE_.md`). The reference is a markdown
  link rather than an `@`-import (Decision 3).
- [x] ✅ **Task 2.3**: Wire into `bootstrap_plan_workflow`, so every path that
  turns the plan workflow on also produces the document it names.

### Phase 3: The first core document

- [x] ✅ **Task 3.1**: Genericise `CLAUDE/PlanWorkflow.md` and `Worktree.md`
  into core documents. Nothing was lost in the reduction — each core is LARGER
  than the original it was extracted from.
- [x] ✅ **Task 3.2**: Convert this repo's own documents to the reference +
  overrides form (1053 → 90 lines and 104 lines), so the dogfooding is live.
- [x] ✅ **Task 3.3**: The other two offenders needed no edit: deploying the
  documents is what makes `worktree_file_copy.py:57` and the shipped
  `hooks-daemon-docs-qa.md` reference resolve. A reference is only wrong while
  its target is missing.

### Phase 4: The remaining core set

- [x] ✅ **Task 4.1**: Roster selected and recorded, with the reason each
  document is in or out (Decision 6).
- [ ] ⬜ **Task 4.2**: Genericise and ship the selected documents, one sub-agent
  per document.
- [ ] ⬜ **Task 4.3**: Deploy to the path the CONFIG names, not a hardcoded
  `CLAUDE/` (Decision 7) — found by auditing the Phase 2 work, reproduced RED.

### Phase 5: Verify

- [ ] ⬜ **Task 5.1**: The Phase 1 invariant test passes with no exemptions.
- [ ] ⬜ **Task 5.2**: Full QA gate green; daemon restarts; docs regenerated.
- [ ] ⬜ **Task 5.3**: A simulated fresh client install produces a project whose
  named documents all exist.

## Technical Decisions

### Decision 1: the core document is DAEMON-owned, the override is CLIENT-owned

This is the whole design, and both halves are load-bearing. A single
client-owned document strands every existing client on the version it was
seeded with, because the deploy must never clobber a customised file — upstream
improvements could then never reach anyone. A single daemon-owned document
destroys customisation on every upgrade.

Splitting them stops the refresh path and the customisation path competing:
`CLAUDE/core/X.core.md` is replaced wholesale on every deploy and must never be
hand-edited; `CLAUDE/X.md` is written once and never touched again.

The vocabulary is not invented here — `install/plan_workflow.py` already
distinguishes exactly these two categories and states the rule for each.

### Decision 2: the core document is DEPLOYED into the client, not referenced in the vendored clone

A client install already contains this entire repository at
`.claude/hooks-daemon/`, so the core document could be referenced there instead
of copied. Rejected: that path differs between client mode and self-install
mode, where the daemon root IS the project root. `utils/cli_command` documents
at length what that difference costs — it shipped a documented command that
expanded to `-m: command not found`, and agents concluded the package was not
installed and tried to "repair" working installations.

Deploying a copy makes one path correct in both modes. `directory_role_rules.py`
chose the other option for `DirectoryRoles.md`; this plan does not follow it.

### Decision 3: a markdown link, not an `@`-import — and the read is VERIFIED

The owner asked for `@`-style read forcing. Implemented as a plain markdown
link instead, because this project already has a law against the alternative:
R6 in `DocumentationStrategy.md` prohibits `@`-imports outside the resident set
in root `CLAUDE.md`, since they re-inline eagerly and defeat progressive
disclosure. The `at-import-census` check offers an allowlist escape hatch
expressly limited to *"a deliberately always-loaded file"* — which a core
document is not, being read on demand. Taking that hatch would have declared
these files resident in order to silence a check that was right.

Nothing is lost by the link, because the `@` was never a mechanism here
either: it auto-resolves only inside a CLAUDE.md chain, and these documents sit
outside one. In both spellings the forced read is a convention an agent
follows.

What actually enforces it is a test asserting each override document exists AND
still references its core. That turns "this project dogfoods the template" from
a claim in a plan into a fact the build enforces. Without it this repo's own
override could drift off its core with nothing noticing — the exact failure
this plan exists to fix, reintroduced one level up.

### Decision 5: a missing bundled template does not fail a client's install

It fails the BUILD instead. A manifest entry with no shipped template is a
packaging defect, and the completeness test in `test_core_docs.py` catches it
before release, which is where such a defect belongs. Failing the deploy in a
client would trade the plan tooling — `mkplan.bash`, the plan directory — for
the documentation about it, which is the worse of the two losses.

### Decision 6: ship what the daemon ENFORCES in the client's repo; link to what the client merely CONSULTS

The tempting roster test is "is this document generic enough to ship?", and it
is the wrong one — nearly all of them are. The test that actually separates
them is what the daemon DOES with the subject:

**In** — the daemon enforces a policy inside the client's own repository, so
the client must be able to read its canonical statement AND extend it with
their own rulings:

| Document                | Enforced by             | Named at                                                               |
| ----------------------- | ----------------------- | ---------------------------------------------------------------------- |
| `PlanWorkflow`          | `plan_workflow` handler | `plan_workflow.py:78`, `config/models.py:809`                          |
| `Worktree`              | `worktree_file_copy`    | `worktree_file_copy.py:57`                                             |
| `DocumentationStrategy` | the `docs_qa` engine    | `docs_qa/checks/rules_file_shape.py:172`, `skills/docs-qa/SKILL.md:14` |

`DocumentationStrategy` was not on the original list and is the sharpest case
of the four offenders: `rules_file_shape.py:172` names it in a runtime FINDING
message, unguarded, and `documentation.trees.agent`/`.human`/`.remote` are
per-project configuration — the daemon enforces a model whose canonical
statement no client has ever received.

**Out** — documents ABOUT the daemon. A client consults them; they do not
customise them, and a seeded copy would be a second version to keep in step:
`HANDLER_DEVELOPMENT`, `PROJECT_HANDLERS`, `DEBUGGING_HOOKS`, `SELF_INSTALL`,
`LLM-INSTALL`, `LLM-UPDATE`, `ARCHITECTURE`, `QA`.

**`DirectoryRoles` is out for a different reason and it is the one that set
the principle.** It looks like the same defect, but `directory_role_rules.py`
computes an install-mode-aware link that RESOLVES, and it records the warning
that seeding a document drags in its dependency graph. Deploying is not the
only correct fix — guarding (`plan_number_helper`) and repointing
(`directory_role_rules`) are equally valid ways to keep the promise.

**`PlanJournalling` is deferred, not dismissed.** It is already deployed, so
there is no missing-document bug, but it is seeded ONCE with no core/override
split, which strands every existing client on the version they were seeded
with — the freeze half of Decision 1. This repo's copy is currently
byte-identical to the shipped template, with no guard against that changing.
Folding it in is right, but its deploy location is plan-directory-relative
(`plan_dir.parent`), not docs-tree-relative, so the migration moves a working
deploy for any project with a non-default plan directory. That is a design
question of its own and belongs in its own plan.

### Decision 7: deploy to the path the CONFIG names, never a hardcoded one

Found by auditing this plan's own Phase 2 work, reproduced RED before fixing.
`deploy_core_docs` wrote to a hardcoded `CLAUDE/`, while
`plan_workflow.workflow_docs` — the path the handler QUOTES to the agent — is
per-project configuration. For a project whose docs tree is not `CLAUDE/`,
the document was created somewhere the reader is never sent: the original
defect with an extra step, and harder to see because the file does exist.

It also scattered markdown into a directory the daemon itself would refuse a
write to, since `markdown_organization` derives the allowed agent tree from
the same configuration.

The precedent was one line away in the same function. `plan_dir_name` is
threaded through `bootstrap_plan_workflow` as a parameter whose docstring says
it MUST be passed the configured value "so the bootstrap honours a project
that tracks plans elsewhere (single source of truth)". The fix applies that
rule to documents: the parent of `workflow_docs` is the docs directory, and
its filename is the override to seed — so a project that renamed the document
also gets the file it was promised. The other core documents have no config
key of their own and keep canonical names in that same directory.

### Decision 4: guidance must not name a document the daemon does not ensure

The four offenders share one root cause: a guidance string naming a client path
is written by hand, and nothing connects it to the deploy. Task 1.2's invariant
is the durable fix; the individual corrections are only its current instances.

## Success Criteria

- [ ] A fresh client-mode install produces a project where every doc path named
  in handler guidance or a config default exists.
- [ ] An upgrade refreshes core documents and leaves override documents
  byte-identical.
- [ ] This repo's own `CLAUDE/PlanWorkflow.md` is the override form, and a test
  fails if it stops referencing its core document.
- [ ] No shipped file cites a document that is not shipped.
- [ ] Full QA gate green.

## Delivery & Milestones

- <!-- milestone or delivery commit hash -->
