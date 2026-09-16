# Decision: the two `${VAR:-default}` interpolations in the generated forwarder

Supporting document for Plan 00412, closing
[DECISION-forwarder-interpolation-contexts.md](DECISION-forwarder-interpolation-contexts.md).
Decision only — nothing here was implemented, and the tree is unchanged.

## The ruling

**DECISION: endorse option B — stop interpolating a generator-supplied path
into a `${VAR:-default}` word at all. Every path the generator bakes sits in a
plain double-quoted assignment, passed through `_escape_for_double_quotes`, and
the expansion default references that variable by name. Option C is declined:
a refusal is warranted only where a value cannot be embedded correctly, and
every path a filesystem can hold can be. The `reaches` row may be added, but
the document's claim that B makes it "meaningful" is withdrawn — the row
protects against total regression only, and the Defence must be an effect
test.**

B wins over A on one determinate ground, not on tidiness. Both are correct (A's
missing rule is `}` → `\}`, and bash specifies it). But under A the invariant
"every path in an expansion default went through the second table" is a
property of the CALL GRAPH, which is exactly the kind of property this plan has
already recorded as unprovable by scan (`reaches` proves a call, not an
effect). Under B the invariant becomes a property of the ARTEFACT — "no
absolute path appears inside a `${…:-…}` word" — which is a regex over the
generated text, and this module already owns the regex that reads that shape.

## Evidence

### The document's factual claims, checked

- **Three quoting contexts.** Holds. `forwarder_generator.py:264` is a quoted
  literal ahead of an unquoted `*` in a `[[ == ]]` pattern; `:266` is a plain
  double-quoted assignment; `:273` and `:280` are inside `${VAR:-…}`. The
  first two are one context for the escaper's purposes (the document says so
  itself: "correct, applied" for both); the third differs, and measurably so.
- **The escaper has no rule for `}`.** Holds: `_SHELL_DOUBLE_QUOTE_ESCAPES`
  (`:82-87`) is `\`, `"`, `$`, `` ` ``.
- **"What is true today."** Holds. Sites `:264` and `:266` call the helper;
  `:273` and `:280` do not, with the comment at `:257-260` naming this
  document. `scripts/qa/declared-invariant-pairs.yaml` carries no row naming
  `_escape_for_double_quotes`. The register lists the instance as partially
  fixed (`CLAUDE/Security/AsymmetricSiblingProtection.md:180-202`).
- **"Five sites."** Wrong by one. `append_nc_socket_arg`
  (`forwarder_generator.py:539-559`) interpolates the same fallback events
  directory raw into a double-quoted argument (`f'"{arg}"'`, `:558`) for the
  nc rung. Plain double-quoted context, the existing escaper is exactly right
  there, and it is not applied. It sits in a different function, so a
  `reaches` row over `build_relay_guard_block` would never see it — which is
  the blind spot the document describes, one function along.
- **What `resolved_events_dir` carries.** The table reads as if it were a
  checkout path. It is not: `_get_event_socket_fallback_dir`
  (`daemon/paths.py:1277-1298`) is `$XDG_RUNTIME_DIR` → `/run/user/<uid>` →
  `/tmp`, plus `hooks-daemon-<8 hex>-events`. The only operator-chosen text in
  it is the deploying host's runtime-dir value. Real, but a smaller surface
  than the checkout path the `relay_binary` default is built from
  (`_default_relay_binary_path`, `:164-166`), and `transport.relay_binary`
  itself is a free-text config field (`config/models.py:1483-1486`).

### What the characters do inside `"${X:-word}"` — measured, bash 5.2

