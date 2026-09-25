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
the pipe inside the body; no whitelist line is suggested for it. A pipe fed by
a subshell, such as `(grep x f) | head` or `( (grep x f) ) | head`, is judged
on the subshell's last command: allowed for `grep`, still denied for `pytest`.

`secret_file_guard` now gives its exemptions (the `secret-meta` helper, an
allowlisted consumer with the path in flag position, and a reader naming only
confirmed-encrypted files) behind `time`, `time -p` and `!` too. Neither word
changes which command runs or what it reads. Behind `then`, `do`, `else` and
the other compound-only words the exemption is still withheld. The exemption
covers one simple command, and those words only occur inside a compound.

The same fault hid commands from other checks. A `git commit`, `gh issue create`, `sed`, a worktree `cp`/`mv`, or a write outside the project, behind
`then` or `do`, is now caught by `staged_lint_gate`, `issue_filing_gate`,
`sed_blocker`, `worktree_file_copy` and `project_containment`, as it already
was without the prefix. Expect new denials for commands inside loops and `if`
bodies that those checks would deny on their own. The command-hint and merge
advisories fire in these spellings too, and so do `verification_result_gate`
and `quarantine_artefact_read_guard`. A heredoc fed to `cat` inside a loop
body, and a commit message inside an `if`, are now treated as data. A
`{ set -euo pipefail; ...; }` group now counts as the safety prelude.
