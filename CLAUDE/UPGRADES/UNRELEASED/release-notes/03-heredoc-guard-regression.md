# Callout: a v3.64.0 regression let destructive git commands through a heredoc

**Plan**: 00409
**Audience**: everyone

**Upgrade if you are on v3.64.0.** That release stopped denying five
destructive `git` spellings when they were written as `bash <<'EOF' … EOF`.
The quoted delimiter governs only what the OUTER shell expands on the way in —
it never stops the receiving interpreter from running the bytes — but the
command text was blanked before the guards judged it, so every guard saw an
empty command and allowed it.

Measured rather than argued: the shipped v3.63.0 module was recovered from its
tag and run side by side with v3.64.0's. v3.63.0 denied all five spellings;
v3.64.0 allowed every one. This was a regression introduced in v3.64.0, not a
pre-existing gap, so v3.63.0 and earlier are unaffected.

Now fixed: a heredoc body is exempt from scanning only when nothing on its line
can EXECUTE it. `cat`, `tee`, `git` and similar consume their input as data and
keep the exemption; `bash`, `sh`, `python3`, `ssh` and anything piped onward do
not, and their bodies are scanned like any other command.
