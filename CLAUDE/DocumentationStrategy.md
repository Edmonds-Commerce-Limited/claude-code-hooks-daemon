# Documentation Strategy

**Read first:** [CLAUDE/core/DocumentationStrategy.core.md](core/DocumentationStrategy.core.md) — the daemon's core
guidance for this subject, and the baseline everything below extends.

That file is DAEMON-owned: it is refreshed on every daemon upgrade and
overwritten wholesale, so never edit it and never copy its content here. It
carries the whole ruleset, the two-tree model and the enforcement reference.
This file holds only what is specific to this repository — the daemon's own
self-install source checkout — which for a documentation policy means the
rulings this project has granted itself: what it keeps outside the corpus, what
it treats as generated, and how far it has ratcheted enforcement.

## Self-install path convention

This repository runs the daemon in self-install mode (`self_install_mode: true`; see [CLAUDE/SELF_INSTALL.md](SELF_INSTALL.md)), so the wrapper lives at the workspace root rather than at the nested client path the core document shows. Wherever it writes `.claude/hooks-daemon/bin/hooks-daemon docs-qa …`, use:

```bash
bin/hooks-daemon docs-qa --sweep
```

The subcommands and flags are identical — only the prefix changes.

## Where the model lands in this repo

[CLAUDE/DirectoryRoles.md](DirectoryRoles.md) is the per-directory application
of the tree model here: which markdown belongs in each directory, and what
enforces it. Capture mechanics for the vendored tree — the provenance schema and
the fidelity rule — are in [CLAUDE/RemoteDocs.md](RemoteDocs.md).

One sub-folder `CLAUDE.md` in this repository is a registered module-local
canonical home rather than a routing table under R7d:
[.claude/ccy/CLAUDE.md](../.claude/ccy/CLAUDE.md), which owns the ccy
supervisor hot-reload contract.

## What this project keeps outside the corpus

Two categories are scope-excluded here — invisible to the corpus, not merely
capped at advisory severity:

- **The daemon's own shipped payload markdown under `src/`** — skills, guides
  and install templates, the core documents above included. These are ASSETS
  deployed to client projects, not documentation living in the wrong place, so
  asking for them to be promoted into a doc tree would be wrong. The exclusion
  is permanent and deliberate rather than legacy debt.
- **Frozen historical records** — versioned upgrade guides, superseded plan
  drafts and files that self-label as archived in their own name. Their links
  are a permanent record of what was true when written, so re-verifying them
  against current truth would report noise forever.

The globs and the full reasoning live in `.claude/hooks-daemon.yaml` under
`documentation.qa.scope_exclude_globs`, which is their source of truth.

## Deployed copies are generated, not authored

Self-install means source and deploy target are the same tree, so this repo's
`.claude/skills/`, `.claude/agents/` and shipped `.claude/rules/`
directory-role pointers are DEPLOYED COPIES of sources under `src/`, declared
in `documentation.qa.generated_docs` for that reason. Edit the source and
redeploy; hand-editing the deployed artefact silently diverges dogfood from
what ships, and the hand-edit advisory names the redeploy command for each.

## Adoption state

Every deterministic check runs at its advisory default here: nothing has been
ratcheted to `block`, and the grandfather allowlist is empty — standing
violations were fixed rather than allowlisted, and the exclusions this project
does keep are the scope exclusions above. Ratchet one check at a time via
`documentation.qa.check_modes`, following the core document's adoption
sequence.

The semantic half is live: this repo enables the `hooks-daemon-docs-qa` agent
(it ships disabled upstream) and dogfoods it through the `docs-qa` skill.

## Running the checks

The docs-QA sweep is **not** part of this project's QA suite — run it
explicitly with the CLI above. The suite itself is:

```bash
./scripts/qa/llm_qa.py all
```

`scripts/qa/run_all.sh` is the single source of truth for which checks it
contains; full QA policy is [CLAUDE/QA.md](QA.md).

## This repo implements the ruleset it obeys

Elsewhere this document would only describe configuration. Here the enforcement
is code: the check core is `src/claude_code_hooks_daemon/docs_qa/`, its three
handler surfaces are documented in
[docs/guides/HANDLER_REFERENCE.md](../docs/guides/HANDLER_REFERENCE.md), and the
agent and skill are shipped assets under `src/`. Changing what a check does is a
code change with tests, not a config edit — so a finding you disagree with is a
defect to fix upstream in this repo, not a rule to exempt yourself from.

Provenance: Plan 00284
([CLAUDE/Plan/Completed/00284-documentation-ssot-enforcement/PLAN.md](Plan/Completed/00284-documentation-ssot-enforcement/PLAN.md)),
whose review documents carry the evidence behind each rule.
