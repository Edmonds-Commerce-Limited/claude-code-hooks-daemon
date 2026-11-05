# Callout: gh issue/pr view guards now suggest a command that returns the body

**Plan**: 00565
**Audience**: client projects

The `gh_issue_comments` and `gh_pr_comments` guards used to tell an agent to append `--comments`, but without a terminal `gh ... view --comments` prints only the comments and drops the body (and prints nothing for an item with no comments). They now suggest `--json title,body,state,comments` (plus `author` for pull requests), which returns both, and their guidance says `--comments` alone omits the body in non-interactive output. What the guards match and block is unchanged, and `--comments` is still allowed (reported as issue #158).
