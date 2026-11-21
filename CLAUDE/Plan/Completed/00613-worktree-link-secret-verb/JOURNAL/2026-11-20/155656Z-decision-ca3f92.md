## 15:56 · decision · —

Read gap closed and residual 1 narrowed (builder's decisions).

Read gap: `utils/link_reach.py` judges what lies behind every link below the root of a recursive read, wired into `recursive_search.protected_reached` (so the secret guard and the quarantine-artefact guard both inherit it). Links come from the verified Plan 00623 link index when the root is in the project and the index is complete, else a bounded walk (4096 directories, 4096 links, 2 s). A directory link goes to `find_under`, which fails closed for a target outside the project; a file link is judged by the index and the protected globs anchored at the project root. Anything unresolvable, past a cap or the deadline denies. The seed audit log was NOT used as the source: it is agent-writable.

Follow modes: every reader is assumed to follow every link unless its words prove otherwise. Proven NONE: grep-family without R (ugrep: R/S) or a dereference/follow long option or abbreviation; rg without -L/--follow; ag without -f/--follow; index-view git grep. Proven FILES: find without -L/-follow. An uncertain option parse, RIPGREP_CONFIG_PATH, GREP_OPTIONS, or a function/alias definition in the command proves nothing. The Grep tool (ripgrep, no follow) is not expanded.

Residual 1: chose "a protected link entry must be listed in the config committed at HEAD of the main checkout" over a session-start baseline, because HEAD is readable by the CLI with no daemon state and an agent cannot change it without leaving a commit. Protection is judged by the union of the working and committed protected sets, so un-protecting a path in the working config does not ungate it. Unprotected entries are not gated. This narrows the route (an agent that commits the edit still passes); it does not close it.

Release note renumbered 016 to 018 (016 used on another branch, 017 on another; 018 free on every local and remote ref).