| Word as written              | `X` unset            | `X=/override`  |
| ---------------------------- | -------------------- | -------------- |
| `/some/pa}th`                | `/some/path}`        | `/overrideth}` |
| `/some/pa\}th`               | `/some/pa}th`        | `/override`    |
| `/a\$Y/b` (`Y=EXPANDED`)     | `/a$Y/b`             | —              |
| `/a$Y/b` (`Y=EXPANDED`)      | `/aEXPANDED/b`       | —              |
| `` /a\`echo RUN\`/b ``       | `` /a`echo RUN`/b `` | —              |
| `/a\"b`                      | `/a"b`               | —              |
| `/a\\b`                      | `/a\b`               | —              |
| `$d` where `d="/some/pa}th"` | `/some/pa}th`        | `/override`    |

And in a plain double-quoted string, `"/some/pa\}th"` yields `/some/pa\}th` —
the backslash survives. So `\}` is the correct escape in the expansion word
and the wrong one in a plain string: the two tables really are different, and
the document is right that the existing helper cannot be pasted at these
sites. The bash manual specifies the rule rather than leaving it to
implementation: "the matching ending brace is the first `}` not escaped by a
backslash or within a quoted string" (§3.5.3, Shell Parameter Expansion).

Tilde is not expanded in either context (`"${X:-~/relay}"` → `~/relay`), `!`
is inert in a non-interactive shell, and a newline, a space and glob
characters all survive the plain-assignment-then-`$name` route byte for byte.
So the set of characters the plain context must escape is the four the
helper already has, and there is no path a POSIX filesystem can hold (any
byte but NUL) that cannot be embedded that way.

### The defect as it stands today — reproduced through the real generator

`build_relay_guard_block("pre-tool-use", TransportConfig(relay_enabled=True), Path("/some/$HOME/pa}th/untracked"), Path("/some/$HOME/pa}th"))`, then the
`_rl_*` assignment lines run under `bash` with `HOME=/EXPANDED`:

- `_rl_dir` = `/some/$HOME/pa}th/untracked` — the fixed site, correct.
- `_rl_bin` = `/some//EXPANDED/path/untracked/bin/hooks-relay}` — `$HOME`
  expanded, the brace migrated to the end.
- with `HOOKS_DAEMON_RELAY_BINARY=/override`: `_rl_bin` =
  `/overrideth/untracked/bin/hooks-relay}` — the operator's override is
  corrupted.

Two failure classes are live at these two sites, and they are not the same
severity. `$` and backtick are the escaper docstring's "silent and remote"
class: a command substitution runs every time the daemon is down. `}` is a
fail-open: the resolved path is wrong, `-x`/`-S` is false, and the forwarder
takes the legacy round trip — the cost `build_relay_guard_block`'s own
docstring (`:219-223`) already accepts for a false negative. The document's
decision to leave the sites wholly raw rather than half-escaped kept the MORE
severe class live in order to keep the register honest. That was a defensible
trade and it should now be short: the implementation below closes both
classes in one change.

### Why B and not A — the one difference that is determinate

Both are correct. A needs a second table (the existing four plus `}` → `\}`),
and its stated cost — "every existing caller gains an argument" — is only
true if it is built as an argument; a sibling helper sharing the table costs
no caller anything. So A is cheaper than the document says, and the artefact
stays byte-identical for every normal install.

What decides it is what each option lets a Detector PROVE.

- `reaches_helper` (`scripts/qa/check_declared_invariant_pairs.py:439-470`)
  answers "does this function call the helper, directly or one hop away". It
  is satisfied by one call anywhere in the function. `build_relay_guard_block`
  already makes three, so a `reaches` row over it is GREEN TODAY, with two
  sites raw — and would stay green under A with one site forgotten, or under
  B with a fresh `${VAR:-<literal>}` site added by habit. Context count and
  site count are invisible to it. The document's "once all five sites sit in
  one context, the `reaches` row becomes meaningful" does not follow; the
  sixth site in `append_nc_socket_arg` is the counter-example already in the
  tree.
- Under B the guarantee has a second, cheap, artefact-level statement: no
  `${…:-…}` word in a generated block contains a baked absolute path.
  `_ABSOLUTE_PATH` (`forwarder_generator.py:342-344`) already reads exactly
  that shape — `test_a_default_value_expansion_still_exposes_a_baked_path`
  (`tests/unit/install/test_forwarder_root_normalisation.py:140-147`) pins
  that `${VAR:-/abs/path}` is detected. Under A the same guarantee cannot be
  stated over the artefact; it lives only in which helper each f-string
  called.

