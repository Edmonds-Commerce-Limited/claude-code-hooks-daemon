# Category: asymmetric sibling protection

**Defence**: `scripts/qa/check_declared_invariant_pairs.py` — a checked-in
registry of site pairs that must agree, each relation asserted mechanically.

Index: [README.md](README.md). Found by
[Routine 00001](../Routine/00001-security-review-full/ROUTINE.md), across eight
independent checks rather than one.

## The class

This repository already implements the correct behaviour at another site, and
this site re-derives it, derives it shorter, or omits it.

A defect belongs here when the fix is **already written somewhere in this
codebase** and simply did not reach the site in question. The correct code is
often in the same file, sometimes twenty lines above.

The boundary is the SIBLING. A guard that is merely incomplete is not in this
class; a guard that is incomplete *while its neighbour is complete* is. That
distinction is what makes the class mechanically checkable at all — the
neighbour supplies the oracle.

Eleven prose instances and thirteen table rows came out of run 2026-001, from
eight reports whose authors never saw each other's work. Three reached for
almost identical phrasing without coordination:

- *"the escaper already exists, in this module, twenty lines above"* (D-EXEC F3)
- *"the shared fragment exists, is used by the neighbouring handler"* (D-PUB-4)
- *"a fix applied to the instance rather than to the class"* (F-DEPL-4)

That convergence is the strongest ranking signal in the entire review, and it is
why this class outranks defects with worse individual consequences.

## Why a review finds it and the test suite does not

**A test can only check a site against its own contract, and each site's own
contract is satisfied.** `pipe_blocker`'s tests assert that whitelisted
producers are allowed and expensive ones denied; `env` was whitelisted, so
allowing it was the tested behaviour. `process_probe`'s tests assert that
wrappers are unwrapped; `env` is in `_WRAPPERS`, so unwrapping it was the tested
behaviour. Both suites passed. Both were right about their own file.

Nothing in either test suite could see the other, because the defect is not in
either site — it is in the RELATION between them. A test fixture is built from
one module's imports, and that is exactly the boundary the defect hides behind.

This generalises past this class. **A defect that lives in a relation is
invisible to any check whose scope is one side of it**, which is the same
lesson [authored path resolution](AuthoredPathResolution.md) reached from the
other direction: there, both instances were missing *variables* rather than
missing tests.

## Instances

**The `env` pipe whitelist** — `strategies/pipe_blocker/common.py`,
`UNIVERSAL_WHITELIST_PATTERNS`, against `utils/process_probe.py`'s `_WRAPPERS`.

What it allowed: `env pytest tests/ | head -20` truncated pytest's output. The
pipe blocker attributed the pipe to `env` at the segment head, found it
whitelisted as a cheap filter, and allowed the truncation the handler exists to
prevent. Any expensive command could be hidden behind it.

The sibling that does it right is the rest of the repository. `_WRAPPERS`
classifies `env` as a command runner, and the evasion suite asserts that
`env git commit`, `env gh issue create`, `env pgrep -f` and `env cat <DETAIL>`
are each judged on the WRAPPED command. The pipe whitelist was the single site
holding the other reading.

Removal cost nothing: `printenv` is the non-wrapper spelling, does the same job,
cannot run another command, and remains whitelisted.

- Defence: `79421f21`, committed deliberately red over 1 declared row.
- Fix: `85b5adc4`.

**The worktree relocation verbs** —
`handlers/pre_tool_use/worktree_file_copy.py`, `_RELOCATION_VERBS`, against
`core/utils.py`'s `_WRITE_INDICATOR_RE`.

What it allowed: `install` and `dd` relocate a file and were not matched, so
the same move out of a worktree was denied when spelled `cp` and allowed when
spelled `install`. Verified by probing the handler rather than reading the
regex — three verbs denied, two allowed.

The sibling had carried both all along. The worktree verbs were an alternation
inlined at their only call site, which is the shape that has no sibling to be
checked against and drifts from one silently.

- Defence: `602c5fa3`, committed deliberately red.
- Fix: `55f374e8`.

**Judging prose as a command** — the same handler, found by hitting it: the
commit message for `602c5fa3` was DENIED, because it described this handler and
so contained a worktree path beside a relocation verb. A **call-path** instance
rather than a constant one.

What it cost: the deny renders "WHY THIS IS CATASTROPHIC" and five bullets about
destroying branch isolation, so someone writing a sentence was told they nearly
destroyed their work. A guard that cries wolf on prose is a guard people switch
off, which is how a false positive becomes a security problem.

