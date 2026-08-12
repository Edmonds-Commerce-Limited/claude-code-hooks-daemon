# README change requests (as received)

Cold-reader review of the README against v3.51.0. Tracked here as a
supporting document for Plan 00215 rather than inlined into PLAN.md.

The source document ended with a section marked NOT FOR EXPORT, concerning
a different project's positioning. It is deliberately omitted -- the cut is
made at that marker and nothing after it is reproduced here.

---

# claude-code-hooks-daemon README — change requests

Read against v3.51.0. The test a cold reader applies: *someone follows a link to this repo,
knows nothing about the project, and gives it ninety seconds.* Today that reader leaves
knowing it is a faster way to run Claude Code hooks, and not knowing what it is **for**.

Everything below is what to change. Everything not listed is fine as it is.

## The one structural problem

**The README answers "why a daemon?" and never answers "why guardrails?"**

`## Why Use This?` is four hundred words, and every one of them is about iteration speed for
hook authors — restart the daemon, not the session; write handlers in Python, not shell. All
true, all worth keeping. But it is the answer to the *second* question. The first question is
why an autonomous agent needs blocking rules at all, and the README never puts it in a
sentence. The word "safety" appears exactly once, as a priority-band label above a list of
what gets blocked.

So the reader infers the category from the evidence available and files it under developer
ergonomics.

## 1. Replace the strapline

Current, immediately under the badges:

```
A better way to build and maintain Claude Code hooks.
```

That is a category, not a claim. Replace with:

```
Guardrails for coding agents — containment, policy enforcement and quality gates,
evaluated on every tool call before it runs.
```

## 2. Add a "What this solves" section directly beneath it

New section, before `## Installation & Updates`:

```markdown
## What this solves

A coding agent with shell access will eventually run the command nobody thought to forbid.
Not maliciously, and usually mid-way through doing exactly what was asked: a `git reset
--hard` to tidy the tree before committing, a `sed -i` across forty files that mangles
thirty-nine, an API key pasted into source because it was the shortest path to a green test.

Claude Code exposes hooks — points where an external program inspects a tool call and
allows, blocks or annotates it. That is the right mechanism, and it is underused, because
each hook is a separate program spawned per event and changing one usually means restarting
your session. Most projects write two or three and stop.

This daemon makes handlers cheap enough to write a hundred of. Lightweight forwarder scripts
— one per event — pass events over a Unix socket to a long-lived Python process holding
every handler in memory. The hundredth handler costs almost nothing at runtime, and the
daemon restarts in under a second without touching your session.

**The enforcement is deterministic.** A handler is a function returning allow or deny — not
a prompt, and not a judgement the model makes about its own behaviour. It cannot be reasoned
with, and it decides the thousandth call exactly as it decided the first. For the failure
that actually matters — the destructive command issued confidently and in good faith — that
is the property you want.
```

## 3. Move Installation below it

Current order puts `## Installation & Updates` — two `curl` blocks — above `## Why Use This?`. A returning user loses nothing by scrolling one section; a first-time reader
currently meets install commands before learning what is being installed.

Order: strapline → What this solves → Why a daemon (existing `Why Use This?` content,
retitled) → What's Built In → Installation & Updates → everything else unchanged.

## 4. Retitle and trim `## Why Use This?`

Retitle to `## Why a daemon rather than plain hooks`. Keep all five sub-headings. With
section 2 above it, this section is now answering the question it actually answers.

## 5. Add the origin, in one line

⬜ **Needs the real detail — do not draft this without it.** The strongest available line is
that the project was started after an agent did something destructive that no existing tool
would have stopped. One factual sentence naming what happened, at the end of "What this
solves", is worth more than the rest of this document. Invented specifics would be worse
than nothing.

## Factual corrections

### 6. "Five hooks" is wrong and contradicts the same README

```
When installed, your project has just five Claude Code hooks — one per event type.
```

There are **31** forwarder scripts in `.claude/hooks/`, and `## What's Built In` says "15
event types" three sections further down. Replace "just five Claude Code hooks — one per
event type" with "one lightweight forwarder per event type".

### 7. The test badge is not the number to lead with

The badge claims `tests-10800+passing`. That is pytest's collected count and it is correct —
parametrised tests expand at collection. But a reader who greps `def test_` finds **9,888**
and concludes the badge is inflated.

Add the ratio alongside it, because it has no such gap and it is the more interesting fact:

```
63,509 lines of source, 145,073 lines of tests — the test tree is 2.3× the size of the
thing it tests.
```

Both figures are one `find` each and neither moves much between releases.

### 8. Promote `## Deterministic vs Agent-Based Hooks`

It currently sits tenth. It states a real design boundary — what this is for and what it is
explicitly *not* for — and it is one of the best things on the page. Move it directly after
`## What's Built In`. A tool that says plainly what it does not do reads as built by someone
who knew where the edges were.

## Smaller items

- `## What's Built In` lists five categories but the priority bands in `## Writing Custom Handlers` list six — `56–79 Advisory` has no corresponding section above. Add it or drop
  the band.
- The `Requirements` section is at position 12. Python version and OS support are things a
  cold reader checks in the first thirty seconds. Move it up, or add the two facts to the
  badge row.
- `MIT License — Copyright © 2024–2026 Edmonds Commerce` is the only place the maintainer is
  named, at the very bottom. A one-line author credit near the top with a link is normal and
  currently absent.

## Leave alone

- The handler counts (`92 production handlers across 15 event types`) — generated at release
  from live config, so let that process own them.
- All installation and upgrade command blocks, including the warning about hand-building the
  venv.
- `## Project-Level Handlers`, `## Writing Custom Handlers`, `## Configuration`,
  `## Git Integration` and `## Troubleshooting` — accurate, well-scoped, and doing their job.
- The status-line example block. It shows rather than tells.
