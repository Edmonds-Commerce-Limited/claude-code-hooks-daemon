# Plan 00613 Task 3.4: draft reply to the peer project

**Status**: DRAFT, not sent. The owner sends it.

**To**: the peer project's agent that asked for `worktree-link-secret` (DESIGN
section 1). The repository does not record which project or channel it came
from (DESIGN "Provenance": a peer agent's request). Send it back the way the
request arrived, which the owner knows: the team bus, if that is how it came.

**Before sending**: the route is merged on main here but is NOT in a released
version yet (release notes 009 and 019 sit in
`CLAUDE/UPGRADES/UNRELEASED/`). Either send after the next release, or keep the
"available from the next release" sentence below.

**Owner's choice, open guard gaps**: three read routes through a seeded link
are still not judged. They are ledger 00474 entries N683 to N685: an
interpreter one-liner that walks or copies a tree (`shutil.copytree('.')`,
`os.walk(followlinks=True)`), `fd ... | xargs cat`, and `find ... | parallel cat`. The reply below says that reads are denied "with known gaps" and does not
list them. Add or drop the detail as you see fit.

---

## Reply text

Your request for a verb that links a protected file (your vault password file)
into a worktree has been decided by the owner. The answer is yes, with link mode
only, but not as an agent-invocable verb that takes a path. The project config
decides what is linked. No agent names a path.

Available from the next hooks-daemon release:

1. List the file, or the directory holding it, in the `worktree_create` seed
   list in symlink mode, in `.claude/hooks-daemon.yaml`:

   ```yaml
   handlers:
     worktree_create:
       worktree_create:
         enabled: true
         options:
           seed:
             default_mode: symlink
             entries:
               - path: <your vault password file>
                 mode: symlink
   ```

2. Commit that config change to your default branch, with the main checkout on
   that branch. A protected link entry is placed only when the config committed
   on the default branch lists it. An uncommitted edit, a detached HEAD, or a
   main checkout on a feature branch all refuse it.

3. A worktree Claude Code creates (`isolation: worktree`, `--worktree`) is
   seeded by the creation hook. For a worktree made by hand with
   `git worktree add`, run `bin/hooks-daemon seed-worktree <worktree>`. It takes
   only the worktree, applies the configured list, never overwrites an existing
   destination, and exits 1 with the reason when it refuses.

What stays the same:

- `mode: copy` of a protected file is refused, and worktree creation aborts.
  Move any such entry to symlink mode before upgrading (pre-upgrade task 01).
- A hand-typed `ln -s`, `ln` or `cp` naming the protected path is still denied
  by `R-SECRET-BASH-MENTION`. Use the seed list.
- An agent reading through the link is judged as reading the file itself.
  `Read`, `Edit`, `Grep`, `cat`, and link-following recursive reads
  (`grep -R`, `rg -L`, `find -L`, `tar -h`, `cp -L`) are denied. This was
  verified against a running daemon. A few rarer shapes are known gaps that
  are being worked on.
- Every protected link placed is logged before it is made, in
  `worktree-seed-protected-links.jsonl` (verb `worktree-seed` or
  `seed-worktree`).

Known limits: a write through the link changes the canonical file. A link stays
until its worktree is removed.
