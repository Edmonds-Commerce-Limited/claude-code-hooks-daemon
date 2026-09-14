# Callout: a gate you switched off is no longer announced as policy

**Plan**: 00390
**Audience**: everyone

The `<hooksdaemon>` block in your `CLAUDE.md` promises the reader two things in
its own headings: that the handlers listed are "active in this project", and
that the table holds "All other **enforced** rules". A handler that is loaded
and enabled but switched off by a config key satisfied neither, and was listed
anyway — with its rule's Why column stating the policy as present-tense fact.

`plan_close_approval` is the case that bit. With
`plan_workflow.close_requires_human_approval` at its default `false` the
handler's `matches()` returns `False` before doing anything else, so it can
never fire. The generated table still carried:

```text
| R-PLAN-CLOSE-APPROVAL | ... | This project requires a human to close a plan; the daemon enforces that ... |
```

An agent reading its own instructions has no way to tell that apart from a
project that really does require it. In this repository one did exactly that:
two finished plans sat open for days waiting on an `approve-plan-close` that
was never needed, and the belief was written into both plan documents as fact
before anyone checked the key.

**What changes.** A handler can now report `is_dormant()` — an optional
protocol, defaulting to active — and the CLAUDE.md generator leaves a dormant
handler out of the block entirely: no rule row, no advisory line. The default
is deliberately "active", because most handlers gate on their INPUT rather than
on config, and input-gating cannot be decided when the document is written.

Both shipped approval gates now report it: `plan_close_approval` and
`merge_to_main_approval`. **If your project leaves either key at its default,
those rows will disappear from your `CLAUDE.md` on the next restart.** Nothing
about enforcement changed — the rows were describing a gate that was already
switched off. If you turn a key on, the row comes back.

`.claude/HOOKS-DAEMON.md` was checked and deliberately left alone. Its handler
table is a listing of what is LOADED, and its description already reads "while
the key is on" — a conditional a reader cannot mistake for policy.
