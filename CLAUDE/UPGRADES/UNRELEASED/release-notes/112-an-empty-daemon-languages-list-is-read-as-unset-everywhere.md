# Callout: an empty `daemon.languages: []` is read as unset everywhere

**Plan**: 00586
**Audience**: operators

`daemon.languages` narrows the language-specific handlers to the languages you list, and unset means every language. The handler language filter already read an empty list as unset, but the `optimise` checklist (which `housekeeping` runs as its last step) read `[]` as a declared project with no languages, so the items that depend on a language (the ESLint-on-write handler and the LSP-noise strategies) were reported as not applicable and their recommendations hidden, even in a project with the matching marker files. Both now read `[]` as unset, so the checklist falls back to detecting your languages from the project's marker files. Enforcement is unchanged. If you want fewer language handlers, list the languages you do use; an empty list never meant "none".
