# Callout: the code file reader parses once per file, and reads scripts by language

**Plan**: 00463
**Audience**: operators

`subagent_full_qa_blocker` bounded the bytes it reads from a file of code, but
kept re-parsing the same file's content at every reference to it: a file that
fed itself back, or was referenced many times in one command, cost one parse
per reference. A distinct `(path, kind, argv, directory, PYTEST_ADDOPTS)` is
now parsed at most once per event at each depth; every other reference reuses
the memoised verdict, and a file feeding itself back is recognised as a cycle
rather than followed again.

Every parse in one judgement — the command, each nested `bash -c`, each file
and each Python literal — draws on ONE budget of 96 KiB, counted in bytes.
Code the budget cannot cover is denied (`too-much-code-to-judge`), never
skipped. A file too large to parse is scanned raw for a declared program's
name, comments and strings included, and any hit denies; a script that runs a
script more than eight files deep is denied (`code-nested-too-deep`).

Python code that can start a process has EVERY string literal read as a
command, wherever it sits (a variable, a dict, a return value, a
concatenation, an f-string's constant parts); a literal whose first word
Python computes (`f"{n} files"`) is a program named at run time and is not
seen. A file run by its path with no execute bit runs nothing, unless the
command may change modes first. A script path led by a variable the code never
sets (`bash "$SCRIPT"`) is denied as unseen, and `$(cat f)` as the command
word runs the file.
