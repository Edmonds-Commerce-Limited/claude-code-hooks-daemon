# Decision request: the two `${VAR:-default}` interpolations

**Status**: DECIDED — option B endorsed, option C declined; ruling and the
unbuilt work it implies in
[fable-forwarder-interpolation-decision.md](fable-forwarder-interpolation-decision.md).
Nothing is implemented yet: three sites are fixed; these two are not,
deliberately.

Context:
[DESIGN-declared-invariant-pairs.md](DESIGN-declared-invariant-pairs.md),
[the security register](../../Security/AsymmetricSiblingProtection.md).

## What was fixed, and what was not

`build_relay_guard_block` in `install/forwarder_generator.py` interpolates
variable values into a generated shell forwarder. The worklist recorded this as
one defect — "unescaped interpolation" — and reading the site showed it is
**three different quoting contexts**, not one:

| Site                               | Context                                            | `_escape_for_double_quotes` |
| ---------------------------------- | -------------------------------------------------- | --------------------------- |
| `deployed_hooks_dir(project_root)` | quoted literal before an unquoted `*`              | correct, applied            |
| `untracked_dir`                    | plain double-quoted string                         | correct, applied            |
| `event_file_name`                  | plain double-quoted string, internal catalogue key | correct, not needed         |
| `resolved_events_dir`              | inside `${VAR:-default}`                           | **insufficient**            |
| `relay_binary`                     | inside `${VAR:-default}`                           | **insufficient**            |

The escaper's table is `\`, `"`, `$`, `` ` `` — the plain double-quoted case.
That is exactly right for the first three and **incomplete for the last two**,
because a `}` inside `${HOOKS_DAEMON_EVENTS_DIR:-/some/path}` terminates the
expansion early and the remainder becomes literal text. The escaper has no rule
for `}`.

## Why this was not just "apply the helper everywhere"

Applying it uniformly would have produced a forwarder that is still wrong for a
path containing `}`, while every signal said it was fixed:

- the `reaches` row would be **green**, because the row asserts the function
  CALLS the helper and it would;
- the register would list the instance as fixed;
- no test would object, because no test uses such a path.

This is the blind spot recorded the day before the fix — *`reaches` proves a
call, not an effect* — arriving on the very next row. It is the reason the row
for this pair has **not** been added: a row that can be satisfied by a partial
fix is worse than no row, because it converts an open defect into a closed one
on paper.

## The fork

**A. Extend the escaper with a context argument.** One helper, two tables:
double-quoted, and parameter-expansion-default. Honest, and it makes the
context explicit at every call site.
*Cost*: every existing caller gains an argument; the helper stops being the
one-line thing its docstring describes.

**B. Stop interpolating into `${VAR:-default}` at all.** Assign the default to
a plain shell variable first, then expand:
`_rl_default="/some/path"; _rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-$_rl_default}"`.
The value then sits in a plain double-quoted string, where the existing escaper
is already correct and already proven.
*Cost*: two extra lines in the generated forwarder, on a hot path that runs on
every hook invocation when the daemon is down. Two variable assignments are
nothing, but the forwarder is deliberately minimal.

**C. Reject the path at install time.** Refuse to generate a forwarder for a
checkout whose path contains a character that cannot be safely embedded, and
say so loudly.
*Cost*: a new refusal in installing projects, which is why this one is squarely
an owner call and not something to slip in. It is also the only option that
tells the user something is wrong rather than silently coping.

**D. Accept and document.** Record that a project root containing `}`, `` ` ``
or `$` is unsupported, and move on.
*Cost*: the failure stays silent and remote, which is the exact thing the
escaper's own docstring exists to prevent.

## Recommendation

**B, then a row.** It removes the awkward context entirely rather than teaching
the escaper about it, reuses a helper already proven correct for the resulting
context, and needs no new refusal. Once all five sites sit in one context, the
`reaches` row becomes meaningful instead of satisfiable-by-halves, and it can be
added with the instance.

**C is the better answer if the owner wants the failure to be loud**, and that
is a legitimate preference rather than a worse one — but it adds a refusal in
installing projects, which is not mine to add.

## What is true today

Three sites escaped, two not, no row for this pair, the instance recorded in the
register as partially fixed with this document named. Nothing is claimed to be
closed that is not.
