# Callout: a full_words-only full_qa_patterns entry judges operands as words only

**Plan**: 00474
**Audience**: client projects

A `subagent_full_qa_blocker` entry that declared `full_words` and no `full_args` also ran the path rules on every operand, so `{command: php, full_words: [bin/qa]}` denied `php probe.php .`, `php probe.php ..` and `php probe.php <nested repo root>` although no full word was present. Such an entry now judges operands as words only: a word in `full_words` makes the run full, and no operand is judged as a repository root or as at or above the start directory. An entry that declares `full_args`, even `full_args: []`, behaves exactly as before, as do `bare_is_full`, `read_only_flags` and `value_flags`. If you relied on a words-only entry denying `.` or a repository root, declare `full_args` for it.
