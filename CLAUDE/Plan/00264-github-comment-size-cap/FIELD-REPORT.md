# Feature report: GitHub issues are for humans — verbose content belongs in plans, never in comment floods

**For**: claude-code-hooks-daemon maintainers
**From**: a downstream `ai-tools` project session, 2026-08-20
**Note**: the reporting organisation's name appeared four times in this
report and has been redacted as `<client>` — it is entry 6 of this
project's `.claude/block-words.secret` list, so it must not enter tracked
source. See Plan 00264's report-back for how it got this far.
**Ask**: a built-in PreToolUse handler (working name `github_comment_size`)
that blocks agent sessions from posting oversized GitHub issue/PR
comments, steering the content into the daemon's plan system instead.

---

## The incident

Agent sessions (Claude Code, daemon-managed repos) flooded GitHub issues
with journal-grade content within hours:

- **`<client>`-infra#1273** — filed 12:44 UTC. By 13:27 it carried: a
  **44,467-char** "repo research" comment posted 20 seconds after
  creation, a **22,398-char** "Research addendum", then a chain of
  correction comments ("Correction: there are TWO pfSense instances…",
  "MEASURED: …"). The issue body itself was 19KB.
- **`<client>`-infra#1269** — accumulated ~12 step-by-step narration
  comments over two days: "Built, reviewed, and ready for the dev run",
  "Dev run attempted — converge OK, verify failed, now fixed", "Reviews
  complete", "Dev run GREEN", a manual "Sizing retrospective", plus
  corrections-on-corrections.

Humans (including management, who read only the issue) could no longer
find either ticket's actual state. The repo owner called it "a HUGE
degradation".

## Root cause

Not the CI bots — every flooding comment was authored by the developer
account agents act under, i.e. **interactive/agent sessions**, exactly
the surface the daemon governs. Two reinforcing drivers:

1. Repo-level session rules that (correctly) demand visibility — e.g. a
   standing rule that "a blocked item recorded only inside a plan
   document is invisible" — were generalized by agents into "record
   *everything* on the issue".
2. A sizing/approval workflow that legitimately uses issue comments
   (`Approved: <size>`, `time: <n>h <note>` one-liners) normalized
   comment-posting, and sessions extended it to research dumps and
   per-step progress narration.

Guidance patches (CLAUDE.md policy sections, workflow prompt updates)
were applied the same day, but guidance alone is the same mechanism that
failed — the daemon's own philosophy applies: make the rule mechanical.

## Why this belongs upstream (not a per-repo project handler)

- A project handler protects only the repo it is copied into; the
  flooding happens across every repo agents work in. Per-repo copies
  drift — the exact anti-pattern the daemon exists to prevent.
- The daemon already ships GitHub-aware built-ins (`gh_issue_comments`,
  `gh_pr_comments` requiring `--comments`) and a size-tiered
  `comment_size` handler for *code* comments. A GitHub-comment size cap
  is the natural sibling: same family, same options machinery, delivered
  estate-wide by routine daemon upgrades.
- The remediation target — "put it in the plan JOURNAL/supporting doc
  and link it" — is the daemon's own plan-workflow infrastructure, so
  the deny message can point at a facility the daemon guarantees exists.

## Proposed handler design (worked out, ready to lift)

**Match** (Bash tool only):

- `gh issue comment …` / `gh pr comment …`
- `gh api` with a path matching `(issues|pulls)/…/comments` or
  `issues/comments/<id>` AND a write method (POST/PATCH or any
  `-f/-F/--field/--raw-field body=` present)
- Explicitly NOT matched in v1: `gh issue create` / `gh pr create`
  bodies (sometimes legitimately structured/long; comments are the
  flooding vector), and read shapes (`--paginate` list calls).

**Body-size extraction**, first match wins:

1. `--body` / `-b` inline value (shlex parse; on shlex failure fall
   through to 4).
2. `--body-file` / `-F <path>` (comment subcommands) → stat the file
   (resolve relative paths against the hook input's cwd). Missing file
   or `-` (stdin) → cannot judge → ALLOW.
3. `gh api -f|--field|--raw-field body=VALUE` inline; `-F body=@path` →
   stat the file.
4. Fallback for heredoc/`$( )` bodies no parser can extract: if the
   command matched a comment-write shape, estimate
   `len(command) − ~150`. Catches the 44KB-dump case without needing to
   understand substitution.

**Decision**:

- estimated body ≤ threshold → ALLOW, no context.
- over threshold + `MUST_LONG_COMMENT_BECAUSE="…"` present → ALLOW with
  context recording the declared reason (daemon's standard escape-hatch
  convention).
- over threshold otherwise → DENY (terminal). Reason names the actual
  size, the threshold, and the remediation: post a ≤20-line human
  summary; relocate the content to the plan's `JOURNAL/` day-file or a
  supporting doc; link the committed file from the short comment;
  corrections EDIT the earlier comment rather than chaining a new one.

**Suggested options** (mirroring `comment_size`'s shape):

```yaml
github_comment_size:
  enabled: true
  options:
    max_comment_chars: 3000   # policy target ~1500; block at 2x
    mode: block               # block | warn
    exclude_repos: []         # e.g. a scratch/testing repo
```

**Deliberately out of scope**: MCP `mcp__github__create_issue_comment`
(workflow agents in CI don't run through the daemon); retroactive
cleanup of existing floods; issue-body caps (possible v2 at a higher
threshold).

## Test matrix (written, passing shapes enumerated)

A collocated pytest suite was drafted during this session and is
reproducible from this report: match/non-match for the four write shapes
and four read/create non-shapes; ALLOW for small inline body, small api
field, missing body-file, escape hatch (with context); DENY for big
`--body`, big `gh pr comment`, big `--raw-field`, big `--body-file`
(tmp file), big `-F body=@file`, and the heredoc-substitution fallback;
deny-reason asserts the size figure and the word JOURNAL appear.

## Companion behaviour already shipped repo-side (for context)

- Canonical policy doc (`CLAUDE/github-comment-discipline.md` in
  ai-tools): comments only on human-relevant events (blocked, hand-off,
  decision needed, done), ≤ ~20 lines; research/progress → plan docs,
  linked not pasted; corrections edit-not-chain; machine formats stay
  one-liners; issue bodies same rule.
- The estate-wide comment-trigger workflow prompt gained the same rules.
- `<client>`-infra PR #1274 adds the section to that repo's CLAUDE.md.

The handler is the missing enforcement leg. With it upstream, every
daemon-managed repo gets "issues are for humans, plans are for
verbosity" as a mechanical guarantee on the next daemon upgrade.
