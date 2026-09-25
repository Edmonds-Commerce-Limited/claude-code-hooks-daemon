# Callout: the code file reader parses once per file, and reads scripts by language

**Plan**: 00463
**Audience**: operators

`subagent_full_qa_blocker` bounded the bytes it reads from a file of code, but
kept re-parsing the same file's content at every reference to it: a file that
fed itself back, or was referenced many times in one command, cost one parse
per reference. A distinct `(path, kind, argv, directory)` is now parsed at
most once per event; every other reference reuses the memoised verdict, and a
file feeding itself back is recognised as a cycle rather than followed again.

Reading a script run by its path or by `python script.py` no longer misreads
its own prose as the run it makes. A Python string literal is judged as shell
code only when it sits inside a `subprocess`/`os` call's own argument list, not
wherever a multi-word string appears in the file — a docstring or a log
message elsewhere is never a candidate, however many words or apostrophes it
has, and a literal that still fails to parse as shell is treated as no
command, not as an unseen run. A file past the parse cap is scanned for a
declared program's name with its comments dropped, and a Python file also has
every string's content blanked (found with Python's own tokenizer, not a
hand-rolled quote count) — a docstring or a message quoting a program's name
is data, not a line that runs it.
