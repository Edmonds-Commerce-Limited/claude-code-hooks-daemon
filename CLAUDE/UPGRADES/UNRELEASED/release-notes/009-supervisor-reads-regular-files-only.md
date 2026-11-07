# Callout: the ccy supervisor no longer hangs on a FIFO in a signal directory

**Plan**: 00474
**Audience**: client projects

The ccy supervisor globs its signal directories (goal, compaction, usage-pause, session-modes, standing-auth, session-actions, model-switch, model-downgrade, operator and context sidecars) and `/proc`, then reads each entry it finds. A FIFO there made the read block in `open` for ever, hanging the supervisor tick. Socket and device entries were opened the same way. Every such read now opens non-blocking and reads only when the descriptor is a regular file. Anything else is treated as an unreadable entry, as a malformed file already was. A client QA rule that flags directory walks opening non-regular files (fedora-desktop's walk-opens-non-regular-file, their issue #191) no longer finds instances in the deployed `.claude/ccy/claude-supervise.py`.
