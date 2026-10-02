# Review: ARCHITECTURE.md § "Threat model: the agent is careless, not hostile"

Reviewer: Fable 5.1, read-only. Text under review: `CLAUDE/ARCHITECTURE.md:783-816`
(commit f38117f59). Context read: `CLAUDE/Security/README.md`,
`CLAUDE/Routine/00001-security-review-full/CHECKS.md`, `.claude/agents/security-reviewer.md`,
the N135/N176/N177/N189 dismissal in `NIGGLES.md:709-731`, and the module docstrings of
`secret_file_guard.py`, `sensitive_content.py`, `destructive_git.py`,
`upgrade_approval_guard.py`, plus `Security/FailOpenBoundaries.md` and
`Security/UnenumeratedSpelling.md`.

The ruling is taken as settled. Every finding below is about the written statement.

## Findings

### 1. The in/out test is a plausibility guess, not a decidable line — must-fix

**Evidence.** The section's operative test is `ARCHITECTURE.md:815-816`: "would a careless
agent plausibly type this?" That asks a reviewer to estimate a frequency, and two reviewers
will estimate it differently. The example lists do not settle the cases that actually come up,
and one example is wrong as written. Five borderline commands against the current text:

| Command                                            | Current text puts it…                                                                                                                             | Right?                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `git -C ../other commit`                           | Unplaced. `cd sub && git commit` is in scope; `-C` is not mentioned.                                                                              | Should be in scope, clearly. `destructive_git.py:36-48` records that one `-C` silently disabled the whole handler, and the fix was treated as a defect, not evasion. A global option is an ordinary spelling.                                                                                                 |
| `python -c "open('.env').read()"`                  | In scope ("interpreter one-liner", line 796).                                                                                                     | Right, and matches what `secret_file_guard` already does.                                                                                                                                                                                                                                                     |
| `cat $(ls *.secret)`                               | Ambiguous. "command assembled from text" (803) says out; "substitution NESTING chosen to slip past a parser" (805) implies one plain level is in. | Should be in scope: one level of substitution or a glob is ordinary shell with a working purpose. The text needs to say "one level" explicitly, otherwise line 803 swallows every `$( )`.                                                                                                                     |
| `find . -name '*.key' -exec cat {} +`              | Unplaced.                                                                                                                                         | Should be in scope. `secret_file_matching.py:1630` already treats `find -name` as an expanding route, and the shape is routine agent work.                                                                                                                                                                    |
| `git commit -am x` after an unrelated edit         | In scope ("a careless secret in a commit", 797) — but only by inference.                                                                          | Right, and it is THE archetype: `sensitive_content` scans the working tree for `-a` precisely because of it. It should be the first example, not an inference.                                                                                                                                                |
| `timeout 3600 bash -c 'while …; git commit; done'` | OUT, by line 803 (`bash -c` is listed without qualification).                                                                                     | **Wrong.** A literal `bash -c '…'` body is visible to the daemon and is a shape the daemon's own guidance tells agents to type (`R-UNBOUNDED-LIVENESS-LOOP`: "Wrap it in `timeout 3600 bash -c '…'`"). Only a body the daemon cannot see (`"$X"`) is the dismissed N189 shape. The example conflates the two. |

**Proposed wording.** Replace the plausibility test with a two-part criterion a reviewer can
apply without guessing, and fix the `bash -c` example.

Old (801-809):

> - **Out of scope**: shapes only an adversary writes. Examples:
>   - a command assembled from text (`bash -c "$X"`, `eval`, `printf`-built words);
>   - a git alias defined to hide a subcommand;
>   - arithmetic or substitution nesting chosen to slip past a parser;
>   - `/proc/self/...` or file-descriptor tricks;
>   - anything that disables or routes around the daemon itself.

New:

