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

Measured per surface in [LEAK-INVENTORY.md](LEAK-INVENTORY.md): what each one
emits, whether anything redacts it, and where the documentation sends it. All
three leaked, none redacted, and one pointed a client's diagnostics at a GitHub
org this project does not control.

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

Five, each with what it defends against, in
[DECISIONS.md](DECISIONS.md): redaction by construction rather than by
inspection; the minimal synthetic reproduction as the load-bearing rule; daemon
paths kept while client paths go; unverifiable claims turned into checkable
artefacts; and the older-version rule made mechanical.

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

- [x] ✅ **Task 2.1**: Assemble a report from controlled fields; scrub project
  root, `$HOME`, git remote, branch and hostname to placeholders while
  preserving daemon-internal paths. `ReportFields` is the entire input surface,
  so the hostname is never collected rather than scrubbed out, and a test
  asserts each banned field name is absent from the class — output can be
  scrubbed into looking clean, a field never collected cannot come back.
  Scrubbing runs before the digest, so the provenance header vouches for the
  bytes actually filed. Shipped as `hooks-daemon issue-report --fields`, which
  refuses with EVERY reason at once and leaves no file behind when it does.
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

- [x] ✅ **Task 3.1**: Version currency — resolve installed versus latest; when
  older, scan the release notes between them for the named subsystem and refuse
  if it changed. Two asymmetries are deliberate: being AHEAD of the newest tag
  is fine (a contributor on the default branch is not behind), and being unable
  to check is a refusal rather than a pass — an unchecked install and a
  checked-and-clean one must never render the same. Wired into the CLI verb
  with `--latest`; the lookup is an INPUT rather than a network call, because a
  report generator that needed a working remote would fail exactly when the
  daemon is misbehaving, which is when it gets run.
- [x] ✅ **Task 3.2**: Configuration ruled out — delivered as the stated-reason
  gate plus a handler-NAME check, and NOT as an option list. The task as worded
  rests on a premise that does not hold: a handler's options are not declared in
  any schema, they are whatever the project's config supplies at registration
  time, so there is nothing to enumerate and a generated list that LOOKED
  authoritative would be worse than none, because a reporter would trust it. The
  refusal therefore points at `hooks-daemon explain-handler <name>`, which is the
  authoritative source, and says so. What does have teeth is the name: 127
  handler config keys are machine-readable from `HandlerID`, so a report naming a
  handler this daemon does not have is refused with the nearest real names —
  that reporter has usually been debugging something other than what they think,
  which is worth catching before it becomes a public issue rather than after. The
  stated-reason half is unchanged and already enforced: `assemble_report` refuses
  a report whose `config_considered` is empty, and refuses an entry that names an
  option without saying why it is insufficient.
- [x] ✅ **Task 3.3**: Source cited — require a `file:line` in the daemon source
  and verify it resolves in the installed version. A citation that does not
  resolve means the reporter read a different version, a fork, or nothing, and
  all three change how the rest of the report should be read. It is a lower
  bound, not a proof — a resolving line proves the line exists, not that
  anybody understood it — and the module says so rather than implying more.
  Containment is checked after resolution, because
  `src/claude_code_hooks_daemon/../../../etc/passwd` satisfies the prefix test
  as text while pointing outside the tree.

### Phase 4: The filing gate (client installs only)

- [x] ✅ **Task 4.1**: `issue_filing_gate` (PreToolUse, priority 14, rule
  `R-UPSTREAM-ISSUE-UNVERIFIED-BODY`). Priority 14 is the band
  `sensitive_content`, `artifact_publish_blocker` and `project_containment`
  already occupy, for the same reason: all of them guard content LEAVING the
  project. Three boundaries decide whether it is usable rather than merely
  correct, and each has a test that fails if it is traded away. It stands down
  in self-install, because `issue-sdlc` files issues here hourly and a gate
  that fired would break the delivery loop on its first tick — but an
  UNRESOLVABLE install mode is answered as "client", so the failure direction
  is a clear refusal rather than a silent disclosure. It engages on the
  repository a command TARGETS, read from `--repo`/`-R` in the same shell
  segment or a `GH_REPO` assignment, never on this repo's name appearing in the
  text: a client filing "upgrade the hooks daemon" on their own backlog is the
  false positive that would get the handler switched off. And `gh issue comment` is deliberately uncovered — no generator produces a comment body, so
  requiring provenance on a follow-up would make the tracker unusable for the
  reporter this plan exists to help, while `sensitive_content` already scans
  one for secret terms. Respellings are covered through
  `compile_command_name_pattern` rather than by literals, with both directions
  in `test_blocking_handler_evasion.py`. Registered across all eight surfaces:
  `HandlerID`, `Priority`, `RuleID`, the module, `.claude/hooks-daemon.yaml`,
  `init_config.py`'s template, `hooks-daemon.yaml.example` (the one CI catches
  and a local run does not) and `HANDLER_REFERENCE.md`.

### Phase 5: The issue form and the SOP

