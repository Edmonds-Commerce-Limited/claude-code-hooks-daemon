## 15:36 · decision · —

Review 614c fix round, decisions so far:

- P2 GREEN: the glob rows of the committed RED test (`cat o*/*`, `head -n1 own/*` after a brace expansion past the cap) asserted the gave-up cause text. They are denied, but by the literal fallback, which already matches those globs against the index and names the protected pattern. The test was split: the search rows still require the gave-up cause, the glob rows require DENY only. No decision was loosened.
- N1: the bounded link scan behind a computed cd now also returns each directory link (renamed `computed_move_directories`), in both cwd walkers.
- Merge of main (Plan 00618, which carries Plan 00615's directory readers): recursive_search keeps this branch's multi-directory walk and ports main's additions into it; main's `expand_tilde` (every shell-state tilde fails closed) replaces this branch's `_expand_tilde` because it is stricter. secret_file_matching keeps this branch's walker, which already reads `git -C` as a move; main's git -C helpers used only by the replaced loop are dropped.
- Plan 00615 (find -exec / xargs reads) landed on main through Plan 00618, so it is not built here.
