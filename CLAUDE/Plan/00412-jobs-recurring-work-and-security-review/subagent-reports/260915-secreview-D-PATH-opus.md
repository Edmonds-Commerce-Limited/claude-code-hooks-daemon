# Security review — check `D-PATH`

Routine 00001, run 2026-001, FULL sweep. Interval: current tree at HEAD
`5d59f7ff` (root `74b0989c`), reviewed as a tree rather than a diff.

Check definition: *"New filesystem writes, and whether each is inside project
containment; new path handling that a `..` or a symlink could walk out of."*

**The check was answerable and was run.** Four findings, two of them confirmed
by executing the live code, two of them live instances of blind spots the
`authored path resolution` register entry already names. The confirmed
category (`scripts/qa/check_authored_path_stat.py`) is not re-reported.

| #   | Finding                                                                                               | Status                      | Confidence      |
| --- | ----------------------------------------------------------------------------------------------------- | --------------------------- | --------------- |
| 1   | `quote-drift` opens and reads any host file an author names in an `ssot-quote` marker                 | New class                   | High — executed |
| 2   | `project_containment` allows an out-of-repo write on six shapes when the destination is spelled `~/…` | New class                   | High — executed |
| 3   | The authored-path Detector sees none of the 31 join-then-consume sites in its own two trees           | Coverage gap (blind spot 4) | High — measured |
| 4   | `path-existence`'s span pattern admits `..`, so a plan probes host paths                              | Instance (blind spot 5)     | High — executed |

---

## Finding 1 — an `ssot-quote` marker names any file on the host, and the daemon opens it

### Citation

`src/claude_code_hooks_daemon/docs_qa/checks/quote_drift.py:78-89`

```python
source_abs = project_root / block.source_path
if not source_abs.is_file():
    ...
source_text = source_abs.read_text(encoding="utf-8")
```

`block.source_path` is whatever an author wrote between `ssot-quote:` and `#`.
The parser accepts it unconditionally —
`src/claude_code_hooks_daemon/docs_qa/quotes.py:66-67`:

```python
_QUOTE_OPEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^<!--\s*ssot-quote:\s*([^#]+)#(\S+?)\s*-->\s*$"
)
```

`[^#]+` admits `..`, a leading `/`, and any symlinked component. There is no
containment test, no normalisation, and no size bound anywhere on this path.

### What it concretely allows

A one-line comment in a markdown file makes the daemon `open()` and
`read_text()` an arbitrary file on the host, as the daemon's user.

Confirmed by calling the check's own `_verify_block` (probe at
`/workspace/untracked/scratch/probe_quote_source.py`, run against the real
module):

```
'../../../../etc/hostname'   joined -> /workspace/../../../../etc/hostname   OPENED AND READ
'/etc/hostname'              joined -> /etc/hostname                          OPENED AND READ
'CLAUDE/../../../etc/hostname'  joined -> …/CLAUDE/../../../etc/hostname      OPENED AND READ
'.claude/hooks-daemon.yaml'  joined -> /workspace/.claude/hooks-daemon.yaml   OPENED AND READ
```

Three concrete consequences, in descending certainty:

1. **`secret_file_guard`'s invariant is broken by the daemon itself.**
   `R-SECRET-READ` states the protected file's contents "must NEVER be read
   into context by any route — not Read, not Bash, not an interpreter
   one-liner, not a copy". That guard judges *tool calls*. This read is not a
   tool call, so nothing sees it: an `ssot-quote` marker naming
   `.claude/block-words.secret` or `.env` has the daemon read the file during
   its own PreToolUse gate. (`_verify_block` does not echo the bytes into the
   finding message, so this is a *read*, not yet a disclosure — see 2.)

2. **A verbatim-substring oracle over that file.** `verify_quote(block.body, span)` returns clean when the quote body appears in the source span, and a
   distinct BLOCK message otherwise; `resolve_anchor_span` gives a second
   oracle on anchor text. The answer is delivered to the agent as a docs-QA
   denial. So the content is queryable even though it is never quoted back.
   `MIN_QUOTE_LENGTH_CHARS = 80` bounds the rate, not the capability.

