# Callout: `root_recursion_guard` now runs before `secret_file_guard`

**Plan**: 00483
**Audience**: everyone

`root_recursion_guard` now runs at priority 13 (it was 16), ahead of `secret_file_guard` at 14. A recursive search rooted at `/`, `/proc`, `~`, `$HOME` and the like is denied by the root-recursion guard on the command text alone, with its own guidance and its `MUST_SCAN_ROOT_BECAUSE` escape hatch, instead of being walked by the secret guard first. If you disable `root_recursion_guard`, the secret guard still judges such a search as before.

The upgrade moves a config that still carries the earlier example's 16 to 13, because it merges your customisations onto the new example. A config that set any other priority keeps it; set it below 14 to get the new order.
