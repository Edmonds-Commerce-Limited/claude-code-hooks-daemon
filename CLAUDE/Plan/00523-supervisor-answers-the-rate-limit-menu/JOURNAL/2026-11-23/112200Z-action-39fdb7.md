## 11:22 · action · —

A review pass on the pre-fill hold found a gap, fixed in `e287c1052`.

The hold was skipped while the occurrence was still open. But the Enter sets phase answered before the occurrence closes, and the closing redraw sends an empty dump just as the pre-fill appears, so a restore could still be typed onto the pre-fill. The hold now applies in answered or cleared whatever the occurrence state is.

Two tests were added:

- the answered dialog still closing;
- a transcript `> continue` above an empty box, which must not hold anything.

The new closing test was written after the fix, so it was never seen failing; by the logic, the old code would have let the restore through.

Also in that commit:

- doc corrections (the pre-fill is there from the answer onward; the state file is ignored after a day);
- Claude Code's own auto-continue listed as a known limit;
- release note 025 cut down to the README schema.

Checked:

- 540 passed on the nine-file supervisor set.
- ruff, black and mypy are clean.
- There are no daemon config keys or truth changes. The switch is a ccy environment variable, and the feature is new behaviour.
