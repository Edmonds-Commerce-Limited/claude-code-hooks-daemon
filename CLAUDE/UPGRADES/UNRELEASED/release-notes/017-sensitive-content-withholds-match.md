# Callout: a `sensitive_content` public-pattern deny no longer shows the matched text

**Plan**: 00514
**Issue**: #92
**Audience**: operators

A deny from a `public_patterns` entry used to end with `Matched: <the matched text>`. The reason is written to the session transcript, so a pattern written to catch a value by its shape (a labelled sort code, a reference number) repeated that value into the transcript.

The deny reason now names only the pattern and where it matched:

- `Write` and `Edit`: the file path and the line number;
- git metadata: the field (commit message, tag name, branch name, author identity, merge message);
- `gh`: the inline body, or the body-file path;
- a staged file at commit time: the path, as before.

The matched text, a snippet of it and the raw command line are no longer in the reason, and no log record holds the match. The secret word list already worked this way.

This reverses the earlier rule that public patterns are safe to name. Nothing blocks differently: every pattern that denied before still denies. Nothing to do on upgrade, but a pattern's `description` is still shown, so keep it generic.
