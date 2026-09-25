# Callout: a protected path your config names but lacks is now reported

**Plan**: 00414
**Audience**: client projects

A fresh clone never has the gitignored secret word list, so `sensitive_content`'s
word-list source was inert from the first session, and nothing said so: silence
looked the same as health. The SessionStart hygiene advisory now names a
protected path that is missing when your config names it explicitly
(`sensitive_content`'s `secret_word_list_path` option, or a path-shaped entry
in `secret_file_guard`'s `protected_paths`), and says which guard it leaves
inert. It is told once, and repeats only when the config or the file's
presence changes. A default you never configured is not reported, and the
check only stats the path: nothing is opened or read. To clear it, create the
file or remove the declaration.
