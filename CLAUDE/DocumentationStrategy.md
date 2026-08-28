# Documentation Strategy — one canonical home per fact

**This file is the canonical home for the project's documentation-SSoT rules.**
Every other statement of these rules anywhere in the repository is a pointer to
this file. Provenance: Plan 00284
(`CLAUDE/Plan/Completed/00284-documentation-ssot-enforcement/`), whose review
documents carry the evidence behind each rule.

## The model

There are exactly **two documentation trees**, split by AUDIENCE:

| Tree                       | Audience | Register                                                                         |
| -------------------------- | -------- | -------------------------------------------------------------------------------- |
| **Agent tree** (`CLAUDE/`) | agents   | Verbose, information-dense. OWNS the depth for every fact.                       |
| **Human tree** (`docs/`)   | humans   | Terse, digestible, friendly prose. MAY point into the agent tree for full depth. |

Tree NAMES are per-project configuration; the SPLIT itself is not optional —
when SSoT enforcement is enabled it enforces the split. Humans may read the
agent tree, but should expect its register. The plan directory (`CLAUDE/Plan/`)
is a subdirectory of the agent tree: the plan system is primarily for agents.

Every other surface — `.claude/rules/`, `.claude/skills/`, `.claude/agents/`,
sub-folder `CLAUDE.md` files, code comments, GitHub issues/PRs, plan folders —
**POINTS at canonical docs; it never duplicates them.**

## The rules

**R1 — One canonical home per fact.** Every durable fact has exactly one file
that owns it; all other statements of it are pointers (R4) or tracked quotes
(R4b). N copies makes every change a graph traversal nobody performs.

**R2 — The canonical agent tree is configured, defaulting to `CLAUDE/`.**
Durable agent-facing truth lives there in clearly-named files with logical
sections. Facts about a code module MAY instead live in that module's
REGISTERED sub-`CLAUDE.md` (R7d), which then IS the canonical home for them.

**R3 — Audience split.** As above. A human-tree file that restates agent-tree
content at length is a violation; summary + link is the intended shape. The
agent tree always owns the depth; only the tree names are configurable.

**R4 — The pointer test (what a pointer may contain).** A compliant pointer may
contain: (a) up to ~3 sentences of orientation prose saying what the target
covers and why the reader would follow it; (b) surface-specific APPLICATION
notes not stated in the target (how this role/path uses the fact); (c) the
link. It may NOT contain: copied or reconstructed **tables**; **fenced
command/code blocks** that appear in the target (unless quoted per R4b);
**numbered procedures**; **enumerated lists** duplicating the target's;
restated **normative sentences** carrying the target's rule; or **derived
facts** (R5). The boundary is CONTENT CLASS, not sentence count — evidence
shows structured facts are what drifts harmfully; prose paraphrase mostly does
not.

**R4a — Safety-critical restatement exception.** A rule whose loss is dangerous
(e.g. release human-gating) may be restated in compressed prose at the point of
use, but must cite the canonical doc and still may not restate its
tables/steps/counts. Claim the exception in-file with an HTML comment marker so
it is auditable.

**R4b — The `ssot-quote` mechanism.** A small verbatim excerpt MAY repeat
anywhere IF wrapped in metadata naming its source (file + heading/marker
anchor):

```markdown
<!-- ssot-quote: CLAUDE/SomeDoc.md#some-anchor -->
(verbatim excerpt)
<!-- /ssot-quote -->
```

This turns deliberate repetition into TRACKED quotation: the checker verifies
each quote against its source span (normalised for formatting) and reports
drift the moment the canonical copy changes. Use it where inline text genuinely
serves the reader better than a link — e.g. a short verification snippet
repeated at several points of use. Anchors are headings/markers, never line
numbers.

**R5 — Derived facts are stated only by their source.** Counts, enumerated
lists with a generator, step totals, version numbers, file/handler rosters:
stated only in the file/script/registry that produces them, or in a generated
doc (R10). Everywhere else: "see X, the single source of truth for the list".
This project has twice invented this rule in incident response (the QA-check
count, the playbook test count); it is now law.

**R6 — Links are plain and resolve.** Root-relative (or verified-relative)
markdown links; no case-mismatched paths; no links to files or anchors that do
not exist. No `@`-imports outside the deliberate resident set in root
`CLAUDE.md` — `@`-imports re-inline eagerly and defeat progressive disclosure.

**R7 — Satellite surface contracts.**

- **(a) `.claude/rules/*.md` — POINTERS ONLY (firm).** Frontmatter
  (`paths:` + `description`) + a trigger statement + the rule in ≤2 imperative
  lines + link(s) to the agent tree or a registered `CLAUDE.md`. No fences, no
  tables, no numbered procedures, no quotes. If the substance has no canonical
  home yet, CREATE THE HOME FIRST, then thin the rules file to a pointer.
