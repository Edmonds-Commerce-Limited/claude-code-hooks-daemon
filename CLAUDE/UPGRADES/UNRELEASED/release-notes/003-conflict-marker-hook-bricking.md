# Callout: a merge conflict can no longer brick a session through the daemon's hook files

**Plan**: 00552
**Audience**: operators

A merge, rebase or stash pop that conflicted on a hook stub or `.claude/init.sh` used to leave `<<<<<<<` markers in a bash script. The script failed to parse and exited 2, which Claude Code reads as a block, so every event was blocked, including UserPromptSubmit, and the session could not take a prompt.

Two changes close this, and both reach an existing client on its next upgrade:

- **Stubs fail open when `init.sh` does not parse.** Each deployed stub now runs a `bash -n` check on `init.sh` after the relay hot path and before sourcing it. If the file is broken, the stub exits 0 with a non-blocking message naming the file (JSON events carry it in `systemMessage`; the status line prints a display line; worktree-create writes it to stderr and exits 1). The check costs about 10 ms against a 3 ms bash spawn floor, and only hooks that miss the relay pay it. A stub that itself holds markers still cannot parse; the next change prevents that.

- **A managed `.gitattributes` block.** Install and upgrade now write (or update in place) a block in the project root `.gitattributes` that sets `-merge` for `.claude/hooks/**` and `.claude/init.sh`. A conflict on those files then keeps your side of the file intact with no markers, and git still reports the conflict. The block sits between `# BEGIN claude-code-hooks-daemon managed block` and `# END claude-code-hooks-daemon managed block` comment lines; your own lines outside it are never touched and a re-run changes nothing. **Commit the new `.gitattributes`.** `.claude/settings.json` is deliberately not covered, because it holds project-owned entries and `-merge` would silently drop a side of a real edit; use `reconcile-settings` to re-add missing registrations. The daemon repository's own self-install does not get the block.

- **New verb `repair-install`.** `.claude/hooks-daemon/bin/hooks-daemon repair-install` restores a broken install from a terminal, with no Claude session and no running daemon. It redeploys the hook stubs and `.claude/init.sh` from the installed daemon's templates (the installer's own generator, so the parse guard is included), runs `bash -n` on every one and reports each `OK` or `BROKEN`, and checks that `.claude/settings.json` parses. It exits non-zero while anything is still broken. `--check` reports without writing. `settings.json` is only ever rewritten with the explicit `--reconcile-settings` flag, and a file carrying conflict markers is never overwritten: resolve it by hand. The stub parse-guard message now names this command. See the recovery section of `docs/guides/TROUBLESHOOTING.md`.

If a conflict does leave a kept-ours stub or `init.sh` that is older than the merged branch, run `repair-install` (or re-run the upgrade) to redeploy them.