3. **Unbounded synchronous read on the dispatch hot path.** `read_text()` has
   no size cap (there is no `st_size` guard anywhere in `docs_qa/` except the
   corpus's mtime/size cache keys). A marker naming a multi-gigabyte file is
   read whole inside a PreToolUse hook.

The timing makes this worse than it first reads: `docs_qa_edit.py:144-173`
builds the context from `tool_input` and calls `run_stage(CheckStage.EDIT, context)` inside `handle()`. **The read happens before the write is allowed** —
a Write that is then DENIED has already caused it. And the same `_verify_block`
runs at `CheckStage.STAGED` (commit gate) and `CheckStage.SWEEP` (session
start, `quote_drift.py:149-172`), so a marker that reaches the tree re-reads
its target at every session start with no further agent action.

### The class

**A path an author wrote, joined to a root and then OPENED, with no test that
the result is still inside the repository.**

The boundary is mechanical and separates this cleanly from the registered
category: that one is about a stat predicate answering the wrong *question*
(`..` walked through the filesystem). This one is about a join being
*dereferenced* — `read_text`, `open`, `glob`, `iterdir` — with no containment
test at all. Normalising does not fix it; the register says so in its own last
bullet. A site belongs here when all three hold: the joined value comes from
document content or config rather than from the daemon enumerating the
filesystem; the result is dereferenced rather than merely stat-ed; and no
`is_relative_to(root)` (or equivalent) gates the dereference.

Two sites in the tree already do this correctly and are the pattern to copy:

- `utils/worktree_seeding.py:59-74` — rejects absolute, rejects `..` in
  `candidate.parts`, then `source.resolve().is_relative_to(root.resolve())` to
  catch a symlinked component. All three, in that order.
- `remote_docs/capture.py:92-98` — `_sanitise_segment` refuses a segment that
  is only dots, explicitly "traversal, not a name".

### Why the test suite does not catch it

`tests/unit/docs_qa/checks/test_quote_drift.py` has 21 tests. Every one builds
its marker through the same helper (`_quote_block(source, anchor, body)`, line
42\) and every call site passes a well-formed in-repo path: `CLAUDE/Source.md`
for the present case, `CLAUDE/Nope.md` for the missing case (lines 76-353). The
"source file is missing" branch — the only place the suite exercises a path
that does not resolve — is tested with a path that is still inside the repo.

Nothing in the fixture shape suggests the source path is an *untrusted input*
rather than a *reference to a sibling document*, so no test varies it that way.
The suite is testing the mechanism it was handed; the mechanism's input domain
was never written down.

### Detector hypothesis

**Rule**: in `docs_qa/` and `plan_qa/`, a path built by joining a non-literal
value must not be dereferenced (`read_text`, `read_bytes`, `open`, `glob`,
`rglob`, `iterdir`) unless a containment test on that name is reachable first.

The practical form, because "reachable first" needs flow analysis a syntax rule
should not attempt: **route every authored dereference through one helper** —
the sibling of `authored_path_exists` — and make the rule a chokepoint, exactly
as the existing Detector is. Something like
`utils.authored_paths.authored_path_read(base, target)` that normalises,
resolves, asserts `is_relative_to(base)` and raises a typed error otherwise.
The Detector then says: *no bare dereference of a joined non-literal in these
two trees*, with no exemption marker, and the containment question is answered
in one place rather than argued at each site.

**Likely false positives**, honestly stated:

- **The corpus walkers.** `docs_qa/corpus.py:726-807`, `quote_drift.py:157-161`,
  `at_import_census.py:112-116`, `module_doc_budget.py:321-325` all join
  `project_root / rel_path` where `rel_path` is a corpus key the daemon itself
  produced by walking the tree. Containment is guaranteed by construction and
  the rule cannot see that. These are 12 of the 31 sites in Finding 3 — nearly
  half. Routing them through the helper costs one `resolve()` each and keeps
  the rule a chokepoint, but a reviewer will read them as noise unless the
  helper's docstring says why they are included.
- **`plan_qa/context.py:145-161` and `plan_qa/model.py:515-524`** join
  config-derived directory names (`policy.completed_dir`, `plan_dir_rel`,
  `journal_dir_name`). These are *not* false positives — see Finding 4 — but
  they will be argued as such because the config is in-repo.

The ratio is roughly 1 genuine to 3 arguable, which is far better than the
17-to-7 ratio the register says got the original rule scoped down. It stays
tolerable only if the fix is a helper rather than a warning.

### Confidence

**High.** Executed against the real module; the four cases above are the
probe's actual output, not a reading of the code. What I did *not* establish:
whether any code path echoes the source *bytes* into a message. I read every
`Finding` constructed in `quote_drift.py` and none carries `source_text`, so I
am calling this an oracle rather than a direct disclosure — but that is a
negative established by reading one file, and a second route (a report
renderer, a log line at debug level) would change the severity. Settled by
grepping every consumer of `CheckContext`/`Finding` for a field carrying source
text.

---

## Finding 2 — `project_containment` allows an out-of-repo write spelled `~/…`

### Citation

`src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py:319-327`

```python
if any(character in target for character in _UNEXPANDABLE_CHARACTERS):
    return target
if target.startswith("~"):
    return target
```

`_resolve_against_cwd` returns the tilde token unchanged, and `_is_outside`
(line 469) then treats it as never-outside because `Path("~/x").is_absolute()`
is False.

### What it concretely allows

An out-of-repository write, through six of the command shapes the handler's own
`get_claude_md` declares it covers — and declares exhaustively:

> "**That list is exhaustive, not illustrative — and one gap remains.** An
> interpreter one-liner … is NOT caught and cannot be" (line 538).

Confirmed against the live handler (probe at
`/workspace/untracked/scratch/probe_containment_tilde.py`, `ProjectContext`
initialised from the real config):

```
DENY   echo probe > ~/probe.txt            offending=['/root/probe.txt']
DENY   cp README.md ~/probe.md             offending=['/root/probe.md']
DENY   curl -o /etc/probe.sh https://…     offending=['/etc/probe.sh']
ALLOW  curl -o ~/probe.sh https://…        offending=[]
ALLOW  wget -O ~/probe.sh https://…        offending=[]
ALLOW  tar -cf ~/probe.tar CLAUDE          offending=[]
ALLOW  mkdir ~/probe-dir                   offending=[]
ALLOW  rsync -a CLAUDE ~/probe-dir         offending=[]
ALLOW  scp README.md ~/probe.md            offending=[]
ALLOW  sh -c 'curl -o ~/probe.sh https://…'  offending=[]
```

The first three lines are what make this a defect rather than a design
limit. The handler **already denies `/root/probe.txt`** — it just reached that
path by the other extraction route. So one guard gives opposite verdicts for
the same destination depending on which of its two extractors saw it, and the
nested-shell re-entry (`_nested_shell_targets`) inherits the gap.

The two routes disagree because only one of them expands `~`. The shared
accessor is explicit that expanding it is correct —
`core/utils.py:71-76`:

> "`~` is deliberately ABSENT: unlike `$VAR` or a glob, a leading tilde is a
> deterministic expansion of HOME that this process can perform exactly. It
> also must not be declined — Claude's own memory files live at
> `~/.claude/projects/*/memory/`, and `markdown_organization` blocks writes to
> them today, so treating `~` as unresolvable would silently un-enforce that
> policy for its most natural spelling."

`_resolve_write_target` acts on that, calling `_expand_home(target)` at line
617-618. `_resolve_against_cwd` does the opposite, and its docstring cites
"release review finding C6" as the reason — a finding about *fabricating* a
location out of a token that needs a shell. `$HOME`, `*`, `?` and a backtick
genuinely need one. `~` does not: the daemon knows `HOME`, and the companion
accessor proves it by expanding it three modules away.

### The class

**Two extraction routes inside one guard that normalise a path differently, so
the guard's verdict depends on which route saw the target rather than on where
the target is.**

The test for membership is a question, not a pattern: *can I write the same
destination two ways and get two verdicts?* Any guard with more than one input
path — a shared accessor plus a local extractor, a tool payload plus a Bash
parse — is a candidate, and the answer is found by enumerating the
normalisation steps each route performs and diffing the lists. Here the lists
differ by exactly one entry: `_expand_home`.

This is distinct from the interpreter-one-liner gap the handler documents.
That one is a genuine impossibility (resolving it means executing the command).
This one is a discrepancy between two pieces of the same handler, and the
correct behaviour is already written down in the other piece.

### Why the test suite does not catch it

**The test suite asserts the defect.**
`tests/unit/handlers/pre_tool_use/test_project_containment.py:275-288`:

```python
("dollar-expansion", 'curl https://x -o "$HOME/evil.sh"'),
("glob-star", "curl https://x -o out*/evil.sh"),
("glob-question", "curl https://x -o out?/evil.sh"),
("backtick", 'curl https://x -o "`whoami`/evil.sh"'),
("leading-tilde", "curl https://x -o ~/evil.sh"),
...
assert handler.matches(_bash(command, cwd="/tmp/work")) is False, \
    f"{label} was fabricated into a path instead of declined"
```

`~` was grouped with four tokens that really are unexpandable, and the group was
pinned by a parametrised test. The class is now protected by a green test whose
failure message argues for it. Fixing the handler fails this case, and the
failure text tells the next reader they have reintroduced a release-review
finding — which is the shape that makes a defect survive several reviews.

The suite also has the right test for the right shape at line 227-231
(`curl -o ../../../tmp/x.sh` → denied), so the gap is not a missing category of
thought. It is one token in a list.

### Detector hypothesis

**Rule**: for each guard that resolves write destinations by more than one
route, the set of normalisation operations applied by each route must be equal.
Concretely, as a repo-specific check: any module importing
`_UNEXPANDABLE_CHARACTERS` from `core.utils` must apply the same tilde
treatment as `_resolve_write_target` — i.e. a function that tests
`target.startswith("~")` and returns without expanding, in a module that
imports that constant, is a violation.

**Likely false positives**: a route that declines `~` for a reason other than
resolvability — a read-only classifier where `~` is genuinely out of scope.
I found none in this tree, so the rule currently fires on exactly the one site.
That narrowness is also its weakness: it is closer to a regression test wearing
a Detector's clothes than to a rule that generalises. The honest framing is
that the *class* (route-dependent normalisation) is real and worth a Detector,
but a syntax rule can only reach the one instance of it; a genuine Detector
would need to enumerate each guard's routes, which is a design change to how
targets are extracted (one accessor, not two) rather than a check.

**Note for the fix**: the second-order effect is the interesting one. Making
containment expand `~` means `~/.claude/...` writes become out-of-root
candidates — caught by the existing `allow_claude_home` allowance
(`_is_permitted`, line 475), which resolves the Claude home and compares
component-wise. I checked; it handles them. But that allowance is what makes
the fix safe, and a fix that lands without it would deny every Claude-home
write.

### Confidence

**High.** Executed against the real handler with the real config. The ALLOW
verdicts above are the handler's own output.

---

## Finding 3 — the authored-path Detector sees none of the 31 sites in its own two trees

**Not a new category.** This is blind spot 4 of
`CLAUDE/Security/AuthoredPathResolution.md` ("It is a syntax rule … a join
built up over several statements … does not match"), reported because the
register asks for blind spots to be measured rather than assumed, and because
the measurement changes how the Detector's coverage should be described.

### Citation

`scripts/qa/check_authored_path_stat.py:159-166` — the receiver must be an
`ast.BinOp` at the call site:

```python
receiver = node.func.value
if not (isinstance(receiver, ast.BinOp) and isinstance(receiver.op, ast.Div)):
    continue
```

### What it concretely allows

I re-ran the Detector's question one statement away: a local assigned from a
join with a non-literal operand, then stat-ed, read, globbed or iterated,
scoped to the same two trees the Detector claims (scanner at
`/workspace/untracked/scratch/scan_authored_indirect.py`).

**31 sites. The Detector reports 0 of them.** Breakdown:

- 12 are corpus-walker joins (`corpus.py`, `at_import_census.py`,
  `module_doc_budget.py`, `quote_drift.py:157`) — daemon-enumerated keys, safe
  by construction.
- 9 are plan-tree joins over config-derived directory names
  (`plan_qa/context.py:145,159`, `plan_qa/model.py:395,515`,
  `plan_qa/checks/common.py:114,317`, `journal_entry_ordering.py:148,172`,
  `same_commit_plan_doc.py:78`) — see Finding 4.
- **2 are `quote_drift.py:79` and `:89`** — a genuinely authored path, stat-ed
  and then read. Finding 1.

So the Detector's own scoped trees contain a live instance of the hazard it was
written to eliminate, and it is invisible for a purely syntactic reason: the
author wrote `source_abs = project_root / block.source_path` on its own line
instead of inlining it.

### The class

Already named by the register. What is new is the measurement: **the blind spot
is not a residue, it is the majority.** The Detector finds 7 sites; the same
question asked one statement away finds 31 in the same two directories.

### Why the test suite does not catch it

`scripts/qa/check_authored_path_stat.py` is a Detector, not a test — and it
passes. It passes because it is asking a narrower question than its own
docstring claims:

> "in the two trees whose job is resolving paths an author wrote, normalise
> before you stat, always. Seven sites, no exceptions to weigh"

"Always" is the claim a reader takes away, and the register's
"What the Defence does not catch" section is the only place the qualifier
lives. A green check plus a confident docstring is what makes a blind spot read
as coverage.

### Detector hypothesis

Extend the existing Detector with single-assignment tracking within a function
scope: record names bound to a join with a non-literal operand, then flag the
predicates on those names. My scanner is 80 lines and does exactly this; it
needs a function-scope boundary (mine uses module scope, which would over-report
across a reused name) and the same `_SCOPED_TREES` filter.

**Likely false positives**: the 12 corpus-walker sites, as in Finding 1. That
is a 1-in-3 signal ratio — worse than the current rule's, better than the
17-to-7 that got the original scope rejected. Making it a chokepoint (route
through the helper) rather than a warning is what keeps it obeyed.

### Confidence

**High** for the count (measured, scanner output above). **Medium** for the
claim that the 12 corpus sites are safe by construction — I traced `rel_path`
back to `corpus.documents` keys for `quote_drift.py:157` and
`at_import_census.py:112`, and inferred the rest from the identical shape
rather than tracing each. Settled by reading `corpus.py:700-810` for how keys
are produced.

---

## Finding 4 — `path-existence` lets a plan probe arbitrary host paths

**Not a new category.** This is blind spot 5 ("Containment is a different
question … a link reading `src/../../etc/passwd` resolves to a real file, and
this Defence says nothing about that"), reported because the register states it
hypothetically and the tree contains a live instance whose input pattern
*specifically admits* the traversal.

### Citation

`src/claude_code_hooks_daemon/plan_qa/checks/path_existence.py:45-68`

```python
code_dirs = "|".join(re.escape(d) for d in main_repo_code_dirs(context.layout))
return re.compile(rf"^(?:{code_dirs})/[A-Za-z0-9_./-]+$")
...
if not authored_path_exists(context.project_root, span):
    missing.append(span)
```

The character class `[A-Za-z0-9_./-]` contains `.` and `/`, so `..` is a
well-formed span. Confirmed:

```
'src/../../../etc/hostname'         regex=True  normalised=/etc/hostname                    exists=True
'src/../.claude/hooks-daemon.yaml'  regex=True  normalised=/workspace/.claude/…yaml          exists=True
'tests/../../../../etc/passwd'      regex=True  normalised=/etc/passwd                       exists=True
```

### What it concretely allows

An inline-code span in a `PLAN.md` becomes a one-bit existence probe against
any path on the host, and the answer comes back in a finding the agent reads:
`"PLAN.md references path(s) that do not exist: …"`. Absence is reported by
name (up to `_MAX_REPORTED_PATHS = 10`); presence is silence. Registered at
both EDIT and SWEEP, so it runs at every session start on a plan already in the
tree.

Lower severity than Finding 1 — existence, not content, and the check is
`Level.ADVISE` — but it is the same missing test, and the *guard prefix*
(`src/`, `tests/`, `config/`) reads like a containment check while doing none:
it constrains the first segment and nothing after it.

The same is true of `docs_qa/checks/pointer_resolves.py:95-100`: a markdown
link target reaching outside the repo resolves, and the check reports the link
as live. Harmless on its own — a live link is the non-finding — but it is the
third site where an authored path is resolved with no containment test, which
is what makes the pattern worth a rule rather than three fixes.

### The class

Same as Finding 1: an authored path resolved with no containment test. This is
the *stat* end of it, where the register already predicted it.

### Why the test suite does not catch it

`tests/unit/plan_qa/checks/` fixtures name plausible plan paths (`src/foo.py`),
because that is what the check is *for*. The span pattern was written to
recognise "does this look like a project path?", and a pattern answering that
question honestly has no reason to reject `..` — the rejection belongs at the
resolution step, which is a different function in a different module. Neither
side is wrong in isolation, which is why no test sits at the seam.

Worth stating plainly: the `authored_path_exists` conversion did not cause
this and does not worsen it. `Path.exists()` on the unnormalised join returns
True here too, because `/workspace/src` exists so the `..` walk succeeds. The
register is right that normalising is orthogonal to containment.

### Detector hypothesis

Same chokepoint as Finding 1, with the containment assertion inside the
helper — which is the argument for putting it there rather than at each call
site: `authored_path_exists` is already the single funnel for the stat half,
so one change covers `path_existence.py`, `pointer_resolves.py` and
`plan_qa/model.py` at once.

The design question the helper's signature forces, and which I cannot settle
from here: **is escaping the root a "does not exist" answer, or an error?**
Returning False silently makes an escaped link report as dead, which is the
exact wrong-message failure the registered category exists to stop. Raising
makes a docs check crash on a hostile document. A third `Finding` ("this
pointer leaves the repository") is probably right, and it is a policy decision
for the caller, not for a reviewer.

**Likely false positives**: a legitimately out-of-repo pointer. In a monorepo
or a worktree layout, `../sibling-package/README.md` is a real, correct link.
`core/worktree_paths.py` already re-roots worktree paths for
`markdown_organization`, so the concept exists in the tree; a containment rule
that does not consult it will fire on every cross-worktree pointer.

### Confidence

**High** that the traversal resolves (executed). **Medium** on severity: I am
treating a 1-bit existence oracle delivered through an ADVISE message as low
harm, and that judgement depends on where those findings are surfaced. If the
plan-QA sweep report reaches anywhere outside the session, it is worth more.

---

## What I checked and found clean

Recorded so the next full run knows these were looked at, not skipped.

- **`project_containment`'s containment test itself.** `_is_within` (line
  452-463) resolves before `relative_to`, and the docstring names the
  string-prefix failure (`/repo-backup` vs `/repo`) it avoids. `..` and
  symlinks are both handled. The tilde gap in Finding 2 is upstream of this
  function, not in it.
- **Session-id-derived signal paths.** `operator_signal.py:81`,
  `session_actions_signal.py:68`, `model_downgrade_signal.py:117`,
  `goal_injection.py:94` all sanitise with `[^A-Za-z0-9_.-]` → `_`, which
  removes `/`, so a `..` in a session id cannot traverse (it becomes a filename
  `..json`, not a directory step). `one_shot_approval.py:30-32` additionally
  replaces `..` with `__`. The three signal modules do not, and are safe only
  because `/` is stripped — an inconsistency worth knowing about if that
  character class is ever widened, but not a defect today.
- **`remote_docs` URL-to-path derivation.** `capture.py:92-98` refuses a
  dots-only segment explicitly; `_require_https` refuses a non-HTTPS URL. A
  lossy derivation appends a SHA-256 prefix rather than colliding.
- **`routines/` (the newest code in the interval).** `find_routine` matches
  against folders it enumerated (`resolver.py:84-105`); `ledger_path` joins a
  literal and an `int` year (`ledger.py:121-131`). No authored value reaches a
  path.
- **`utils/worktree_seeding.py:57-74`** — the correct pattern, cited above.
- **Daemon runtime writes.** The B108 discipline holds: runtime files go to
  `untracked/`, and the `/tmp` appearances in `daemon/paths.py:1127-1295` are
  documented last-resort socket-path fallbacks that log a warning.
- **`secret_file_matching.path_is_protected`** (line 255-273) checks both the
  raw path and its `os.path.realpath`, so `..` and symlink spellings of a
  protected path both match. Not walkable out.

## What I did not check

- **Client-install writes** (`install/*.py` writing into another repository's
  tree). In scope for D-PATH by the letter of the definition, but the
  destination is a different project's root and containment is a different
  question there. Flagging as unexamined rather than clean.
- **`--report-dir` and similar CLI flags** (`daemon/cli.py:3363-3387`) resolve
  an operator-supplied path and write outside the repo by design. I judged that
  an operator choice rather than a containment defect; if the routine wants CLI
  surfaces treated as untrusted, this needs a second look.

## Probes

Read-only, left in `untracked/scratch/` for whoever builds the Defences:

| Path                                           | What it shows                                                   |
| ---------------------------------------------- | --------------------------------------------------------------- |
| `untracked/scratch/probe_quote_source.py`      | Finding 1 — which file `_verify_block` actually opens           |
| `untracked/scratch/probe_containment_tilde.py` | Finding 2 — the ALLOW/DENY split by extraction route            |
| `untracked/scratch/scan_authored_indirect.py`  | Finding 3 — the 31 sites                                        |
| `untracked/scratch/scan_containment.py`        | The 55 unnormalised `relative_to` sites the triage started from |
| `untracked/scratch/scan_writes.py`             | Write-side sweep (2 hits, both clean)                           |
