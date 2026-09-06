# Plan 00335 Decisions

## Decision 1: invert the quoted-heredoc exemption to a sink allowlist

**Task 1.1.** The plan offered two directions and required they be decided
together. The decision is the **inversion**, and it subsumes the narrow fix
rather than competing with it.

### What was decided

`curl_pipe_shell` grants the quoted-heredoc exemption **only when every
heredoc's receiving command is a recognised NON-EXECUTING data sink**
(`_DATA_SINKS`). Previously it withheld the exemption only when a receiver
matched a list of known interpreters/executors, and granted it otherwise.

The failure direction flips: an unrecognised receiver now WITHHOLDS the
exemption (the body is scanned) instead of GRANTING it (the body is blanked
and the handler sees nothing).

### Why, and what changed the answer

The review framed this as a trade — safety against a growing allowlist, "each
omission costs a false denial" — and left it as an owner's call. Probing the
shipped handler before deciding (`probes/probe_phase1.py`) showed the trade is
much less balanced than that framing suggests, for two reasons.

**First, the enumerate-the-bad-guys design has a live bypass the review did
not find.** `ssh host <<'EOF'` was ALLOWED. `ssh` executes the heredoc body on
the remote host, so this is the same class as B2's `eval`/`. /dev/stdin` — a
receiver that executes without naming an interpreter. It was not on either
list, so the body was blanked and a `curl … | bash` payload passed a
priority-10 terminal RCE guard. Finding a fourth member of a family that had
already yielded three is the strongest available evidence that the family
cannot be enumerated.

**Second, the inversion closes the residue the plan recorded as unclosable.**
Non-Goals originally excluded the word-expansion family (`b$'ash'`, `$SHELL`,
`${SHELL}`) on the reviewer's reasoning: it is unbounded, so no finite
normalisation closes it. That reasoning is correct *for an allowlist of bad
receivers* and irrelevant to an allowlist of good ones. `b$ash` and `SHELL`
are simply not in `_DATA_SINKS`, so they withhold like any other unrecognised
word — no normalisation required, and the unboundedness now works in the
guard's favour. Verified: both DENY after the change.

**The false-denial cost is far smaller than "each omission costs a false
denial" implies.** Withholding the exemption does not deny the command; it
means the body is *scanned*. A denial follows only if the body ALSO matches
`curl|wget … | interpreter`. So an omission from `_DATA_SINKS` bites only for
a heredoc that both uses an unlisted receiver and contains the anti-pattern in
its body. The common documentation case (`cat > doc.md <<'EOF'`) keeps its
exemption because `cat` is a sink.

### What this does to the narrow fix

The `jq -r . <<'EOF'` over-block disappears by construction rather than being
fixed separately. It existed because `.` (the sourcing builtin) was matched
against EVERY word of the receiving segment, and `.` is also jq's identity
filter. Under the inversion the receiving command is identified by its own
command word — `jq`, which is a sink — and its arguments are not consulted at
all. The proposed "consider `.` only in first-word position" fix is therefore
not implemented: there is no longer a bad-word list for `.` to be on.

This is exactly the interaction the plan predicted: implementing the narrow
fix first would have been discarded here.

### Consequences accepted

- `_DATA_SINKS` must grow when a legitimate data-heredoc receiver is missing.
  Kept deliberately tight; `sed` and `awk` are EXCLUDED despite being ordinary
  filters, because `sed -f -` and `awk -f /dev/stdin` execute the body as a
  program and `sed`'s `e` flag can reach a shell. `crontab -` is excluded for
  the same reason with a delay: it installs commands that execute later.
- `sudo` is skipped when resolving the command word, so `sudo -E tee f` reads
  as `tee`. This does not weaken anything: `sudo -E bash` resolves to `bash`,
  which is not a sink and still withholds.
- The interpreter and executor receiver checks are REMOVED rather than kept as
  belt-and-braces. Keeping them would have preserved the `jq` over-block and a
  second one (`cat > bash.txt <<'EOF'`, where the prefix match on `bash`
  fires), and they are fully subsumed: anything they caught is not a sink.

### Rejected: keep enumerating executors

Rejected because the enumeration has now failed four times (`eval`,
`. /dev/stdin`, `source /dev/stdin` at B2; the seven punctuation shapes at B3;
the six expansion spellings recorded as a limit; and `ssh`, found here). Each
round closed the shapes someone thought of. The sink list can be wrong too,
but its errors are false denials that surface immediately and loudly, not
silent grants.