`utils/shell_segmentation.strip_inert_spans` is this repository's existing
answer to "what command is actually being run", and `destructive_git`,
`pipe_blocker`, `merge_to_main_approval` and `daemon_location_guard` all reach
it. This handler judged the raw string. The helper existed; the site did not
reach it.

The boundary was kept rather than widened: `bash <<'EOF'` still has its body
judged, because the receiver RUNS those bytes whatever the outer shell quoted.

- Fix: `c23b1b8c`, whose own message carries the previously-denied shape and is
  therefore the regression proof.

This instance has **no registry row**. A call-path row needs a single named
helper both sites must call, and this site's fix was to route its whole scan
target through one — expressible, but not yet written. It is recorded as an
instance because it happened, not because it is covered.

**The unguarded refresh** — `remote_docs/store.py::refresh_document` against
`write_capture`, on the helper `content_guard`. The first instance found by the
**call-path** rule kind rather than by comparing two constants.

What it allowed: `write_capture` refuses to vendor content the sensitive-content
scanner rejects, because a capture writes from a CLI and bypasses the `Write`
hook that would otherwise inspect it. `refresh_document` ran the same fetch and
the same write with no scan at all.

The reasoning applies more strongly on the refresh path, which is what makes
this more than tidiness: a capture is something a human ran deliberately once,
while a refresh exists *because upstream may have changed*, and those new bytes
have had no review by anyone.

The fix added a `REFUSED` outcome rather than reusing `FAILED` — a failed fetch
is transient and retryable, a refusal means upstream is now serving something
that must not enter the repository — and placed the scan BEFORE the
unchanged-hash short-circuit, so the short-circuit cannot become a route past
the guard.

- Defence: `5b6ac98b`, committed deliberately red.
- Fix: `a6ce7bb7`.

**The tilde that escaped containment** —
`handlers/pre_tool_use/project_containment.py::_resolve_against_cwd` against
`core/utils.py::_resolve_write_target`, on the helper `expand_home`. The most
consequential instance so far: a live bypass of `R-WRITE-OUTSIDE-PROJECT-ROOT`.

What it allowed: the same destination got opposite verdicts depending on how
the command spelled the write.

| command              | before    | after |
| -------------------- | --------- | ----- |
| `curl -o ~/x.sh`     | **ALLOW** | DENY  |
| `echo > ~/notes.txt` | DENY      | DENY  |

`_resolve_write_target` expands a leading `~`; `_resolve_against_cwd` declined
it and handed back the token unresolved — and an unresolved, relative-looking
token is treated as never-outside, so the write was allowed. `core/utils.py`
had already written down the opposite rule, noting that declining the tilde
"silently un-enforces" the memory-file policy for its most natural spelling.

**The docstring was part of the camouflage.** `_resolve_against_cwd` claimed it
shared the decline "verbatim" with the shared accessor. It shared the CONSTANT
— which deliberately omits `~` — and then added a `~` decline on top. A reader
checking the claim would have been reassured by it, which is worse than no
claim at all.

Fixing it **overturned release-review finding C6**, which listed `leading-tilde`
beside `$HOME`, a glob and a backtick as "decline, do not fabricate". C6's
principle is preserved and still enforced for the other three: `/tmp/work/~/evil.sh`
is never produced. What C6 missed is that declining was not the only
alternative — `~/x` expands deterministically to where the shell actually
writes, so naming it is *resolution*, not fabrication. The other three have no
such expansion available. Superseding a finding in the open, with the test that
records why, is the point here: leaving a real bypass open to avoid touching an
existing verdict would have been the worse error.

- Defence: `b3f3614b`, committed deliberately red.
- Fix: `f280153f`, verified by a full suite at 32/32.

**The forwarder interpolations** — `install/forwarder_generator.py`,
`build_relay_guard_block`, against `_escape_for_double_quotes` in the same
module. **Partially fixed, and listed that way on purpose.**

What it allowed: a checkout path carrying `$` or a backtick produced a forwarder
that expanded a variable, or ran a command substitution, every time the daemon
was down. The escaper's own docstring calls this failure "silent and remote" and
escapes an internal CONSTANT for that reason — while the paths, which are
wherever the user cloned, went in raw.

Reading the site found the worklist's one defect to be **three quoting
contexts**. Three sites are a plain double-quoted string, where the existing
escaper is exactly right, and are fixed. Two sit inside `${VAR:-default}`,
where `}` terminates the expansion and the escaper has no rule for it.