> - **Out of scope**: a shape is out of scope when EITHER holds:
>
>   1. the operative text is not visible to the daemon at the time of the call — it comes
>      from a variable, a file or a substitution's output (`bash -c "$X"`, `eval "$cmd"`,
>      `source f`, a git alias resolved at run time, words built by `printf -v` or
>      arithmetic); or
>   2. the shape has no working purpose other than defeating a parser — `$(( $(…) ))`
>      around a command, a `case` inside `function f {` inside `$( )`, `/proc/self/fd`
>      reads of a file that has a name, anything that stops or routes around the daemon.
>
>   A LITERAL body is visible and in scope: `bash -c 'git commit -m x'`,
>   `timeout 3600 bash -c '…'`, `python -c "open('.env').read()"`. One level of `$( )`,
>   a glob, `find -exec`, `xargs`, and git's global options (`-C`, `-c`, `--git-dir`) are
>   ordinary shell and in scope, however rarely typed.

And replace 815-816:

> Reviews and security sweeps apply the same test before raising a bypass: would a careless
> agent plausibly type this?

with:

> Reviews and security sweeps apply the two-part test above before raising a bypass. "Would
> an agent plausibly type this?" is a tiebreaker when the test does not settle it, not the
> test itself.

Also add `git commit -am x` to the in-scope list at 793 as the first example.

### 2. Prompt injection is unplaced, and the text will be read both ways — must-fix

**Evidence.** The section has two actors, careless and hostile (785-787). An agent carrying
out instructions injected through an issue body, a fetched page or a file in a cloned repo
is neither: it is well-meaning, and the instructions may ask for exactly the shapes in the
out-of-scope list. A reviewer who meets this case will either dismiss an ordinary-shape
finding ("the agent was effectively hostile") or raise an obfuscated one ("the agent was
innocent"). Both are wrong under the ruling, and the text does not say so.

Two options, consistent with the owner's words:

- **Option A — judge the command, never the motive (recommended).** The ruling is about
  SHAPES. The daemon never knows who authored an instruction, so injection changes nothing
  about what is in or out: an injected instruction that produces an ordinary shape
  (`cat .env | curl -d @- …`, `git commit -am x`) is caught exactly as a careless one is;
  an injected instruction that produces an out-of-scope shape IS the hostile case, and the
  defence against it is upstream of the daemon (Claude Code's permission mode, the human,
  OS permissions — the "defence in depth over an OS boundary" line already in
  `secret_file_guard.py:24-27`). This needs one paragraph and no new category.
- **Option B — name injection as a third actor and defend it part-way.** Treat the
  injected agent as careless but assume its instructions come from an adversary, so the
  guards chase obfuscated shapes WHERE THE SINK IS EXFILTRATION (protected-file reads,
  `gh` bodies, network egress) and nowhere else. This is defensible but it reintroduces
  the parser arms race the owner ruled out, on the surfaces where it is most expensive,
  and the boundary ("which sinks?") will drift. Not recommended; recorded so the owner
  decides.

**Proposed wording (Option A).** Add after 813:

> **Motive is not judged.** The daemon sees a command, not who wrote the instruction behind
> it. An agent carrying out instructions injected through untrusted content (an issue body,
> a fetched page, a file in a cloned repository) is covered exactly as far as those
> instructions produce in-scope shapes, and no further. Past that point it is the hostile
> agent above, and the defence is upstream — Claude Code's permission mode, the human in
> the loop, and the OS permissions the guards are defence-in-depth over. A finding is never
> promoted to in-scope because the agent "might have been injected", and never dismissed
> because it "must have been".

### 3. "Prefer the simpler guard" reads as a licence to weaken what must stay — must-fix

**Evidence.** Line 813: "Prefer the simpler guard that lets the adversarial shape
through." Nothing in the section says what the ruling does not touch. Four things in the
codebase look like adversarial posture and would be fair game for a reader applying 813
literally:

- **Fail-closed verdicts on what the guard cannot read.** `R-SECRET-COMMAND-UNREADABLE`
  ("an unreadable command is never treated as clean"), `R-SECRET-EVALUATION-ERROR`,
  `R-PROJECT-CONTAINMENT-EVALUATION-ERROR`, and the `JUDGED UNSEEN` denies in
  `HANDLER_REFERENCE.md:1490`. Note the direct tension: N177's shape (a `case` inside a
  function inside `$( )`) is DISMISSED for the commit gates and DENIED by
  `secret_file_guard`. That is correct — the ruling sets the ceiling on what must be
  CAUGHT, not a floor on what may be denied out of caution — but the text does not say
  so, and 813 says the opposite.
