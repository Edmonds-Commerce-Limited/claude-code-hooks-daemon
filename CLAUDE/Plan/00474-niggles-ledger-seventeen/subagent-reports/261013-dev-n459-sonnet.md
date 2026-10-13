# N459 report: wrapped status line shows an ellipsis for context

## Cause (probable, not proven end to end)

Evidence gathered:

- No daemon handler writes "..." for context, so the ellipsis is not daemon text.
- Rendering through `HookResult.to_json("Status", terminal_columns=N)` with a realistic segment set gave row widths
  of 78 at COLUMNS=80 and 99 at COLUMNS=100 (53 at 60): rows are packed to within 1-2 columns of the full terminal,
  i.e. zero margin.
- The context figure is the tail of the `model_context` segment ("... | ◔ 12%"), so when a row is cut at its right
  edge the context figure is what goes.
- Vendored `remote-docs/code.claude.com/docs/en/statusline.md`: `padding` is "in addition to the interface's built-in
  spacing"; notifications share the status line row outside fullscreen, and "on narrow terminals, these notifications
  may truncate your status line output". COLUMNS is the whole terminal, so usable width is smaller than COLUMNS.

Ruled out: display-width miscount of the context glyphs (◔◑◕● are width 1 in `_display_width`; the packing check above
shows rows within COLUMNS by the daemon's own count); an oversize single segment (context segment is about 25 columns).

Not proven: no live Claude Code render was available, so the exact number of columns Claude Code reserves is unknown
(the docs give none). `terminal_columns` forwarding from COLUMNS was not re-verified in a live wrapper run.

## Fix

`STATUS_WRAP_MARGIN = 8` in `core/hook_result.py`; `to_json` packs rows to `max(1, terminal_columns - 8)`. Segments are
still never split. The 8 is a conservative allowance, documented as not measured.

Tests (red first, new import failed before the constant existed): `TestHookResultStatusWrapMargin` in
`tests/unit/core/test_hook_result.py` (no row reaches the edge, context segment intact at 40-200 columns, margin larger
than the terminal still emits every segment). Existing wrapping tests had their widths offset by the margin.
`tests/unit/core/test_hook_result.py` and `test_input_schemas.py`: 150 passed.

Docs: `CLAUDE/Architecture/StatusLine.md` wrapping section. Release note 055.
