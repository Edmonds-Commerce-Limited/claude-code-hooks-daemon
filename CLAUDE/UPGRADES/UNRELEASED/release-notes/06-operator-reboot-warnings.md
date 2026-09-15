# Callout: the host can now warn a running session before it reboots

**Plan**: 00417
**Audience**: operators

Interactive sessions run in a container on a machine that operators and
automated patch cycles reboot. Nothing told the agent: work in flight was cut
off mid-step, uncommitted changes were lost, and the next session re-derived
where things stood. `bin/hooks-daemon signal` closes that gap, delivering a
warning through the ccy supervisor when Claude is next idle:

```bash
bin/hooks-daemon signal reboot-warning --minutes 10 --all-sessions
bin/hooks-daemon signal shutdown-warning --minutes 5
bin/hooks-daemon signal reboot-cancelled
```

The agent is told to commit and push, journal where it got to, finish the
current step and start nothing new. `shutdown-warning` additionally asks for a
handoff entry, because no session restore follows one.

**The channel carries no free text, deliberately.** This is the only signal
family writable from outside the container, which makes it a prompt-injection
surface by default, so it is built closed rather than validated: the payload is
at most a positive integer, and the wording the agent reads lives in the
supervisor, in code, under test. A signal's `kind` selects one of three
pre-written sentences and `minutes` is the only value ever interpolated. At
worst a forged signal makes an agent commit its work and pause.

Wire it into your host's shutdown path — a `systemd` pre-shutdown unit or the
`molly-guard`-style hook you already run — and the sessions on that box get the
warning your other services already do.
