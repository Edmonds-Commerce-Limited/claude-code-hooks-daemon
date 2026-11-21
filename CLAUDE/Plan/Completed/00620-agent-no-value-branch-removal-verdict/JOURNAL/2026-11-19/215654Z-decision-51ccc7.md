## 21:56 · decision · — — Bundle directory pinned to the main checkout; keep history keyed on the work

Two additions to RULINGS.md after a review of the 21:52 rulings, settled by a fable sub-agent under the owner's delegation, 2026-11-19 (not the owner's own words; the owner may overturn them).

Q8: the bundle directory is always resolved against the repository's main checkout, never the worktree the command runs in. Agents work in linked worktrees that are removed afterwards; a bundle written inside one would be lost with it, and the "nothing is lost" proof rests on that file. The guard refuses when it cannot resolve the main checkout. Slice 1 gains a test for a run from a linked worktree.

Q5: the keep history is keyed on the work as well as the name. A request whose inventory shares any unique commit with an earlier keep verdict's inventory is a re-review of that verdict, so a renamed branch gets no fresh start. Slice 1 gains a test for it.
