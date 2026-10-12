# Callout: issue_filing_gate reads gh flags from shell words

**Plan**: 00474
**Audience**: everyone

`issue_filing_gate` read `--repo`/`-R` and `--body-file`/`-F` (and `--web`) by regex over the raw command text, so text inside a quoted argument counted as a flag. A title such as `'git merge -F - reads stdin'` made a valid generated report look like a stdin body and refused it. Worse, a title such as `'see -R someone/else'` placed before the real `--repo` made the gate read the wrong target and stand down for a real filing against the public hooks-daemon tracker; a quoted `--web` in a title likewise opened the browser-fallback exemption. The flags are now taken from the segment's shell words, so only a real flag counts. A segment that cannot be split into words (an unterminated quote, `$(...)`) is still read from the raw text as before, which can only over-find a flag and never stands the gate down.
