# Callout: the sensitive-content guard and the redaction sinks now read the same word list

**Plan**: 00474
**Audience**: operators

`sensitive_content` resolved `secret_word_list_path` with its own code while the redaction sinks (log, payload-capture and transcript scrubbing, the QA scans) used `secret_redaction.resolve_secret_word_list_path`, so a project that configured the option as an absolute path or with a `{REPO_ROOT}/` prefix had the guard and the redaction reading different files. Both now use the one resolver, with the semantics `CONFIGURATION.md` already documented: the value is repository-relative, a leading `{REPO_ROOT}/` is optional sugar for the same thing, and an absolute value is logged and replaced by the default `.claude/block-words.secret`. If you configured an absolute path, move the list under the repository (or use `{REPO_ROOT}/`); `hooks-daemon check` already reports the degraded value. A configured list that does not exist is inert for every reader alike and is reported at session start by `secret_file_hygiene_checker`.
