# Plan 00403: upstream issue reporting sop

**Status**: In Progress
**Created**: 2026-09-14
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

A client project's agent that meets daemon misbehaviour has no procedure. It
decides for itself whether the behaviour is a defect, whether the version
matters, what to include and what to leave out — and then files into a
repository that is **PUBLIC**
(`Edmonds-Commerce-Limited/claude-code-hooks-daemon`, confirmed via
`gh repo view`). Three things go wrong, and they are not equally bad.

A report that turns out to be configuration costs us triage. A report against a
version where the bug is already fixed costs us triage. **A report carrying the
client's private material into a public issue costs the CLIENT, and no history
rewrite reaches it.** That asymmetry orders this plan: the redaction guarantee
is built first and enforced by construction, and the quality gates are built on
top of it.

One finding reorders the work. Every existing route to a bug report already
leaks, and the documented one leaks worst — while `utils/secret_redaction.py`,
whose own threat model says its output "may be pasted into a bug report", is
called by no reporting path at all. So Phase 1 is not the SOP; it is stopping
the bleeding.

## The three leaking surfaces (verified, not assumed)

| Surface                                                                           | Emits                                                                                                      | Redaction | Where the docs send it                                                             |
| --------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | --------- | ---------------------------------------------------------------------------------- |
| `scripts/debug_info.py` — what `BUG_REPORTING.md` actually prescribes             | `.claude/hooks-daemon.yaml` verbatim (`:352-357`) and **`.claude/hooks-daemon.env` verbatim** (`:361-368`) | none      | "Paste the contents of the report file" into a GitHub issue                        |
| `bin/hooks-daemon bug-report` — the real CLI verb, which the guide never mentions | config verbatim (`cli.py:7167-7172`), `HOSTNAME`/`VIRTUAL_ENV` (`cli.py:7060-7068`), 100 log lines         | none      | —                                                                                  |
| `/hooks-daemon report` skill                                                      | LLM narrative + **session transcript** excerpts (`report.md:53-59`, which warns they are unredacted)       | none      | **the wrong GitHub org** — `anthropics/claude-code-hooks-daemon` (`report.md:204`) |

An `.env` file is a conventional home for credentials. Nothing stops a client
putting a token in `hooks-daemon.env`, and the guide gives no warning before
telling them to paste the result into a public issue. The wrong-org link is not
merely a broken URL: it points a client's diagnostics at a repository this
project does not control.

## Goals

- A client project **cannot** file an upstream issue carrying its own private
  material: the generator redacts by construction, and the filing gate refuses
  a body that did not come from it.
- A report proves it is a real defect before it is filed — configuration ruled
  out with reasons, the daemon source cited, the version question answered.
- One procedure, in one place, that the scattered client-facing instructions
  point at instead of each describing their own.
- Issues that arrive in a shape `issue-sdlc` can consume without re-deriving
  the context.

## Non-Goals

- Blocking issue filing in THIS repository. Owner ruling below: the gate binds
  client installs only. `issue-sdlc` files and edits issues here every hour and
  must not be slowed or carved around.
- Redacting Claude Code session transcripts in general. That gap is real and
  stated at `secret_redaction.py:15-20`; this plan keeps transcripts OUT of
  upstream reports rather than trying to make them safe to publish.
- Any change to what `issue-sdlc` does with an inbound issue.

## Owner rulings

| Question                            | Ruling                                                                                                                                                                                                       |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| How hard should the filing gate be? | **Block in client projects only.** A PreToolUse handler denies `gh issue create` against the daemon repo unless the body came from the daemon's own generator; it detects self-install and stands down here. |

## Design decisions

**Redaction is by construction, not by inspection.** A denylist of "things that
look sensitive" is the shape that fails — the same mistake as judging a path by
its text rather than by what it is, which produced three shipped false
positives in Plan 00401. So the report is assembled from fields the generator
controls, and the single place client content can enter is a reproduction that
must be minimal and synthetic.

**The minimal synthetic reproduction is the load-bearing rule.** A repro
authored against invented paths under `untracked/scratch/` cannot leak, removes
most of the surface in one move, and independently produces a better issue. A
bug that genuinely cannot be reproduced synthetically is still reportable — the
report says so explicitly and carries no client data instead.

**Daemon paths are ours; client paths are not.** Scrubbing keeps
`.claude/hooks-daemon/…` and `src/claude_code_hooks_daemon/…` intact, because
those ARE the substance, while rewriting the project root, `$HOME`, the git
remote, the branch name and the hostname to placeholders.

**Unverifiable claims become checkable artefacts.** The generator cannot know
whether the reporter really read the source. It CAN require the report to name
which config options were considered and why each is insufficient, and which
`file:line` was read. That is the move `MUST_EXCEED_COMMENT_SIZE_BECAUSE` and
the remote-docs provenance frontmatter already make here.

**The older-version rule is mechanical.** Installed versus latest; when older,
diff the release notes between them for the named subsystem. If it changed,
refuse and say upgrade first. If it did not, allow the report and record that
finding in it — the owner's rule, made checkable.

