# Category: outcome reachable by an unenumerated spelling

**Defence**: `scripts/qa/check_dangerous_invocation_corpus.py` — a recorded
verdict in `scripts/qa/dangerous-invocation-corpus.yaml` that no longer
describes what the real chain decides

## The class

A dangerous outcome is reachable by a command, flag or shell construct that no
guard's pattern names.

Two causes, deliberately one category, because one Detector finds both:

- **The pattern is short.** A guard enumerates a tool whose subcommand set is
  open. `git checkout -- <file>` is denied and `git checkout -f` is not; the
  push-force pattern already parses refspec sigils and handles `+`, one key
  away from `:`.
- **Nothing judges the outcome at all.** `rm -rf`, `truncate -s 0`,
  `crontab -r`, `docker run -v /:/host`.

Whether a row is uncovered because a pattern is short or because nothing exists
is a fact the Detector reports, not a reason for two Detectors. F-GAP's own
report flags the overlap and routes a candidate to F-BYPS for exactly this
reason: *a duplicate is cheaper than a hole.*

## Why a review finds it and the test suite does not

Every guard's tests pass, because they test the spellings the guard names. A
test suite is written from the same list as the pattern, so it inherits the
pattern's blind spot exactly. Nothing in a per-handler suite asks "what else
reaches this outcome?" — that question has no owner until something like this
corpus gives it one.

The documentation makes it worse rather than better. `CLAUDE/ARCHITECTURE.md`
and `CLAUDE/HANDLER_DEVELOPMENT.md` both list `rm -rf` beside `sed -i` and
`git reset --hard`. Those two are genuinely denied, so a reader checking the
third has every reason to believe it. **The gap cannot be found by reading**,
which is why it survived being noticed once, in
`CLAUDE/Plan/Completed/00017-acceptance-testing-playbook/PLAN.md:183`, and
never actioned.

## Why the corpus asks for a DECISION, not a match

F-GAP measured that `verification_result_gate` *matches* almost every git
command and then allows it. A `matches()`-only method would therefore have
scored 24 git candidates as covered while nothing denied them — a Detector that
reports the opposite of the truth on two dozen rows.

The corpus runs each command through the project's real configured chain and
reads the decision. It builds that chain **in-process**: the guard judges a
command string wherever it appears, including inside a probe's own payload, so
a shell-borne probe is denied before it can run. That is the guard working, and
it is also a small instance of this very class seen from the other side.

## Instances

**20 rows: 14 `UNCOVERED-open`, 3 `UNCOVERED-accepted`, 3 controls.** The full
table is the corpus file. The ones worth naming here:

- **`rm -rf`** — the worst single row, for the documentation reason above.
- **`git reflog expire --expire=now --all`** + **`git gc --prune=now`** —
  sharp because `destructive_git`'s own acceptance test justifies a decision
  with "recoverable via reflog". The handler's safety reasoning depends on a
  mechanism nothing protects.
- **`gh auth token`** — confirmed live on this host: `~/.config/gh/hosts.yml`
  holds the OAuth token at mode 0600 and matches no default protected glob.
  This is **not** a defect in `secret_file_guard`: the route is command-shaped,
  not path-shaped, and outside what that guard claims.
- **`pip install --index-url <host>`** — arbitrary code execution from a chosen
  host, and the one package-manager row worth denying narrowly.

**Nothing is fixed.** Every fix is owner-gated per row, because every new deny
is a new refusal surface in every installing project.

Three rows are `UNCOVERED-accepted` rather than open, and the distinction is
the point: `git rebase` and a broad `npm install` deny are reported as too
noisy to ship — *"it would be suppressed within a release"* — and `printenv`
misfires. A rule that gets switched off protects nothing. Recording a decision
not to act keeps it visible instead of leaving it looking like an oversight.

## What the Defence does not catch

- **Whatever nobody thought to add.** The corpus only covers its own rows. It
  converts an invisible gap into a visible list; it does not generate the
  list. This is the honest reason it is a **weaker** Defence than the
  categories whose Detectors read code, and it must be described that way
  rather than as coverage.
- **Anything that is not a single Bash command string.** A dangerous outcome
  reached by a sequence, by a script the agent writes and then runs, or by a
  tool other than Bash, is outside the harness.
- **Whether a deny is the RIGHT deny.** A row passes when the chain denies it;
  the corpus does not check that the deny message names a useful rule or
  suggests a workable alternative.
- **Noise.** The corpus says nothing about how often a candidate rule would
  misfire in ordinary work, which is precisely the axis the owner-gated
  decision turns on. That judgement lives in the row's `note`, written by a
  person.
