# Callout: the markdown formatter no longer escapes GitHub footnotes

**Plan**: 00474
**Audience**: client projects

`markdown_table_formatter`, `format-markdown` and the CLAUDE.md injector share one mdformat transform, and it did not understand footnotes. A footnote definition such as `[^one]: The source.` was rewritten to `\[^one\]: The source.`, so GitHub showed it as literal text and the reference `[^one]` as plain brackets (GitHub issue 122). A reference starting a wrapped line was escaped the same way.

The transform now enables the `footnote` extension alongside `gfm`, so references and definitions pass through a format unchanged. Files that never used footnotes format exactly as before.

**New dependency**: `mdformat-footnote>=0.1.1` (pure Python; it pulls in only `mdformat` and `mdit-py-plugins`, both already installed). A client install picks it up on upgrade: the upgrade rebuilds the daemon venv, because the venv's recorded hash of `pyproject.toml` and `uv.lock` (and its version stamp) no longer match. A `restart` alone never installs it; if the daemon is running from a venv built before this change, run `bin/hooks-daemon repair`. Until then the formatter still works: it enables footnote support only when the plugin is installed, logs one WARNING when it is not, and formats tables and the rest of GFM as before. A footnote already escaped by an earlier format stays escaped until you remove the backslashes by hand.