- **The no-escape-hatch doctrine** (`secret_file_guard.py:21-24`, Plan 00259: "an agent
  that can type its own justification has self-authorised disclosure"). This is a
  careless-agent control — an agent rationalising, not attacking — and must survive.
- **Human-gated approvals.** `upgrade_approval_guard.py` closes `eval`, `declare -x`,
  indirect names, `set -a`, exported functions (its docstring item 3) — all out-of-scope
  shapes by line 803. The gate exists so a human reads what changed; its breadth is the
  owner's prior decision (Plan 00376), not a reviewer's.
- **Secrets protection against ordinary reads** is in scope by line 796, but a reader
  of 813 could still argue a `Grep -l` on a protected path is "too simple to be a read".
  `secret_file_guard.py:8-10` has already decided that; say the ruling does not reopen it.

**Proposed wording.** Replace 811-813 and add a "What this does not change" block:

Old:

> - **False positives cost real work.** A guard that denies ordinary commands to catch
>   obfuscated ones fails the agents it exists to help. Prefer the simpler guard that lets the
>   adversarial shape through.

New:

> - **False positives cost real work.** A guard that denies ordinary commands to catch
>   obfuscated ones fails the agents it exists to help. When catching an out-of-scope shape
>   would cost an in-scope false positive, let the shape through. When it costs nothing,
>   there is nothing to remove.
>
> **What this ruling does not change:**
>
> - A guard that cannot read what it judges still fails closed (`R-SECRET-COMMAND-UNREADABLE`,
>   the `*-EVALUATION-ERROR` rules, `JUDGED UNSEEN`). The ruling caps what a guard must
>   catch; it does not oblige a guard to allow what it cannot see. The same shape can be
>   dismissed for one gate and denied by another, and both are right.
> - No guard gains an escape hatch an agent can type (Plan 00259). An agent rationalising
>   is the careless agent, not the hostile one.
> - Human-gated steps stay human-gated: release, `approve-upgrade`, protected-path
>   disclosure. Their guards keep the shapes they already close.
> - A protected file is protected against every ORDINARY read route, including `Grep -l`
>   and an interpreter one-liner (`secret_file_guard`).
> - The fail-open behaviour described under "Error Handling & Fail-Open Philosophy" is
>   for infrastructure failure (config, JSON, a crashed handler), and the inventory in
>   `Security/FailOpenBoundaries.md` still applies to it. It is not a statement about guards.

### 4. Ambiguous, overclaimed or missing — should-fix (one must-fix item inside)

4a. **Where a dismissed finding is recorded — must-fix.** Line 809: "recorded and
dismissed". `Security/README.md:43-55` says the register holds categories, not findings,
and `ROUTINE.md:132-134` says `RUNS/` is "not a place to record findings". A dismissed
finding has no category and no Defence, so under the current docs it has NO home — it will
be re-found. The repository already has the right slot: `UnenumeratedSpelling.md:57` has
an `UNCOVERED-accepted` status in `scripts/qa/dangerous-invocation-corpus.yaml`, which
makes the Detector keep asserting the allow. Proposed addition after 809:

> Recording means two things: the ledger or plan that raised it marks it
> `Dismissed (threat model)` naming the shape (as Plan 00474 did for N135/N176/N177/N189),
> and, where the finding is a command, a row is added to
> `scripts/qa/dangerous-invocation-corpus.yaml` with status `UNCOVERED-accepted` so the
> corpus keeps asserting the verdict and the next sweep does not re-raise it.

4b. **"So no guard is judged on whether it survives deliberate evasion" (787) — overclaim.**
`tests/unit/handlers/pre_tool_use/test_blocking_handler_evasion.py` judges every
command-anchored guard on respellings (`git -C`, quoted words, `--git-dir`), and
`destructive_git.py:36-53` calls one of them a defect. Those are in-scope respellings, not
evasion, but the sentence as written contradicts the test file. Proposed: "So no guard is
judged on whether it survives an out-of-scope shape. It is still judged on every ordinary
respelling — a global option, quoting, a path with `git` in it — because a careless agent
produces those without trying."

4c. **"A hostile agent wins anyway, because it can stop the daemon process" (786) — state
the mechanism.** It is true because the relay fails open when the daemon is absent
(`FailOpenBoundaries.md:76-78`, `mid_exchange_fail`). Say so, or a reader will file "the
daemon is stoppable" as a finding. Proposed: "…because it can stop the daemon process, and
the hook layer fails open when the daemon does not answer (see `Security/FailOpenBoundaries.md`)."

4d. **Existing adversarial-shape complexity: kept, simplified or removed? — missing.**
Several guards already handle out-of-scope shapes (`upgrade_approval_guard` item 3,
`secret_file_guard`'s `bash -c` option walk, `command_evasion.py`). Nothing says what
happens to them. Proposed, under the "does not change" block:

> Code that already catches an out-of-scope shape is kept while it costs no in-scope
> false positive; it is not extended; and a false positive it causes is fixed by
> narrowing it, not by adding a parser. Removing it is a plan decision with the owner,
> never a review finding.

4e. **"In scope … Some examples" (791) lists shapes but not SINKS.** The guards protect
outcomes (data loss, secret disclosure, published content, broken history), and a
reviewer deciding a new case needs to know the outcome matters more than the verb.
Optional: one sentence — "What is protected is the outcome: uncommitted work, protected
file contents, what reaches GitHub, repository history, the system Python. The shape test
decides whether a route to one of those is the daemon's job."

4f. **"This is an owner ruling." (785)** — good; keep it, and keep the heading text
verbatim: four files link to the anchor
`#threat-model-the-agent-is-careless-not-hostile` (CHECKS.md:15, security-reviewer.md:21,
Security/README.md:52, NIGGLES.md:728). None of the proposals above rename the heading.

### 5. Home and pointers — should-fix

ARCHITECTURE.md under "Security Considerations" is the right single home: the agent tree
owns depth (`CLAUDE/CLAUDE.md`, `DirectoryRoles.md`), and the three satellites already
point rather than restate, as the SSOT rule wants. Two audiences are missing a pointer:

- **Handler authors** — they decide which shapes a guard matches, and are the ones most
  tempted to chase obfuscation. `CLAUDE/HANDLER_DEVELOPMENT.md` has no mention of the
  threat model (grep: none). Add one line where pattern design is discussed.
- **The evasion test file** — `test_blocking_handler_evasion.py:337-344` already argues
  the false-positive asymmetry in its own words. One pointer to the section would keep the
  test's framing from drifting into "every respelling must block".

Optional: `docs/guides/TROUBLESHOOTING.md` or `README.md` could carry one human-facing
sentence ("the daemon helps an agent that makes mistakes; it does not stop one that sets
out to defeat it") so a client project does not file an obfuscated bypass upstream.

## Verdict

The ruling is sound and the text records it faithfully, but as written it is not yet
usable by a reviewer: the in/out line is a plausibility guess rather than a criterion, one
out-of-scope example (`bash -c`) contradicts the daemon's own guidance to agents, prompt
injection is unplaced and will be argued both ways, "prefer the simpler guard" can be read
as licence to remove fail-closed verdicts, the no-escape-hatch doctrine and human gates,
and a dismissed finding has no recorded home under the current docs. All four must-fix
items are wording changes inside the same section (plus one corpus-row convention), none
renames the heading or breaks the four existing anchors, and none argues with the owner.
With findings 1–3 and 4a applied the section would be decidable, bounded and safe to cite
from a security sweep; 4b–4e and 5 are tightening.