- [x] ✅ **Task 5.1**: `1-defect.yml` mirrors the generator's fields,
  `2-other.yml` takes free text, and `config.yml` turns blank issues OFF. That
  switch is the load-bearing one: the forms are the only place the redaction
  rule reaches someone filing from a browser, and a blank-issue route past them
  would nullify it for exactly that population. It costs nobody a way in only
  because `2-other.yml` asks for no structure at all — a question that has to
  be dressed up as a bug report is a question nobody asks. The field set is
  asserted against `ReportFields` rather than a list written in the test, with
  every non-asked field carrying its reason, so a field added to the generator
  and forgotten in the form fails. Nothing else would notice: no other test
  reads `.github/`, and `rg` skips it.
- [x] ✅ **Task 5.2**: `BUG_REPORTING.md` rewritten as the SOP: the asymmetry
  first, then establish-it-is-a-defect, generate, read, file. Its
  troubleshooting half MOVED to `TROUBLESHOOTING.md` rather than being deleted
  — the one entry that guide lacked ("status says NOT RUNNING but hooks work")
  was added there in the same commit. The filing snippet is no longer restated:
  the generator prints the exact command with the real timestamped filename, so
  duplicating it here would be both redundant and untypable.
- [x] ✅ **Task 5.3**: `issue-report.md` in the bundled `hooks-daemon` skill,
  routed in `SKILL.md` and deployed via `deploy_skills`. It is `cat`-ed rather
  than forwarded to the CLI verb of the same name: that verb takes a `--fields`
  JSON file which is the OUTPUT of the first two steps, so forwarding would run
  the procedure backwards. Its cross-tree pointers are spelled out rather than
  linked, because the file is COPIED into every install and no single relative
  link is correct from both here and a client's `.claude/skills/`.
- [x] ✅ **Task 5.4**: Every site repointed, and one of them was actively
  wrong rather than merely scattered. `LLM-INSTALL.md`'s `debug-report-snippet`
  said "attach it to any bug report" — the instruction Phase 1 diagnosed,
  still live, and quoted verbatim into `LLM-UPDATE.md` by an `ssot-quote`, so
  it shipped twice. `TROUBLESHOOTING.md` asked for the config file "with any
  sensitive values removed", which is the check that fails. Both now say what
  those outputs are: local diagnostics for the person who ran them.

## Success Criteria

- [x] ✅ No reporting path emits an unredacted client config, env file or
  hostname — asserted by a test per path, not by inspection. The env file is no
  longer reproduced at all (keys only); paths, `$HOME`, the git remote and the
  hostname are placeholders in both generators; the log window carries the
  daemon's own format strings rather than the payloads it interpolated. The
  config file is still reproduced in full, scrubbed — deliberate, because
  ruling configuration out is the first thing the SOP asks for, and narrowing
  it to controlled fields is Task 2.1's remaining half.
- [x] ✅ A generated report containing a planted declared term is refused, and
  the refusal names only an index, never the term. Refused rather than
  REDACTED, which is the opposite of what `scrub_report` does and deliberately
  so: the reporter is still at the keyboard, the sentence is theirs to rewrite,
  and a silent redaction teaches them nothing while leaving prose that reads as
  nonsense. Verified live against a real `build_report` call — one problem, an
  empty document, and neither the problems nor the document carrying the term.
- [x] ✅ The filing gate denies a hand-written `gh issue create` against this
  repo from a client install, and allows one whose body the generator produced.
  Verified live against a REAL generated document rather than a fixture: as
  printed → allow, inline body → deny, after an edit → deny, restored → allow.
- [x] ✅ The gate stands down in this repository: it resolves self-install from
  `ProjectContext` and never engages here, so `issue-sdlc` is untouched. The
  live check above had to force `self_install_reader` to False to see any
  verdict at all, which is that stand-down demonstrating itself.
- [x] ✅ Every GitHub URL in tracked documentation names this repository —
  enforced by the `github_urls` QA gate, which walks the tree itself rather
  than using `rg`, because `rg` skips hidden directories and that is exactly
  where the worst instance was hiding.
- [ ] ⬜ Full QA passes and CI is green.

## Delivery & Milestones

- Filed from an owner request for an SOP covering verification, version
  currency, structured collection and a hard no-leak guarantee. Dedupe scout
  checked 22 live plans: no overlap. Six completed plans supply building blocks
  (00072 bug-report CLI, 00201 secret-word redaction, 00371/00386/00389 version
  currency, 00330 skill-surface coherence); the verification gate is new.
- **Three defects found by USING the finished thing, none of which a passing
  test suite would have surfaced.** Each has a regression test now:
  - The generator printed `gh issue create --body-file <report>` with no
    `--repo`. In a self-install that is correct and invisible; in a CLIENT
    project — the only place the generator matters — `gh` takes the target from
    the working directory, so the printed remedy files a hooks-daemon defect on
    the CLIENT'S OWN tracker, and the filing gate never engages because it
    judges the repository a command targets. Both halves fail in the same
    direction, and only where nobody runs it by hand. `issue_report/upstream.py`
    now holds the slug and builds the command, so the printed remedy and the
    gate's comparison cannot drift.
  - `assemble_report` called `scrub_report` without the term list, so the free
    text a reporter TYPES was the one surface with no backstop — and it is the
    only surface the "collect nothing sensitive" design cannot reach.
  - `bin/hooks-daemon --version` does not exist, and three documents made it a
    verification step. Recorded as Plan 00405 N4.
- The pattern across all three: the generator is correct in the environment it
  is developed in and wrong in the one it ships to. Running it was the only
  thing that showed that, because every test runs in the developing one.
