# Callout: `comment_size` and `comment_changelog` no longer read an unclosed `/*` as a comment running to the end of the file

**Plan**: 00506
**Audience**: operators

A block or doc opener with no closing delimiter later in the content used to be closed at the end of the file, so a `/*` inside a string literal (the glob `"src/*.rs"`) made `comment_size` deny a file that held no comment at all. Such an opener now yields no comment and scanning resumes on the next line as code. A terminated block comment is read as before, a marker in a string whose closer does appear later is still read up to that closer, and no configuration change is needed (reported as issue #75). This applies to whole-file content (`Write`). An `Edit` is judged on its `new_string`, a fragment whose closer may lie in the untouched file, so there an opener with no closer inside the fragment is read as a comment running to the end of the fragment.
