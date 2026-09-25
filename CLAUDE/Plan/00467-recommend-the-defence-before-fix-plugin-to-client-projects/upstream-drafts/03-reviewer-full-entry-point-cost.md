# Draft: the conformance reviewer must run the full entry point twice, in a fresh worktree

**Target**: `Defence-Before-Fix/claude-plugin`
**Status**: draft, not filed. A cost and fit problem, not a correctness defect. The coordinator
decides whether it is worth filing.

## Title

`conformance-reviewer`: allow the coordinator to name a targeted entry-point command for the
red and green reproductions

## Summary

`agents/conformance-reviewer.md` (lines 21-26) requires two runs of "the project's entry point":
one at the defence commit, which must fail, and one at the final commit, which must pass. The
agent declares `isolation: worktree`, so both runs happen in a new worktree.

In a mid-sized project the full entry point can be heavy: tens of thousands of tests over 15-20
minutes, plus a per-worktree environment build before the first run. Some projects also stop
sub-agents from running the full gate at all, and leave it to the coordinator. They do this
because several parallel agents each running the full suite exhaust the host. There, the
reviewer's reproduction is either very expensive or denied.

SPEC section 7 needs the verdict to rest on reproduction, and SKILL.md step 8 needs the green
run to go through the project's own entry point. Neither says the whole gate must run. Most
entry points can run one named check (`make qa CHECK=semgrep`, `tool.py <check-name>`). That is
still the project's entry point, at a fraction of the cost.

## Reproduction

1. In any project whose full QA gate takes several minutes, run `/dbf` to the end.
2. Let the skill dispatch `defence-before-fix:conformance-reviewer` as step 3 describes.
3. Observe that the reviewer runs the full gate twice in a new worktree: a new checkout,
   dependency install, the whole suite, then all of it again. In a project whose hooks deny the
   full gate to sub-agents, observe the denial instead.

## Suggested direction

- In SKILL.md step 3, add "the targeted form of the entry point that runs only the new rule's
  check" to what the coordinator hands the reviewer, alongside the full entry point.
- In the reviewer, run the targeted form for the red proof, since only the rule's check has to
  fail. For the green run, use the targeted form plus a note of whether the coordinator ran the
  full gate. Where the targeted form is not enough, say so as a finding rather than running the
  full gate unasked.
