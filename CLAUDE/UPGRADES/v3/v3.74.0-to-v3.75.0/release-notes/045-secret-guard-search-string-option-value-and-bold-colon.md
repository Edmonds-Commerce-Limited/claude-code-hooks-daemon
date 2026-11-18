# Callout: secret_file_guard no longer denies a git search string, a grep filter value or bold markdown

**Plan**: 00595
**Audience**: client projects

`secret_file_guard` (R-SECRET-BASH-MENTION) judged three kinds of text as protected paths although none opens a file (GitHub #200). All three are now allowed:

- The value of a git search option, `-S`, `-G`, `--grep`, `--author`, `--committer` and `--grep-reflog`, in both the separate (`-S x`) and attached (`-Sx`, `--grep=x`) spellings. `git log -S org.freedesktop.secrets` is a search for a string.
- The attached value of a grep/rg filename filter (`--include=*`, `--exclude=`, `--exclude-dir=`, `--glob=`, `--iglob=`) when the command names search paths and none of them holds a protected file. A filter over a directory that does hold one, or a command that names no path (so the cwd is searched), is still denied.
- A colon split of a word no longer yields a wildcard-only part, so bold markdown such as `**Option 2:** build` in a Python heredoc is not read as the glob `**`.

A protected path that is genuinely named still denies: `git log -- <path>`, `git show HEAD:<path>`, `host:<path>`.
