# Callout: a restart that regenerates an identical CLAUDE.md block no longer runs the markdown formatter

**Plan**: 00495
**Audience**: client projects

Every daemon start regenerated the `<hooksdaemon>` block in `CLAUDE.md` and ran the markdown formatter over the whole file, about 0.2 s of CPU on a 114 KB `CLAUDE.md`. The injector now records, inside the repository's git directory (`hooks-daemon-claude-md-format`), a fingerprint of the last text it formatted and the file it produced. When the next start would format the same text and `CLAUDE.md` is still exactly that output, the formatter is skipped and the file is left as it is. Any change to the generated block, or any edit anywhere else in `CLAUDE.md`, runs the formatter exactly as before and produces the same result. Outside a git repository nothing is recorded and every start formats.

Nothing needs to be done on upgrade, and no file is added to the working tree or needs a `.gitignore` entry.