- **(b) `.claude/skills/`** — thin intent-matched shims that point (see
  `.claude/skills/CLAUDE.md`, the skills charter). Invocation mechanics are the
  skill's own content; procedure bodies are not.
- **(c) `.claude/agents/*.md`** — role framing + role-unique behavioural
  instruction + pointers. No engineering-principle restatements, no code
  skeletons, no remediation cookbooks. `.claude/agents/CLAUDE.md` is the agents
  charter mirroring the skills one.
- **(d) sub-folder `CLAUDE.md`** — either a pure routing table (≤ ~15 lines) or
  a REGISTERED module-local canonical home. The **outside-reader test** decides
  content: it belongs iff its intended reader is an agent about to edit files
  in THAT subtree and the content is meaningless without the subtree.
  Qualifying: edit guards; module-local invariants and concurrency contracts;
  local build/test commands; editing gotchas; local conformance walkthroughs; a
  tiny generated index. Disqualifying: repo-wide mandates; procedures for
  actors elsewhere; restated derived facts; hand-written API mirrors of the
  module's own code; governance/principles recaps. Registration is a config
  act; unregistered files carry a routing budget, registered ones size tiers
  (grow-only blocking). Prose indexes with per-file descriptions are forbidden
  — generate them or delete them; they rot fastest.
- **(e) code comments** — current-state rationale local to the code. Durable
  knowledge a reader OUTSIDE the file would need goes to a doc, with the
  comment pointing at it. A verbose comment block IS documentation and is
  cross-checked as such by the docs-qa agent; `comment_changelog` and
  `comment_size` remain the mechanical backstops. No deterministic
  "knowledge-in-comment" blocker exists — the discriminator is semantic.
- **(f) GitHub issues / PR bodies** — point, don't restate. Policy-first;
  enforcement is at most a weak advisory on `gh` invocations.

**R8 — Plan folders are a drafting ground, not a home.** Docs may be created
and iterated inside a plan folder. At terminal-status flip, every supporting
doc gets an explicit disposition recorded in the closing journal entry:
**promote** (canonical content moves into the doc trees; a stub pointer stays
behind), **historical** (the default for dated snapshots — archive immutability
applies, never retro-edited), or **delete**. The Plan Completion Checklist
carries this step.

**R9 — Plan citations are provenance, not storage.** A canonical doc may cite
`Plan NNNNN` (with a path) as history; current guidance the reader needs may
not exist ONLY behind a plan reference.

**R10 — Generated docs are compliant SSoT; declare them.** A doc generated from
code is generation, not duplication — the source is the code. Every generated
doc is declared in a manifest (config: globs + generator command), pre-seeded
with the daemon's artifacts (the `<hooksdaemon>` CLAUDE.md block,
`.claude/HOOKS-DAEMON.md`, generated playbooks). Manifest entries are exempt
from duplication checks; hand-edits to them draw an advisory naming the source
and regenerate command.

**R11 — This policy obeys itself.** This file is the canonical home; root
`CLAUDE.md` carries a pointer plus the shortest possible resident summary;
handler guidance summarises and points (and is generated, hence R10-exempt).

**R12 — Grandfathering.** Violations standing at adoption time go into a
file-scoped config allowlist and only ever advise. Blocking follows the
`plan-doc-size` tiering philosophy: only an edit that makes things WORSE (a new
duplicate block, a new dead link, growth of an over-budget surface) can block;
shrinking is silent; unchanged-but-bad advises.

**R13 — Two enforcement instruments, cleanly divided.** DETERMINISTIC checks
(edit-time handler, bulk `docs-qa` CLI, session sweep — the `docs_qa` package)
enforce only the mechanically-checkable subset: exact/near-exact copies, stale
pointers, quote-vs-source drift, structural placement, manifests and budgets.
The SEMANTIC remainder — conflicting truths, paraphrase drift, scattered truth
with no canonical home, verbose comment blocks — belongs to the
**`hooks-daemon-docs-qa` agent**, which reports with citations and never edits
or blocks. No deterministic check may attempt a semantic judgement. All
deterministic checks ship advisory (`warn`); `block` is a per-check,
per-project ratchet.

## Enforcement status

Enforcement shipped in Plan 00284
(`CLAUDE/Plan/Completed/00284-documentation-ssot-enforcement/PLAN.md`): the
`docs_qa` check core and its three surfaces (`docs_qa_edit`,
`docs_qa_commit_gate`, `docs_qa_sweep` — see
[docs/guides/HANDLER_REFERENCE.md](../docs/guides/HANDLER_REFERENCE.md)), the
`ssot-quote` verifier, the module-doc registry, the generated-doc manifest,
the `hooks-daemon-docs-qa` agent, and the docs-qa skill (a thin shim that
dispatches the agent, bundling its deterministic finder scripts). This
document remains binding as POLICY regardless: follow the rules when writing
or moving documentation, and treat violations you encounter as defects worth
fixing — the deterministic checks catch a mechanically-checkable subset, not
the whole ruleset.