That is the ground: B moves the invariant from the source's call graph, where
the plan has already found scanning weak, to the artefact's text, where a
scan is exact. Everything else the document says for B — one context, one
proven helper, no new refusal — is true and secondary.

### Why not C — a refusal with no defect behind it

C says: refuse to generate a forwarder for a checkout whose path holds a
character that "cannot be safely embedded". The measurements above show there
is no such character. Refusing a working configuration to avoid a defect the
generator can simply not have is not loudness about a failure; it is a
failure the refusal itself introduces, and the user is told their clone path
is wrong when nothing about it is.

The refusal is also narrower than the document describes. The guard block is
inserted only when `transport.relay_enabled` is true
(`generate_forwarder_content`, `:564-627`, step 2), and the default is false.
So C would fire only for an opt-in feature — and on the plain legacy path
the same checkout works today with no interpolation at all.

Loudness is still owed, and B provides it in the right place: a Detector that
goes RED in QA when the generator regresses, rather than an install-time
refusal aimed at the user for a path the code can carry. "Loud where the
defect is" beats "loud at the person who did not cause it".

### Why not D

D records the failure and keeps it. The escaper's docstring exists because
this failure is silent and remote; documenting that a checkout path with `$`
in it runs a command substitution on every daemon-down hook does not make it
less so. Declined.

## What the ruling makes necessary — all of it UNBUILT

1. **Generator (`install/forwarder_generator.py`, `build_relay_guard_block`).**
   Replace `:273` and `:280` with a plain double-quoted assignment of the
   escaped value, then an expansion default that references it by name —
   shape, not exact text:
   `_rl_bin_default="<escaped>"` / `_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-$_rl_bin_default}"`,
   and the same for the fallback events branch. The dynamic events branch
   (`:279`) is untouched: its default word is composed of `$name` references
   only. Update the comment at `:257-260`, which will be false.
2. **The sixth site (`append_nc_socket_arg`, `:558`).** Pass `baked_events_dir`
   through `_escape_for_double_quotes`. Plain context, no shape change; a
   no-op for every realistic value.
3. **Regeneration.** The tracked `.claude/hooks/*` forwarders are generated
   output and are compared byte-for-byte against a fresh generation
   (`test_hook_scripts_match_installer`, via `recorded_untracked_dir`). The 27
   guarded files change shape and must be regenerated and committed in the
   same change as (1).
4. **Tests that pin the old shape.** `tests/unit/install/test_forwarder_generator.py`
   asserts the literal `_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/…}"` line
   at `:403`, `:409`, `:429`, `:825`; the `_GUARD` fixture in
   `test_forwarder_root_normalisation.py:54-59` embeds it; the docstring of
   `test_a_default_value_expansion_still_exposes_a_baked_path` says "it is
   exactly how the relay binary path is baked", which stops being true (the
   scanner rule it tests remains correct and remains wanted).
   `test_guard_block_env_overrides_are_pure_parameter_expansion` (`:432-438`)
   must keep passing unchanged — B adds a builtin assignment, no spawn.
5. **The row.** A `reaches` row for `_escape_for_double_quotes` may be added,
   but its `reason` must say what it proves: that neither function has lost
   every call to the helper. The pair with teeth is
   `append_nc_socket_arg` ↔ `build_relay_guard_block`, which is RED today and
   goes green with (2). The pair the document envisaged
   (`_render_raw_stdout_daemon_down_block` ↔ `build_relay_guard_block`) is
   green today and would be green under any of A–D.
6. **The register.** `AsymmetricSiblingProtection.md:180-202` moves from
   "partially fixed" to fixed only when (1)–(4) and the Detector below have
   landed, and its text should record six sites, not five.

## The Detector's required BEHAVIOUR — home and shape deferred

Where a Defence lives is being ruled on separately
([DECISION-where-a-defence-lives.md](DECISION-where-a-defence-lives.md)).
Whatever that ruling says, the Defence for this instance must do these things,
because nothing weaker distinguishes a fixed site from a raw one:

