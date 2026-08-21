# Plan 00264: github comment size cap

**Status**: Not Started
**Created**: 2026-08-20
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A downstream project reports that agent sessions flooded its GitHub issues with
journal-grade content, and asks for a built-in PreToolUse handler — working name
`github_comment_size` — that caps the size of a GitHub issue/PR comment posted
through the `gh` CLI and redirects the content into the daemon's own plan
`JOURNAL/` and supporting-doc facilities. The full report is in
[FIELD-REPORT.md](FIELD-REPORT.md).

The incident is the evidence for the plan. One issue was filed and, by the time
the report was written the same day, carried a **44,467-character** "repo
research" comment posted almost immediately after creation, a
**22,398-character** "Research addendum", and a chain of correction-on-correction
comments. A second issue accumulated roughly twelve step-by-step narration
comments ("Dev run attempted — converge OK, verify failed, now fixed", "Reviews
complete", "Dev run GREEN"). The cost is borne by humans: management reads only
the issue, and neither ticket's actual state was findable any more. The repo
owner called it "a HUGE degradation". Every flooding comment was authored by the
developer account agents act under — interactive agent sessions, which is
exactly the surface this daemon governs.

The reporting project already applied the guidance remedy (a policy doc, a
workflow-prompt update, a CLAUDE.md section). Guidance is the mechanism that
already failed once here, which is the whole argument for a mechanical rule.
This plan builds that rule, and — equally important — records the parts of the
report's proposed design that are NOT yet settled, so the implementer decides
them on evidence rather than inheriting them.

## Goals

- Ship a PreToolUse handler that caps the body size of a GitHub issue/PR comment
  posted via the Bash tool, with a deny reason that names the measured size, the
  threshold, and the plan-workflow destination for the content.
- Cover the three write shapes the report enumerates: `gh issue comment`,
  `gh pr comment`, and `gh api` write-methods against comment endpoints.
- Make the handler configurable in the same shape as the existing `comment_size`
  handler, so a project can tune or disable it without a fork.
- Settle each open question below by measurement or by a recorded decision — not
  by inheriting the report's proposal unexamined.

## Non-Goals

- Retroactive cleanup of comments already posted to GitHub.
- Capping issue/PR **bodies** at creation (`gh issue create` / `gh pr create`).
  The report scopes v1 to comments because comments are the flooding vector; a
  body cap at a higher threshold is a possible follow-up.
- MCP comment tools (`mcp__github__create_issue_comment`) and CI workflow bots,
  which do not dispatch through this daemon.
- Any change to `gh_issue_comments` / `gh_pr_comments`, which govern READS.

## Context & Background

**Verified against the tree before filing:**

- No plan, handler, doc or test in this repository mentions a GitHub comment
  size cap. The only `gh issue comment` / `gh pr comment` strings anywhere in
  `src/` are in `sed_blocker`'s exemption for `gh` bodies that mention sed.
- The report's "natural sibling" claim is **half right, and the halves matter**.
  `gh_issue_comments` / `gh_pr_comments` are Bash-command handlers in the same
  GitHub family, but they govern READS (`gh issue view` must carry
  `--comments`) and have no size logic at all. `comment_size` has the size logic
  and the options shape worth copying, but it is a `Write`/`Edit` content
  handler for **code** comments, with grow/shrink/same-size tiering that has no
  analogue for a one-shot outbound post. So this handler inherits the
  command-matching idiom from one pair and the options vocabulary from the
  other, and shares implementation with neither.
- `gh` flag semantics were confirmed against the installed binary, because the
  short flags collide across subcommands:
  - `gh issue comment` / `gh pr comment`: `-b/--body`, `-F/--body-file`
    (`-` means stdin).
  - `gh api`: `-f/--raw-field` (string), `-F/--field` (typed; `@<path>` reads a
    file, `@-` reads stdin).
  - **`-F` therefore means `--body-file` on the comment subcommands and
    `--field` on `gh api`.** Extraction must be subcommand-aware; one shared
    `-F` regex across both shapes would misread. The report's rule 3 also lists
    `--field` among the inline forms, but `--field` is the long form of `-F` and
    is exactly the file-capable one — `--field body=@path` must be treated as a
    file read.

## DBF — what guard was missing

Core Standard 15 says the defect worth fixing is the guard that failed to catch
it. Three observations follow, and the last two are the uncomfortable ones.

**The missing guard**: the daemon inspects a great deal of outbound Bash but
nothing at all about what an agent PUBLISHES to GitHub. `sensitive_content`
makes the point by contrast — it checks git metadata surfaces (`git commit`,
`git tag`, branch names, `git config user.*`, `git merge -m`) via a
`_GIT_METADATA_WRITE_SUBCOMMANDS` allowlist, so a `gh` comment body is not a
candidate at all. A comment body is therefore unexamined for size **and** for
secret-list terms, and a GitHub comment is more public than most commits.
Whether the secret-term half belongs in this plan or in `sensitive_content` is
Open Question 7.

**The corollary that limits this plan's value**: a write-time PreToolUse guard
does not cover what is already posted. The 44,467-character comment is on GitHub
right now and no handler will ever see it. Standard 15's corollary says every
write-time rule needs a batch equivalent, and for content that has already left
the repository into a third-party service this project has no batch surface —
unlike `check-permissions --fix` or the plan-QA sweep, both of which can
re-examine what predates their rule. Say this plainly rather than implying the
handler closes the incident: it prevents recurrence, it does not remediate.

**A live instance of the same class, hit while filing this plan.** The field
report named the reporting organisation four times, and that name is entry 6 of
this project's `.claude/block-words.secret` list. Relocating the report into the
plan folder was a Bash `mv`, which no content guard inspects — so the blocked
term landed in a soon-to-be-tracked file with no block, no advisory and no
record. It was caught only because a subsequent `Write` of this PLAN.md quoted
the same name and `sensitive_content` denied THAT. The occurrences have been
redacted, but the lesson belongs in this plan's own subject matter: the Bash
file-write side door and the missing `gh` surface are the same defect wearing
two hats. Plan 00252 already tracks the "no guard inspects staged content for
secret-list terms" half; this is a second witness for it.

## Tasks

### Phase 1: Decide the open questions

- [ ] ⬜ **Task 1.1**: Resolve each item in "Open Questions" below, recording a
  Technical Decision for each with the measurement or reasoning behind it.
- [ ] ⬜ **Task 1.2**: Measure the fallback estimator against real command shapes
  before adopting it — see Open Question 1.

### Phase 2: TDD implementation

- [ ] ⬜ **Task 2.1**: Write failing tests for `matches()`: the three write
  shapes match; `gh issue view`, `gh pr view`, `gh issue create`,
  `gh pr create`, `gh api --paginate` list reads, and non-`gh` commands do
  not.
- [ ] ⬜ **Task 2.2**: Write failing tests for body-size extraction in
  precedence order: inline `--body`/`-b`; `--body-file`/`-F <path>` on the
  comment subcommands (stat the file, resolving relative paths against the
  hook input's cwd); `gh api` `-f`/`--raw-field` inline and
  `-F`/`--field body=@path` file reads. Cover the subcommand-dependent
  meaning of `-F` explicitly, with a test per subcommand.
- [ ] ⬜ **Task 2.3**: Write failing tests for the unjudgeable cases that must
  ALLOW: a missing body file, `-` / `@-` stdin, and a `shlex` parse failure.
- [ ] ⬜ **Task 2.4**: Write failing tests for the decision table: under
  threshold allows silently; over threshold with a declared escape hatch
  allows with context recording the reason; over threshold otherwise denies
  with a reason naming the measured size, the threshold, and the `JOURNAL/`
  remediation.
- [ ] ⬜ **Task 2.5**: Implement the handler against those tests, with named
  constants for every threshold and flag literal (Core Standard 9).
- [ ] ⬜ **Task 2.6**: Decide terminality deliberately and record why. Note
  `comment_size` is non-terminal **because** a terminal ALLOW ends the chain
  and silently disables every later handler — the defect Plan 00241 found
  and Plan 00242 is generalising. Any path here that returns ALLOW must not
  be terminal.

### Phase 3: Integration and configuration

- [ ] ⬜ **Task 3.1**: Register the handler id, priority and tags in
  `constants/`, and add it to the shipped config with its options block.
  Priority sits in the workflow band alongside the other GitHub handlers.
- [ ] ⬜ **Task 3.2**: Enable it in this project's own
  `.claude/hooks-daemon.yaml` and confirm the dogfooding config tests pass.
- [ ] ⬜ **Task 3.3**: Restart the daemon and verify `status` reports RUNNING;
  probe the live socket with a representative allowed and denied command.
- [ ] ⬜ **Task 3.4**: Add a `config-changes` manifest entry under
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/` so the option is surfaced on
  upgrade rather than shipping dormant.

### Phase 4: Guidance, docs and acceptance

- [ ] ⬜ **Task 4.1**: Implement `get_claude_md()`. A blocking handler needs a
  resident guidance body — the coverage test in
  `tests/integration/test_claude_md_guidance_coverage.py` enumerates every
  handler and fails unless each carries a verdict. State what is blocked,
  the remediation, and the escape hatch.
- [ ] ⬜ **Task 4.2**: Add a `#### <handler key>` section to
  `docs/guides/HANDLER_REFERENCE.md`. This is REQUIRED, not optional:
  `scripts/qa/check_handler_reference.py` fails the QA gate for any
  PreToolUse handler the generated registry records as BLOCKING or TERMINAL
  with no section.
- [ ] ⬜ **Task 4.3**: Implement `get_acceptance_tests()` covering an allowed
  small comment and a denied oversized one, using `echo`-wrapped commands so
  no test ever posts to a real repository.
- [ ] ⬜ **Task 4.4**: Run `./scripts/qa/llm_qa.py all` and fix every finding.

## Open Questions

These are unresolved. The report asserts answers to some of them; those
assertions are recorded as proposals, not decisions.

**1. Is the `len(command) − 150` fallback sound?** The report proposes that when
no parser can extract a body (heredoc, `$( )`), the handler estimate the size as
the command length minus about 150 characters. Two problems. First, it measures
the WHOLE Bash command, so a command whose length comes from anything else — a
long chain of `&&`, a loop posting several short comments, a long `--repo` or
path argument — is judged on length it did not spend on the body, and a false
DENY on a legitimate short comment is the failure that gets a handler disabled.
Second, `150` is a magic number under Core Standard 9 and needs a named constant
and a justification for its value. **Also check for an interaction**: Plan 00235
added a shared quoted-heredoc strip because a quoted heredoc body is literal
text bash never parses. That utility blanks precisely the bytes this handler
must MEASURE, so if the implementer reaches for the shared scanner, the fallback
silently reads zero. Measure the estimator against real command shapes before
adopting it; if it cannot be made safe, prefer a false negative to a false
positive and drop it.

**2. Does the escape-hatch name follow the convention? No.** Every hatch in the
tree is `MUST_<VERB>_..._BECAUSE`: `MUST_SCAN_ROOT_BECAUSE`,
`MUST_SQUASH_BECAUSE`, `MUST_STASH_BECAUSE`, `MUST_EXCEED_PLAN_SIZE_BECAUSE`,
`MUST_EXCEED_COMMENT_SIZE_BECAUSE`. The report's `MUST_LONG_COMMENT_BECAUSE` has
no verb and reads as an adjective. `MUST_POST_LONG_COMMENT_BECAUSE` or
`MUST_EXCEED_GITHUB_COMMENT_SIZE_BECAUSE` both fit; pick one and be consistent
with the sibling it most resembles.

**3. Should there be an agent-side escape hatch at all?** Plan 00259 declined
one for `artifact_publish_blocker` on the grounds that an agent which can type
its own justification has self-authorised an OUTWARD-FACING disclosure, and that
the hatches which do exist (`git_stash`, `ancestry_preserving_merge`) all govern
actions whose consequences stay inside the repository. Posting a GitHub comment
is outward-facing by exactly that test — it publishes to a place humans read and
cannot be un-read. This is a real tension with the report's proposal and must be
decided explicitly, not assumed.

**4. Should the default be `block` or `warn` on first ship?** The report
proposes `block`. The precedent cuts the other way: `plan_qa_commit_gate` ships
`warn` as a deliberate rollout ratchet, and Plan 00208 demoted three of five
planned blocking signals to advisory only after a whole-repo scan measured real
false positives. Given Open Question 1, a `warn`-first ship that gathers
evidence before the ratchet may be the safer path. Decide on evidence.

**5. What is the right threshold?** The report suggests `max_comment_chars: 3000` with a policy target around 1500. Neither figure is measured — they are
"policy target, block at 2x". A threshold in characters is also a poor proxy for
the actual complaint, which is comments no human will read; the remediation text
talks in **lines** ("a ≤20-line human summary"). Consider whether the limit
should be lines, characters, or both, mirroring `comment_size`'s two independent
signals.

**6. Is stdin a hole worth accepting?** `cat big.md | gh issue comment 5 -F -`
reads the body from stdin, which the handler cannot judge, so the design ALLOWs
it — and `cat` is whitelisted by `pipe_blocker`, so nothing else stops it
either. That is a clean bypass of the whole handler by an obvious alternative
spelling. Decide whether to accept it as a documented limit (and say so in
`get_claude_md()`, since undocumented holes teach agents the wrong lesson) or to
deny an unjudgeable stdin body on a comment-write shape.

**7. Does the secret-term gap belong here?** The DBF section notes a `gh`
comment body is checked by `sensitive_content` for nothing at all — a blocked
term can reach a public GitHub comment unexamined. That is arguably a more
serious defect than size. Decide whether to fix it in this plan, fold it into
Plan 00252, or file it separately — but do not leave it unrecorded.

## Success Criteria

- [ ] Every open question above has a recorded Technical Decision.
- [ ] The three write shapes are blocked over threshold and the read/create
  shapes are untouched, proven by tests.
- [ ] Unjudgeable bodies never produce a false DENY.
- [ ] `get_claude_md()` returns a guidance body and the coverage test passes.
- [ ] `docs/guides/HANDLER_REFERENCE.md` has a section for the handler and
  `check_handler_reference.py` passes.
- [ ] `get_acceptance_tests()` returns tests that appear in a generated playbook
  and pass.
- [ ] `./scripts/qa/llm_qa.py all` is fully green.
- [ ] The daemon restarts and reports RUNNING with the handler loaded, and a
  live socket probe confirms the deny and the allow.
- [ ] A `config-changes` manifest entry exists so the option is surfaced on
  upgrade.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). The activity log lives in JOURNAL/. -->

- Filed from [FIELD-REPORT.md](FIELD-REPORT.md); the dedupe scout checked 35
  live plans and found no overlap.
