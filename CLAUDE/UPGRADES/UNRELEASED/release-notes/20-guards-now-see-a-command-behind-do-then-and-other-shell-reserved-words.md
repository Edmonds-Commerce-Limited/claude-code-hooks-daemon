# Callout: guards now see a command behind `do`, `then` and other shell reserved words

**Plan**: 00422
**Audience**: everyone

In `for f in a b; do grep x "$f" | head; done`, `pipe_blocker` read the loop
keyword `do` as the pipe's producer. It denied a whitelisted `grep` and
suggested whitelisting `^do\b`, which would have exempted every loop body's
pipe. If you added a whitelist line naming `do`, `then` or `done`, remove it.
The pipe is now judged on the command after the reserved word (`do`, `then`,
`else`, `elif`, `if`, `while`, `until`, `!`, `{`, `time`). A pipe fed by a
whole loop or `if` (`...; done | tail`) is still denied, with advice to move
the pipe inside the body; no whitelist line is suggested for it.

The same fault hid commands from other checks. A `git commit`, `gh issue create`, `sed`, a worktree `cp`/`mv`, or a write outside the project, behind
`then` or `do`, is now caught by `staged_lint_gate`, `issue_filing_gate`,
`sed_blocker`, `worktree_file_copy` and `project_containment`, as it already
was without the prefix. Expect new denials for commands inside loops and `if`
bodies that those checks would deny on their own. The command-hint and merge
advisories fire in these spellings too, and so do `verification_result_gate`
and `quarantine_artefact_read_guard`. A heredoc fed to `cat` inside a loop
body, and a commit message inside an `if`, are now treated as data. A
`{ set -euo pipefail; ...; }` group now counts as the safety prelude.