- **Effect, not call.** Generate the guard block (and the nc-rung call line)
  for an `untracked_dir`, `project_root` and `relay_binary` whose text carries
  each of `$`, `` ` ``, `"`, `\`, `}`, a space and a glob character; execute
  the resulting assignment lines under `bash` (the interpreter the forwarder's
  shebang names) twice — with `HOOKS_DAEMON_RELAY_BINARY` and
  `HOOKS_DAEMON_EVENTS_DIR` unset, and set to sentinels — and assert that
  `_rl_dir`, `_rl_bin` and `_rl_events_dir` equal the intended path,
  respectively the sentinel, byte for byte. This is the proof `reaches`
  cannot give, and it must fail against today's generator (the reproduction
  above is the fixture).
- **Shape over the artefact.** Assert that no `${…:-…}` word in a generated
  block contains an absolute path literal — the invariant B creates and A
  cannot state. `_ABSOLUTE_PATH` already reads the shape.
- **Both branches.** Generate under a root short enough for the dynamic
  events branch and one long enough for the AF_UNIX fallback branch
  (`TestALongRootChangesTheGuardsSHAPE` shows how), so the baked
  `resolved_events_dir` site is exercised, not just `relay_binary`.
- **Red on reversion.** A deliberate re-introduction of a raw
  `${VAR:-{literal}}` f-string must turn it red. If it cannot, it is not the
  Defence.

## What it costs, and who bears it

- **Every install's forwarders change shape once**, at the next regeneration
  — the same event every template change already causes, delivered to
  clients on upgrade. Existing overrides keep their precedence
  (`HOOKS_DAEMON_*` first, then the baked default), so no operator sees a
  behaviour change.
- **Two builtin assignments on the hot path**, one per site. No subshell, no
  spawn; the property `test_guard_block_env_overrides_are_pure_parameter_expansion`
  pins is preserved.
- **Fixture and tracked-output churn** in this repository, listed above. It
  is the routine cost of a generated artefact whose template moved, borne
  once by whoever builds (1)–(4).
- **Nothing for installing projects' refusal surface.** No new deny, no new
  install-time error.

## The strongest argument against, stated fairly

A is the smaller change by every count that shows in a diff: one table entry
or one sibling helper, a class of tests, and a generated artefact that is
byte-identical for every normal install — the very property
`test_an_ordinary_path_is_unchanged` (`test_forwarder_generator.py:387-396`)
was written to protect: "without this, the fix would silently rewrite the
generated forwarder for every existing project". B rewrites it, deliberately.
And the `}` escape is specified by the bash manual, so A is not leaning on an
implementation accident.

The rebuttal is that the property that test protects was about an ESCAPING
fix not changing the artefact — a fix that should be invisible. B is a
template change, which is a normal, visible event with a normal path
(regenerate, commit, ship), and this repository has made such changes before
(Plan 00290 F3, Plan 00364 Task 5.1). What A cannot offer at any price is an
invariant a scan can read off the artefact; it leaves the guarantee resting
on the call graph, where a forgotten call at a future `${VAR:-…}` site looks
exactly like a present one. The diff is smaller; the guarantee is weaker.

## Human gate?

**None remaining.** The question the document reserved for the owner was
whether the failure should be loud (C). The answer is determinate from the
measurements: no path is unrepresentable, so there is no failure for C to be
loud about, and the refusal would land on an opt-in feature for a user who
did nothing wrong. Loudness is delivered by the Detector going red in QA,
which is where the defect is. No installing project's refusal surface
changes.

## Corrections to the decision document, for the record

- Six interpolation sites, not five: `append_nc_socket_arg:558`.
- `resolved_events_dir` carries `$XDG_RUNTIME_DIR` and a hash, not the
  checkout path.
- A `reaches` row is green today and stays green under every option; B does
  not make it meaningful. It guards total regression only.
- A's cost is overstated: a sibling helper needs no caller change.
- C's refusal is narrower than "installing projects": relay-enabled installs
  only, an opt-in with a false default.
- Leaving the two sites wholly raw kept the `$`/backtick execution class live,
  not only the `}` fail-open; the escaper's four rules are all correct in the
  expansion context (measured), so a half-fix would have closed the worse
  class.

With this ruling recorded, the fork is closed; what remains for this instance
is the unbuilt work listed above and the sibling ruling on where the Defence
lives.
