# Callout: the bracket trick must cover every spelling, not just the probe's

**Plan**: 00363
**Audience**: everyone

`self_matching_process_probe` could still deny a `pgrep -f`/`pkill -f`
command after its pattern was already bracket-tricked, with no rewrite to
offer — confirmed against a real `pgrep`: a probe followed by a real
`|| echo "no <name>"` fallback is never exec-optimised away, so the calling
shell's cmdline keeps the FULL command text for the life of the shell, and a
fallback message that spells the target name unescaped keeps the probe
self-matching regardless of the probe's own spelling. That is a genuine
hazard, so the deny still stands — but the message now names the exact text
responsible (`FIX THE OTHER TEXT: ...`) instead of silently repeating advice
already applied. Bracket (or reword) every unescaped spelling of the pattern
in the command, not just the probe's own.
