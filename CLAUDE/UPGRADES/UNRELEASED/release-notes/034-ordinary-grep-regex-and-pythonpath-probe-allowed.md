# Callout: a grep regex inside `bash -c` and a `PYTHONPATH=... python -c` probe are no longer denied

**Plan**: 00474
**Audience**: everyone

Two ordinary commands were denied without any positive finding. `secret_file_guard` read a grep or rg pattern inside a single-quoted `bash -c '...'` program (for example `grep -E "^(src|tests)/.*:[0-9]+"`) as a glob that could match a protected dotfile, because the program string was never segmented the way a top-level command is; the pattern operands of grep, rg and echo inside a single-quoted `bash`/`sh`/`dash`/`zsh`/`ksh -c` program are now text, to three layers of nesting. A grep whose FILE operand names or globs to a protected path, and a double-quoted or non-shell (`python -c`) program, are judged exactly as before.

`upgrade_approval_guard` denied `PYTHONPATH=<src> python -c "..."` as a bypass of the upgrade approval although nothing in it is an upgrade: a `-c` program was always "cannot tell", which counts as the upgrade once the command carries a steering variable. A literal `-c` program is now judged by what it names: it is the upgrade only if its text names `upgrade.sh`, `upgrade_version.sh`, `upgrade_gate_standalone.py`, `--project-root` or the `.claude/hooks-daemon` clone. A program the shell expands (`"$CODE"`, a backtick) or one with no text still counts as the upgrade when steered.