**No registry row was added**, and the reason belongs in this register rather
than only in the plan: a `reaches` row asserts the function CALLS the helper, so
applying the escaper to all five sites would have turned the row green while two
remained broken. A row satisfiable by a partial fix is worse than no row,
because it converts an open defect into a closed one on paper.

The remaining fork is an owner decision, written up with a recommendation in
[DECISION-forwarder-interpolation-contexts.md](../Plan/00412-jobs-recurring-work-and-security-review/DECISION-forwarder-interpolation-contexts.md).

**The bare-name `gh` anchor** —
`handlers/pre_tool_use/sensitive_content.py`, `_GH_BODY_PATTERN`, against
`sudo_pip.py`'s `_SUDO_PIP_PATTERN` and the git surface in its own file. The
first instance to need a **fragment** row rather than a constant or a
call-path one.

What it allowed: `/usr/bin/gh issue create --body "<term>"` and `./gh …` did
not match the publish guard **at all** — no deny, no advisory — while the same
term in `git commit` was denied whether or not the binary was path-qualified.
Confirmed by probing the handler, not by reading the regex. `gh` is the surface
of the two that no history rewrite can retract.

The siblings had all settled this. `git` is recognised here through
`endswith(f"/{_GIT_EXECUTABLE}")`, and `curl_pipe_shell`, `sudo_pip` and the
pipe whitelist each interpolate `command_evasion.OPTIONAL_PATH`. Four sites
agreed that a binary may be named by path; one disagreed, and it was the
irreversible one.

The fix keeps the strict left boundary rather than relaxing it to `\b`.
Widening was the cheaper edit and would have been wrong: `\b` matches inside
`foo-gh`, so the guard would start judging a command that is not `gh`. A test
pins that boundary alongside the path tolerance.

**This row needed a fourth relation, and that is the interesting part.**
`reaches` asserts a CALL; a shared regex fragment is a module-level constant
interpolated into a pattern, so a `reaches` row would have stayed false after a
correct fix. `interpolates` asserts that both symbols are BUILT FROM the named
fragment. What earns it a row where the forwarder pair was refused one: **it
cannot be satisfied by a partial fix** — the fragment is either in the pattern
or it is not. That is the test worth applying to every future row.

The row pairs the `gh` anchor with `sudo_pip`, deliberately **not** with the
git surface twenty lines away in the same file. That one hand-rolls its path
tolerance and is correct, merely bespoke; a row demanding one idiom of both
would assert style rather than protection, and a registry that starts policing
style is one that gets switched off.

- Defence: `2696cffe`, committed deliberately red.
- Fix: `8489b6dd`.

**The unread message file** —
`handlers/pre_tool_use/sensitive_content.py`, `_bash_haystacks`, against
`github_auto_close_keywords.py`'s `_message_file_texts`, on the helper
`read_message_files`.

What it allowed: `git commit -F msg.txt` carrying a blocked term was **never
scanned** — the file was not opened — while `git commit -m "<term>"` was
denied. The sibling handler had read git message files all along; this handler
owned an equivalent reader and had wired it into its `gh` branch only.

Probed through the haystack builder rather than through `matches()`, and the
distinction mattered: a `matches()` False in a temp directory could equally
mean "nothing is staged", which is a different fact. Asserting the wrong one
would have put a false claim in this register.

The fix is one call under the condition the handler **already computed** for
both surfaces. That shape is what makes the row sound: a call placed inside the
`gh` branch instead would satisfy a `reaches` row while leaving git unscanned.
**Choose the fix shape that makes the row honest, rather than choosing a row to
fit a fix** — that inversion is the transferable part.

The reader stays scoped to the two surfaces that genuinely take a message or
body file. Reading every `-F` on every command would start treating `gh api`'s
`-F key=value` — a FIELD, on a surface this guard deliberately does not cover —
as a filename.

**Consolidating it produced a fresh instance of this very class, by my own
hand.** The two copies were strict in DIFFERENT ways: `sensitive_content`
caught a read that fails AFTER the stat, and the sibling only pre-checked with
`os.access`. Keeping one and dropping the other lost the catch, and three
existing tests failed with the lesson already in their docstring — *statting a
file is not reading it, and the gap raises*. A file whose mode denies read
stats perfectly well, and so does one unlinked between the check and the read.
The catch now lives in the shared reader, so the sibling GAINED a protection it
never had. Recorded because the failure mode is the point: deduplication is
exactly when a site's hard-won extra care gets dropped.

- Defence: `ab93117f`, committed deliberately red.
- Fix: `1a74bf90`.