## Tasks

### Phase 1: Stop the bleeding

- [x] ✅ **Task 1.1**: Route `cmd_bug_report` through `secret_redaction`, and
  scrub the config dump, env-var capture and log lines before they reach disk.
- [x] ✅ **Task 1.2**: Same for `scripts/debug_info.py`, and stop emitting
  `.claude/hooks-daemon.env` verbatim — report which keys are SET, never their
  values.
- [x] ✅ **Task 1.5**: The captured log lines carry whole `hook_input` payloads
  — `session_name`, prompt ids, cwd, cost and rate-limit figures — which
  path-and-hostname scrubbing does not touch. Found by running the scrubbed
  command against this repository and reading the result rather than trusting
  the tests. A session NAME is free text a user wrote, so in a client project
  it can carry anything. Reduce what is captured, rather than scrubbing harder
  after the fact.
- [x] ✅ **Task 1.3**: Fix the wrong GitHub org in
  `.claude/skills/hooks-daemon/report.md`, and add a QA check that every GitHub
  URL in tracked docs names this repository, so it cannot recur.
- [x] ✅ **Task 1.4**: Remove "paste the contents of the report file" from
  `BUG_REPORTING.md` — the instruction that turns a local diagnostic into a
  public disclosure.

### Phase 2: The redacting generator

- [ ] ⬜ **Task 2.1**: Assemble a report from controlled fields; scrub project
  root, `$HOME`, git remote, branch and hostname to placeholders while
  preserving daemon-internal paths.
- [x] ✅ **Task 2.2**: Require a minimal synthetic reproduction; refuse one
  referencing any path outside `untracked/scratch/`, with the "cannot reproduce
  synthetically" escape that carries no client data. Daemon-internal paths are
  kept, because a report that could not cite the handler's source would be
  useless; absolute paths are refused whatever they point at, since the prefix
  is what identifies. Running the checker over realistic prose rather than the
  fixtures found a Windows drive path passing clean through a rule built
  entirely around `/`.
- [x] ✅ **Task 2.3**: Emit a provenance header (the remote-docs pattern) the
  filing gate can verify. It is tamper EVIDENCE, not authentication — nothing
  in-process can stop an agent that computes a digest itself, and the module
  says so rather than implying otherwise. What it catches is the failure that
  actually happens: a clean report generated, then edited to paste in a log
  excerpt, and filed.

### Phase 3: The verification gates

- [ ] ⬜ **Task 3.1**: Version currency — resolve installed versus latest; when
  older, scan the release notes between them for the named subsystem and refuse
  if it changed.
- [ ] ⬜ **Task 3.2**: Configuration ruled out — surface the named handler's
  options and require a stated reason per option.
- [ ] ⬜ **Task 3.3**: Source cited — require a `file:line` in the daemon source
  and verify it resolves in the installed version.

### Phase 4: The filing gate (client installs only)

- [ ] ⬜ **Task 4.1**: PreToolUse handler denying `gh issue create` against this
  repository unless `--body-file` names a generator-produced file with valid
  provenance; stands down in self-install. New rule ID, all seven registration
  gates.

### Phase 5: The issue form and the SOP

- [ ] ⬜ **Task 5.1**: `.github/ISSUE_TEMPLATE/` defect form mirroring the
  generator's fields, plus a `config.yml` pointing at the SOP.
- [ ] ⬜ **Task 5.2**: Rewrite `BUG_REPORTING.md` as the SOP's single home, and
  reconcile it with the CLI verb it currently does not mention.
- [ ] ⬜ **Task 5.3**: A skill entry point that drives the procedure.
- [ ] ⬜ **Task 5.4**: Point the scattered client-facing instructions
  (`src/CLAUDE.md`, `tests/CLAUDE.md`, `CLAUDE/LLM-INSTALL.md`,
  `CLAUDE/LLM-UPDATE.md`, `README.md`, `docs/guides/TROUBLESHOOTING.md`) at the
  one SOP instead of each describing its own.

## Success Criteria

- [ ] ⬜ No reporting path emits an unredacted client config, env file or
  hostname — asserted by a test per path, not by inspection.
- [ ] ⬜ A generated report containing a planted secret term is refused, and
  the refusal names only an index, never the term.
- [ ] ⬜ The filing gate denies a hand-written `gh issue create` against this
  repo from a client install, and allows one whose body the generator produced.
- [ ] ⬜ The gate stands down in this repository: `issue-sdlc` files and edits
  issues with no change in behaviour.
- [ ] ⬜ Every GitHub URL in tracked documentation names this repository.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Filed from an owner request for an SOP covering verification, version
  currency, structured collection and a hard no-leak guarantee. Dedupe scout
  checked 22 live plans: no overlap. Six completed plans supply building blocks
  (00072 bug-report CLI, 00201 secret-word redaction, 00371/00386/00389 version
  currency, 00330 skill-surface coherence); the verification gate is new.
