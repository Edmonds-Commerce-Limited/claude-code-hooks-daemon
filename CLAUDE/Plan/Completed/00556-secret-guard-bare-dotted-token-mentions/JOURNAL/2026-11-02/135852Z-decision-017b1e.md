## 13:58 · decision · —   — #142 option (c) inferred; #141 and #147 progress

**#142 (Task 3.3), N556:** I read the owner's approval as option (c). The owner approved fixing all the secret-guard false positives on condition that every true positive still denies, and did not name an option. This choice is my inference, not the owner's.

Option (c) judges `*`, `**` and `**/*` by the session shell's effective `globstar`/`dotglob` state, read from the Bash tool's shell snapshot. If that state cannot be read, it falls back to today's conservative reading. Why not the others:

- (a) leaves the false positive in place;
- (b) gives up coverage for clients whose profile sets those options.

The brief also tells the agent to fall back to the consistency fix alone if the session's own snapshot cannot be identified reliably.

**#141 (Task 3.2):** fault 1 (awk) merged as 88d63f4b7. Faults 2 (`_text_naming` fallback for a wildcard-only glob) and 3 (heredoc bodies fed to brace enumeration) are building under the same approval, with N555's proposed shape. The coordinator added a condition: a heredoc body fed to a shell (`bash <<'EOF'`, `cat <<'EOF' | sh`) is still judged, because it is executed.

**#147:** part 1 merged as 5db9e8534. Part 2, the remaining hard-coded wrapper paths, is building.