**The unguarded rmtree** — `install/skills.py`, `_deploy_one_skill`, against
`_remove_retired_skills` twenty lines below it. **Recorded with no registry
row, for a reason distinct from the other two rowless instances.**

What it allowed: deploying a skill called `shutil.rmtree` on its target with no
provenance test. The sibling refuses to delete a same-named directory that does
not look daemon-deployed, and its docstring states the principle the other site
ignores — doing so "would destroy project work with no backup, which is far
worse than leaving an orphan". The correct reasoning was already written down,
in the same file, twenty lines away.

The realistic loss is not a name collision. It is a user CUSTOMISING a deployed
skill and losing the edit silently on the next upgrade.

**Provenance had to be derived rather than read.** A deployed skill is a byte
copy of the shipped source, so nothing in it was written by the daemon and not
by a user — there is no marker to test, which is why the deploy path had no
test. Comparing the trees supplies one, and survives a version bump: a target
matching what is about to be written IS our own copy; one that differs may not
be.

The rescue nearly introduced a worse defect than the one it fixed. Claude Code
discovers skills by DIRECTORY, so preserving the old copy beside the new one
would register a second, stale slash command. The backup lives outside
`.claude/skills/`, and an unchanged skill leaves none at all — clutter is how a
warning stops being read.

**Why no row**: the two sites take DIFFERENT correct actions on the same duty.
One refuses and warns; the other preserves and proceeds. A `reaches` row would
assert they call the same helper, which is a similarity that is not the
invariant. The invariant is "do not destroy what you did not write", and the
registry has no relation that expresses an obligation discharged two ways.
That is a third distinct reason for rowlessness, beside "the row would be
satisfied by a partial fix" (the forwarder) and "expressible but not yet
written" (`strip_inert_spans`).

- Fix: `e8683948`, verified 32/32.

Ten further table rows are recorded in
[the consolidated worklist](../Plan/00412-jobs-recurring-work-and-security-review/subagent-reports/260915-consolidated-defence-worklist.md),
with the registry's design notes in
[DESIGN-declared-invariant-pairs.md](../Plan/00412-jobs-recurring-work-and-security-review/DESIGN-declared-invariant-pairs.md).
Each becomes an instance here as its row lands. Two of their fixes are
owner-gated, because both add a refusal in installing projects: D-PUB-3's
fail-closed on an oversized body file, and F-HYG-3's new deny in
`staged_lint_gate`.

## Rejected rows

A row is a human claim that two sites must agree. Some proposed pairs turn out
to be **correctly different**, and recording those is as much a part of the
category as recording the instances — otherwise the same pair gets re-proposed
by the next reviewer and eventually written.

**`sensitive_content` vs `staged_lint_gate` on `path_is_protected`** — proposed
by two independent checks (`D-SEC-1`, `F-HYG-3`) as "one excludes protected
paths and the other does not". Rejected after reading both.

`staged_lint_gate` skips a protected file because a lint diagnostic can quote
the offending source line verbatim, so scanning one would leak its content into
a deny message. `sensitive_content` has no such vector by construction: its deny
names the file path and a pattern name or entry index, **never the line**.

So the exclusion that is right in one is wrong in the other. Adding
`path_is_protected` to `sensitive_content` would stop it scanning staged
protected files — and a protected file staged *with a secret term in it* would
then commit silently. The row would have removed protection in the name of
consistency.

**The real defect under `F-HYG-3` points the other way**: `staged_lint_gate`
silently `continue`s past a staged protected file. A protected file reaching the
index is itself the alarming event and nothing says so. That fix is a new deny
in installing projects and is therefore owner-gated, which is how the
consolidated worklist already classified it.

The generalisable point: **two guards touching the same concept are not
obliged to agree — only guards with the same DISCLOSURE behaviour are.** The
asymmetry is a defect when one site is wrong, not whenever the sites differ,
and telling those apart is the reading a registry exists to capture.

## What the Defence does not catch

- **Only declared pairs.** This is the defining limitation and it is
  structural, not an oversight. A divergence with no row in
  `scripts/qa/declared-invariant-pairs.yaml` is invisible, and the registry
  currently holds six rows against thirteen known instances. **Read a green
  run as "every declared pair holds", never as "the class is clear."**

  The third instance above proves the point from inside: it is a real member of
  this category, found while building the Defence, and the Defence does not
  cover it.

  The generative half — proposing candidate pairs by finding a constant or
  helper consumed by one of two handlers that judge the same command — was
  measured as noisy and deliberately does not gate a build. A noisy rule gets
  switched off, and a switched-off rule protects nothing.

