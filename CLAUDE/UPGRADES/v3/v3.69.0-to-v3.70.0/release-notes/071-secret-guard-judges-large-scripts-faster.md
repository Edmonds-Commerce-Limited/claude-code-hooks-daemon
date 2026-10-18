# Callout: the secret-file guard judges a large script Write faster

**Plan**: 00474
**Audience**: client projects

`secret_file_guard` shell-tokenised every line of an authored script to look for a `cd` or `pushd` whose target a later relative path would be read from. It now tokenises only a line that could start with one of them, and a non-shell source file (`.py`, `.js` and the rest), whose scan never uses those directories, skips the step entirely. Every verdict is unchanged: the guard's tests and a pinned corpus of protected-path spellings give the same answer before and after.

Measured on the same host with the shipped protected patterns, a benign `.sh` Write took 376 ms before and 205 ms after at 120 KB, and 4.6 s before and 2.5 s after at 1.2 MB; a `.py` Write took 944 ms before and 740 ms after at 120 KB. A large Write still costs more than the 100 ms the daemon aims for, because the guard's brace-word and Python string-literal scans still read the whole file. Nothing needs to change in your config.
