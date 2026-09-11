# Callout: `transport on`/`off` now establish the state they report

**Plan**: 00383
**Audience**: operators

`transport on` and `transport off` decided they had nothing to do by reading
`daemon.transport.relay_enabled` in your config, and returned before looking at
anything else. The deployed forwarders under `.claude/hooks/` were never read,
so they could never be repaired.

That made the report a claim about your CONFIG while you had asked about your
TRANSPORT. A project whose config said `relay_enabled: false` beside forwarders
still carrying the relay hot path was told:

```
transport off: relay already disabled — nothing to do
```

exit 0 — with every hook still routing through the relay.

**A config match now converges the deployed state instead of assuming it.** If
the forwarders disagree with the config, they are regenerated, the daemon is
restarted, and the result is verified with the same probes a real flip uses.
The message says so rather than claiming nothing happened:

```
transport off: relay already disabled in config, but the deployed forwarders
had drifted — regenerated, daemon restarted, verified
```

**A converged project still pays nothing** — no write, no restart, no probes.
The detector is the repair: forwarder regeneration writes a file only when the
generated content differs from what is on disk, so "check" and "fix" are the
same pass and the common case touches nothing.

**A failed reconcile does NOT auto-revert.** A real flip reverts to the config
state it moved away from. Here the config never moved, so the only state to
restore is the drift being repaired — reverting would reinstate the defect. The
failure is reported and the repaired forwarders stay in place.

**Enabling is gated on the relay binary first.** A regenerated hot path names
that binary, so reconciling in the `on` direction without provisioning would
deploy a forwarder pointing at something that is not there.

**If you SCRIPT the toggle, note the exit code can now be non-zero where it was
always 0.** Repeating the current state used to exit 0 unconditionally, because
it checked nothing. It now reports the truth: if your deployed state is broken,
repairing it and failing verification exits 1. That is the point of the change,
but a script that treated `transport off` as an unconditional success will
start seeing failures it previously could not see. Nothing inside the daemon
invokes the toggle — it is operator-invoked only — so this affects your own
automation if you have any.

**How config and forwarders drift apart in the first place** — no one has to do
anything strange: an interrupted toggle, a hand-edited config, a `git checkout`
that moves one and not the other, or an upgrade that redeploys forwarders. If
you have ever run `transport off` and doubted it, run it again; it will now
tell you whether there was anything to repair.

`transport status` is unchanged and still only reports — it never mutates.