- **Two extractors, both shallow.** `dict_keys` reads the string keys of a
  module-level dict literal; `regex_head_names` reads the `^name\b` head of each
  literal pattern in a module-level tuple or list. A member computed at import
  time, built by a comprehension, or assembled from another module is not seen.

- **A non-literal entry is SKIPPED, not guessed at.** The pipe whitelist mixes
  plain literals with f-strings built from the shared git grammar
  (`rf"^{GIT_INVOCATION}log\b"`). Inventing a member from one would be a false
  positive; skipping it under-reports. That direction is chosen deliberately —
  the cheap error for this rule is missing a member, because crying wolf once
  costs the whole check.

- **Four relations.** `disjoint`, `superset`, `reaches` and `interpolates` are
  implemented; `equal` and `same-normalisation` are designed and not built.

- **`interpolates` proves a REFERENCE, not an effect.** It asserts the named
  fragment appears in the symbol's value expression. It cannot tell whether the
  fragment was placed where it does any good — a path qualifier interpolated at
  the wrong end of a pattern satisfies the row and protects nothing. Position
  was checked by a test, not by the rule, exactly as ordering was for `reaches`.

  A relation added to the Detector also has TWO renderers — the JSON message
  and the terminal label — and the first version of this one had only the
  first, so a real violation crashed the Detector instead of reporting it. A
  test now asserts over the whole relation set so the next relation cannot
  repeat it.

- **`reaches` proves a CALL, not an effect.** It asserts that the named helper
  is invoked somewhere in the function body. It cannot tell whether the result
  is acted on, whether the call sits behind a condition that is never true, or
  whether it runs before the write it is supposed to guard. Ordering was the
  load-bearing detail in the `content_guard` fix and no rule checked it — a
  test did.

  It also cannot see a helper reached through an alias, a partial, or a
  dispatch table, and a name-only match means a DIFFERENT function of the same
  name satisfies the row.

  **It follows exactly ONE hop**, and both bounds were bought. Reading only the
  named body called ordinary refactoring a violation — extracting the work into
  a small helper method broke a row that the fix had satisfied — which would
  push code to stay inline purely to satisfy a check, the rule dictating
  structure. Repointing the row at the inner helper is worse: that helper
  satisfies the row even when nothing calls it, so DEAD CODE turns it green.
  Following arbitrarily far is the opposite failure, degrading the row into
  "this function eventually reaches something". A test pins the two-hop bound
  so the limit is stated rather than discovered.

- **Still only declared pairs.** Rows cover `pipe_blocker`/`process_probe`,
  the worktree verbs, the remote-docs writers, the write-target resolvers, the
  executable anchors, and the message-file scanners.

- **Deduplication is a way to CREATE a member of this class.** Consolidating
  two copies of one concept drops whatever extra care the stricter copy had
  learned, unless someone diffs them for behaviour rather than for shape. It
  happened here while fixing D-PUB-2 and was caught only because the dropped
  care had regression tests. Nothing mechanical watches for it.

- **A proposed pair can be WRONG, and nothing mechanical says so.** The
  `path_is_protected` pair came from two independent checks and would have
  weakened a guard had it been written (see Rejected rows). The Detector
  asserts whatever a row claims — it has no opinion on whether the claim is
  correct, so a badly-read row turns into enforced damage.

  This is the real cost of "near-zero false positives by construction": the
  construction is a human reading both sides, and the rule inherits that
  reading rather than checking it.

  `_escape_for_double_quotes` is the instructive absence. It has a recorded
  instance, a partial fix, and deliberately **no row** — because the row would
  be satisfied by the partial fix. Where a rule can be satisfied without the
  defect being gone, writing the row down is worse than leaving it out, and the
  register has to be able to say so.

- **A row must name which MEMBERS participate.** This was bought the hard way.
  The first row drafted asserted a superset between two relocation-verb
  alternations that were each missing members of the other — `rsync` on one
  side, `install`, `dd` and `tee` on the other — so a naive set comparison
  reported a violation in BOTH directions and neither was the defect. A check
  that opens with noise on its first row gets switched off rather than
  satisfied.

- **A rotted row is caught, but only structurally.** A renamed file or symbol
  raises rather than yielding an empty set, because empty is disjoint from
  everything and a rotted row would otherwise read as a row that passes.
  What is NOT caught is a row whose sites still exist and whose declared
  relation has quietly stopped being the right thing to assert; only a human
  re-reading the `reason` catches that.

- **It proves agreement, not correctness.** Two sites can agree and both be
  wrong. The registry asserts that this project's own reasoning propagates, not
  that the reasoning was sound.
