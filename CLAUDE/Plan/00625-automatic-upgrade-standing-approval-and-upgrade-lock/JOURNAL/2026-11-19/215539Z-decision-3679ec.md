## 21:55 · decision · — — Six open points settled by a fable sub-agent under the owner's delegation

The six open design points are settled by a fable sub-agent under the owner's
delegation. None of this is the owner's own words, and a later owner message
can overturn any of it. The owner's request in the session was to do the
automatic upgrade as well, and to have a fable sub-agent settle the points and
make sure it is safe and secure.

1. Default ON for existing installs: safe, because no key ships and an
   unattended run refuses without a key a human added and committed. The key
   is the consent. Conditions added: opt-out enforced in the entry script, a
   24 hour soak from first sighting, one attempt per release, a once-only
   notice shown with or without a key.
2. Trust model: `.claude/hooks-daemon-release-signers` in the project, tracked
   and identical to HEAD, empty until a human runs `hooks-daemon release-signers add` in a terminal. The key is never taken from a tag, a
   release or the repository host. Rotation and revocation only by the human
   step; an expiry date is not revocation.
3. Every script that runs unattended is the installed version's or
   byte-identical to the verified tag's; Layer 2 is bound to the verified
   commit id; no fetch from main.
4. A question knowable before deploy stops the run before deploy (a
   `Requires human` field read by the gate); one met after deploy is left
   undone and recorded in a file reported every session.
5. Dirty refusal limited to the upgrade-owned paths, the signers file and the
   clone; the commit names its paths; retry only at a later session start.
6. One injected line of at most 300 characters, and nothing injected while
   there is no usable key.

Rulings, threat model and required tests: DESIGN.md sections 11a, 12, 13.
Reasoning: subagent-reports/261119-fable-settle-and-threat-model.md.
