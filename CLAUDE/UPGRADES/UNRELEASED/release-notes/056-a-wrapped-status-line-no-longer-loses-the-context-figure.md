# Callout: a wrapped status line no longer loses the context figure

**Plan**: 00474
**Audience**: client projects

On a narrow terminal the status line showed an ellipsis where the context percentage should be. The daemon packed each row to the full terminal width, but Claude Code renders the status line inside its own spacing and shares the row with notifications, so it cut the end of the row, which is where the context figure sits. Rows are now packed 8 columns narrower than the terminal (`STATUS_WRAP_MARGIN`), so the figure stays visible and the line wraps one segment earlier instead.
