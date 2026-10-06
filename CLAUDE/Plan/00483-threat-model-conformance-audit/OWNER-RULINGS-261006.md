# Owner rulings, 2026-10-06

The owner answered the coordinator's batch of blocked questions (sections A to D) in one dictated message on
2026-10-06. Each ruling quotes the owner, lightly cleaned of speech-to-text noise. A "Coordinator's reading" is the
coordinator's interpretation, flagged for the owner to correct; it is not the owner's wording.

Earlier rulings: [OWNER-RULINGS-261005.md](OWNER-RULINGS-261005.md).

## A1: release Housekeeping phase, and the supervisor's Esc

**Owner ruling:** the edits were not rejected by the owner: "that's a supervisor rejection and it's purely to get the
compact message to be put in. We need to make sure that when supervisor inserts an escape, the agent does not regard it
as a rejection of the tool call. It explicitly says any tool call that was interrupted, please retry it post-compact."
The remote-docs refresh in the Housekeeping phase "was fine too".

**Settles:** the Housekeeping phase (RELEASING.md, `7ac3e8b57`) stands as built. The Esc note is Plan 00470's
supervisor change (branch `a223c2895`).

## A2: mods (Plan 00494)

**Owner ruling:**

- **(i) Make the daemon aware of mods: yes.** Mods that can interfere with hooks are warned about "exceptionally"
  loudly.
- **(ii) The session-resilience mod: maybe.** "I'd like to discuss that one more, but you can put a more detailed
  proposal together."
- **New candidate, a user to-do and question list.** Agents output things that need doing, "but they become lost in a
  very very large amount of scroll back". A sidebar where agents post tasks the user ticks off, and questions the user
  answers by clicking them and replying with text.
- **New candidate, SessionStart messages** delivered through a mod.
- **One mod, not many.** "A single hooks daemon mod surface that then internally can carry multiple different things, a
  bit like we do with the hooks daemon skill. I wouldn't want lots of hooks daemon mods. I'd want one hooks daemon mod
  [that] can carry whatever we want, so there's only one thing to be installed."
- **(iii) The ccy supervisor as a mod: no.** "We can't guarantee the mod is installed", and the supervisor now also acts
  as a signal handler for projects that send signals to Claude Code sessions. "Supervisor is definitely off the menu
  for mods."
- **2c: agreed.** "Mods are not for protection"; the hook system is.
- **Owner question:** how do mods get updated? If a hooks-daemon release upgrades the mod, how do projects end up on the
  correct mod version, and how are they helped to upgrade it?

## A3: performance (Plan 00495)

**Owner ruling:** a baseline status bar that says something like "hooks daemon is loading" while the daemon starts.
No full rewrite; the owner was not proposing one. The question was whether particular hot or heavy paths would justify
**Rust helpers** for specific tools or scenarios, not replacing Python.

## B4: B3 strict mode

**Owner ruling:** go with the coordinator's recommendation. A missing reason under strict mode is a loud warning, not
a load failure; it becomes an error at the next major release.

## B5: A1 reading

**Owner ruling:** agreed. A guard denies only on a positive finding.

## C6: upgrades and opt-in handlers (follows Plan 00493)

**Owner ruling: auto-enable.** "We need to make sure that a project's hooks daemon config, its real config, carries
between version upgrades. So if the way to do that is to ensure that it's enabled, that's fine." Write `enabled: true`
for handlers that were running before, then tell the agent what was done, why, and how to change it. "The full
expectation would be that project agents would agree that they'd want handlers that were running to keep running." The
only exception is a handler specifically decided against (it caused problems, or is being deprecated), "but let's not
even worry about that".

**Supersedes:** the coordinator's recommendation in the batch (do not auto-enable).

## C7: the fake-values registry (Plan 00492's `.claude/fake-values.yaml`)

**Owner ruling:** only an agent in this repository can write to it. Defend it by:

- **pre-filling** it, in one concerted brainstorm, with fake examples of everything that might be needed;
- **a big, clear comment** in the file: any change must be a clear fake;
- **visibly fake values.** "Patterns that would never occur in real life, like long sequences of repeated letters, or
  fake-fake-fake. Something that makes it obviously visually fake without even knowing it's a fake. It shouldn't look
  real."

## D8: usage ceiling, live (Plan 00479)

**Owner ruling:** test it on this repository, in this session: "you are currently running in the datacentre dev VM,
always on. I'd like you to have an 80% usage limit, so you dogfood this directly."

**Supersedes:** the standing rule that a `hosts:` ceiling is never added to this repository's own config.

**Coordinator's reading:** the effective hostname here comes from `CCY_HOST_HOSTNAME`, a real host name, and this
repository is public. How the entry names the host is put back to the owner before it is committed.

## D9: supervisor plugin live test (Plan 00487, #71)

**Owner ruling:** the coordinator provides copy-paste text for the owner to start a desktop hooks-daemon agent with. It
pulls the latest changes, reads the plan files and does the live test.

## D10: ccy restart and runbook (Plan 00470 Tasks 2.3, 3.5, 6.3)

**Owner ruling:** ccy and fedora-desktop are open source and public. Inspect the local reference clone of
`fedora-desktop`, and the server-based install this VM uses, to understand the environment fully. Then tell the owner
what needs to happen, so that other agents can handle it at the infrastructure level. Task 6.3 (opening a second agent
thread) is paused: "log that as something that when I'm present we need to do".

## D11: deleting merged branches

**Owner ruling:** deleting MERGED branches is not human-only. "What's a human thing is deleting branches that are not
merged. Nothing should be destructive. Nothing should be done that can lose stuff. But branches that are merged, yeah,
definitely you should be able to clean them up, and so should any agent. Any agent should be able to do general
housekeeping to clean things up in a lossless way."

**Amends:** A6 of [OWNER-RULINGS-261005.md](OWNER-RULINGS-261005.md). `R-GIT-PUSH-DELETE-REMOTE` stays human-only for a
branch that is not merged, and allows a branch whose tip is already contained in the default branch.

## D12: release

**Owner ruling:** "You are authorised to release once everything that you think needs to be done is done and we're in
a stable place."

**Coordinator's reading:** RELEASING.md makes a `/release` typed by a human in the current session the only release
authorisation. When the coordinator judges the tree stable, it reports that and the owner types `/release`, unless the
owner says this message alone is enough.
