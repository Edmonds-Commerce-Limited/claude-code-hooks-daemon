# Callout: the markdown formatter no longer escapes GitHub footnotes

**Plan**: 00474
**Audience**: client projects

`markdown_table_formatter`, `format-markdown` and the CLAUDE.md injector share one mdformat transform, and it did not understand footnotes. A footnote definition such as `[^one]: The source.` was rewritten to `\[^one\]: The source.`, so GitHub showed it as literal text and the reference `[^one]` as plain brackets (GitHub issue 122). A reference starting a wrapped line was escaped the same way.

The transform now enables the `footnote` extension alongside `gfm`, so references and definitions pass through a format unchanged. Files that never used footnotes format exactly as before.

**New dependency**: `mdformat-footnote>=0.1.1` (pure Python; it pulls in only `mdformat` and `mdit-py-plugins`, both already installed). A client install picks it up when the daemon venv is rebuilt on upgrade (the venv is keyed on a hash of `pyproject.toml` and `uv.lock`, so this change selects a new venv). Until then the formatter still works: it enables footnote support only when the plugin is installed, logs one WARNING when it is not, and formats tables and the rest of GFM as before. A footnote already escaped by an earlier format stays escaped until you remove the backslashes by hand.
