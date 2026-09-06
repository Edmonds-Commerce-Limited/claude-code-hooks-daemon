# Plan 00334 — Technical Decisions

Extracted from `PLAN.md` (which crossed the plan-doc-size advisory) so the plan
document stays lean while the reasoning stays durable. Each decision records
what was chosen, what was rejected, and why — three of them were reversals of
this plan's own earlier work, found by auditing it rather than by a test
failing.

## Decision 1: the core document is DAEMON-owned, the override is CLIENT-owned

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

## Decision 2: the core document is DEPLOYED into the client, not referenced in the vendored clone

A client install already contains this entire repository at
`.claude/hooks-daemon/`, so the core document could be referenced there instead
of copied. Rejected: that path differs between client mode and self-install
mode, where the daemon root IS the project root. `utils/cli_command` documents
at length what that difference costs — it shipped a documented command that
expanded to `-m: command not found`, and agents concluded the package was not
installed and tried to "repair" working installations.

Deploying a copy makes one path correct in both modes. `directory_role_rules.py`
chose the other option for `DirectoryRoles.md`; this plan does not follow it.

## Decision 3: a markdown link, not an `@`-import — and the read is VERIFIED

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

Two shipped templates were found still instructing clients to `@`-reference
their core, describing a seed that does not exist. Corrected: a template that
contradicts the seeder teaches every client the wrong thing.

## Decision 4: guidance must not name a document the daemon does not ensure

The four offenders share one root cause: a guidance string naming a client path
is written by hand, and nothing connects it to the deploy. Task 1.2's invariant
is the durable fix; the individual corrections are only its current instances.

Deploying is not the only correct remedy. Guarding the reference with an
existence check (`plan_number_helper`) and repointing it at a path that does
resolve (`directory_role_rules`) keep the promise just as well. Which remedy
fits follows from Decision 6.

## Decision 5: a missing bundled template does not fail a client's install

It fails the BUILD instead. A manifest entry with no shipped template is a
packaging defect, and the completeness test in `test_core_docs.py` catches it
before release, which is where such a defect belongs. Failing the deploy in a
client would trade the plan tooling — `mkplan.bash`, the plan directory — for
the documentation about it, which is the worse of the two losses.

## Decision 6: ship what the daemon ENFORCES in the client's repo; link to what the client merely CONSULTS

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
`LLM-INSTALL`, `LLM-UPDATE`, `ARCHITECTURE`, `QA`. Their citations are fixed by
repointing instead (Task 4.5).

**`DirectoryRoles` is out for a different reason and it is the one that set
the principle.** It looks like the same defect, but `directory_role_rules.py`
computes an install-mode-aware link that RESOLVES, and it records the warning
that seeding a document drags in its dependency graph.

**`PlanJournalling` is deferred, not dismissed.** It is already deployed, so
there is no missing-document bug, but it is seeded ONCE with no core/override
split, which strands every existing client on the version they were seeded
with — the freeze half of Decision 1. This repo's copy is currently
byte-identical to the shipped template, with no guard against that changing.
Folding it in is right, but its deploy location is plan-directory-relative
(`plan_dir.parent`), not docs-tree-relative, so the migration moves a working
deploy for any project with a non-default plan directory. That is a design
question of its own and belongs in its own plan.

## Decision 7: deploy to the path the CONFIG names, never a hardcoded one

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

Fixing only the deploy would have RELOCATED the inconsistency rather than
removed it — config would agree with the deploy and disagree with the handler.
So `workflow_docs` became a `ProjectLayout` axis (defaulted and last, per that
facade's own documented additive convention) and the handler quotes what it
finds there.

## Decision 8: gate each document on the subsystem that NAMES it

Hanging every core document off `bootstrap_plan_workflow` was the obvious
place — the reported client had the plan workflow on, and the fix worked for
them. It was still wrong, and the reason is one line of config:
`plan_workflow.enabled` defaults to **False**. It is opt-in.

So a stock install deployed nothing at all, while `worktree_file_copy` — a
safety handler in the default profile — went on naming `CLAUDE/Worktree.md` in
its BLOCKING rule text. The plan would have fixed the reported instance and
left the class it was written to remove.

Each document now carries the switch that makes its own guidance reachable,
resolved at `deploy_core_docs_if_enabled` — a decision site of its own,
mirroring `deploy_plan_workflow_if_enabled`, wired into the installer and both
upgrade paths:

| Document                | Gate                    | Because the naming surface is                                 |
| ----------------------- | ----------------------- | ------------------------------------------------------------- |
| `PlanWorkflow`          | `plan_workflow.enabled` | inert while the workflow is off                               |
| `Worktree`              | always                  | a rule text built in `__init__` with no config in hand        |
| `DocumentationStrategy` | `documentation.enabled` | a `docs_qa` runtime finding, independent of the plan workflow |

The gate is the subsystem that QUOTES the path, not the one that happens to
install nearby. That is the only gate that means anything: the promise is made
by the surface that names the document, so that surface decides whether it has
to be kept.

## Decision 9: a cross-subsystem citation is the shape that breaks

Each core document deploys under its OWN gate, and the shipped files that cite
them deploy under gates of their own — `agents.docs_qa.enabled` for the docs-QA
agent, nothing at all for a skill. So the invariant is not "is this document
shipped?" but **does the citing file's gate imply the cited document's gate?**

Two files got that wrong, and both were on this plan's original list:

| Citing file               | Its gate                 | Cited                             | That document's gate    |
| ------------------------- | ------------------------ | --------------------------------- | ----------------------- |
| `hooks-daemon-docs-qa.md` | `agents.docs_qa.enabled` | `CLAUDE/PlanWorkflow.md`          | `plan_workflow.enabled` |
| `skills/docs-qa/SKILL.md` | none (always deployed)   | `CLAUDE/DocumentationStrategy.md` | `documentation.enabled` |

Enable the docs-QA agent without the plan workflow and it points at nothing —
the reported defect, reproduced inside the fix for it.

Both now state the condition in prose, and the agent states the rule it needs
INLINE rather than depending on a document that may be absent. A cited document
is supporting depth; a rule the reader must apply cannot live behind a gate the
reader may not have switched on.

The whole class was then audited by hand, since the scanner cannot see it. The
shipped trees carry **13** citations of a gated document: **8** come from a
file sharing that document's gate (a plan-workflow asset naming
`PlanJournalling`, a core document naming its own override), **1** is a config
example rather than a citation, and **4** cross a gate boundary:

| Citing file               | Its gate                 | Cites                   | Conditional?                         |
| ------------------------- | ------------------------ | ----------------------- | ------------------------------------ |
| `hooks-daemon-docs-qa.md` | `agents.docs_qa.enabled` | `DocumentationStrategy` | yes — "if it exists in this project" |
| `hooks-daemon-docs-qa.md` | `agents.docs_qa.enabled` | `PlanWorkflow`          | fixed here                           |
| `skills/docs-qa/SKILL.md` | none (always)            | `DocumentationStrategy` | fixed here                           |
| `Worktree.core.md`        | none (always)            | `PlanWorkflow`          | yes — "if this project uses it"      |

Two were already conditional; the two fixed here were not. That the count is
small is what makes the manual audit viable — and what makes it worth redoing
whenever a shipped file gains a citation.

Enforcing this in the scanner was attempted and REVERTED. The approximation —
a conditionally-deployed document needs a conditionally-worded citation — fired
on seven legitimate cases (a plan-workflow asset naming `PlanJournalling`, a
core document naming its own override) because those share the gate of what
they cite. The true rule needs a gate recorded for every shipped skill, agent
and template, which is a modelling exercise of its own. A check that cries wolf
is turned off, so the scanner keeps the coarser rule and the gap is written
into its module docstring with the shape to watch for.

## The pattern worth naming: six defects, one caught by a test

Decisions 7, 8 and 9, the two `@`-reference templates, and the docs-directory
permission bug were all found by AUDITING the work, not by anything going red.
Each had passing tests at the moment it was wrong, and the reason is the same
in every case: **the test encoded the same assumption the code did.**

- The deploy hardcoded `CLAUDE/`, and so did the test that checked it.
- The gate hung off `plan_workflow.enabled`, and every test enabled it.
- The permission test asserted the child directory's mode and inherited the
  runner's umask for the parent, so the parent's 0700 never showed.
- The genericisation check read the seeded stub — a file that could not carry
  the defect — rather than the template that could.
- The citation scanner treated every shipped document as unconditionally
  present, so it could not see a citation that crosses a gate boundary — the
  countermeasure built in Task 4.6 reproduced the pattern it was built to break.

That last one is the honest measure of how strong the pull is. Only ONE defect
in this plan was caught by a check rather than by reading: the error-hiding
exclusions that drifted when an insertion moved the lines beneath them — and
that check succeeded precisely because it was written by someone else, against
a hazard they had already been bitten by.

A test written from the same understanding as the implementation confirms the
understanding, not the behaviour. The three durable countermeasures adopted
here are all attempts to break that symmetry: pin the environment rather than
inherit it (the umask fixture), assert against the artefact that can actually
be wrong (the bundled template, not the stub), and SCAN rather than list
(`test_shipped_asset_citations.py`, which found 21 citations no one had
enumerated, then found three more the manual sweep missed).

## Known residuals, stated rather than left to be discovered

The deploy follows configuration; two guidance STRINGS still do not, and both
are correct for the default configuration and stale only for a project that
moved its docs tree:

- `worktree_file_copy.py` builds its `Rule` in `__init__`, before any layout is
  injected, so its `CLAUDE/Worktree.md` cannot read config without restructuring
  how rule text is produced — which also feeds the generated rule table.
- `docs_qa/checks/rules_file_shape.py` hardcodes `CLAUDE/DocumentationStrategy.md`
  in a finding message.

Neither is a missing document any more; both are a stale citation, which is a
narrower fault than the one this plan set out to fix. Fixing them properly means
making rule text configuration-aware in general, which is its own change.

`PlanJournalling` remains as recorded in Decision 6: deployed and therefore not
an instance of this defect, but seeded once and so frozen for existing clients.
