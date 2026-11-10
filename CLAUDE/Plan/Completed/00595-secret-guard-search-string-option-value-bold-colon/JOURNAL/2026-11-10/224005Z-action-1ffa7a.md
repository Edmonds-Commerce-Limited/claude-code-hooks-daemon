## 22:40 · action · — — Plan complete: #200 closed, merged eae5878e9, main CI green

Plan 00595 is complete. It merged at `eae5878e9`, main CI run 42912436475 is green, and GitHub #200 is closed.

The three #200 shapes were misreadings: a git search string, a grep/rg filename-filter value, and a colon-split markdown bold. Each now allows, and the controls still deny.

**What review caught.** The first version relaxed filter values too widely. Four adversarial rounds each compared the old and new handler on the same commands, and each round found a narrower case that could print a protected file:

- Round 1: roots outside the project, symlink roots, and link-following flags.
- Round 2: an unquoted separate glob (`--include * sub`). Bash expands it into cwd file names, which makes the protected file a search operand.
- Round 3: empty-quote prefixes (`''*`). The check had looked only at the character before the value.
- Round 4: approved.

**Two cases already broken on main, fixed here because they share the function:** `rg --follow … -g '*'`, and a cwd that is itself a symlink leading out of the project.

**Lesson.** When relaxing a check on a shell word, decide from the whole parsed word: is it one quoted literal, or would bash expand it? A single adjacent character is not evidence. And every searched root has to resolve inside the project before the protected index can vouch for it.
