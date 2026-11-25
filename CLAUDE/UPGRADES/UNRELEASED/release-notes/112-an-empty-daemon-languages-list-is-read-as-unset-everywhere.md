# Callout: an empty `daemon.languages: []` is read as unset everywhere

**Plan**: 00586
**Audience**: operators

`daemon.languages` narrows the language-specific handlers to the languages you list, and unset means every language. The handler language filter already read an empty list as unset, but the relevance review (which decides what the housekeeping and optimise reports call relevant to your project) read `[]` as a declared project with no languages, so every language-specific item was reported as irrelevant. Both now read `[]` as unset, so the review falls back to detecting your languages from the project's marker files. If you want fewer language handlers, list the languages you do use; an empty list never meant "none".
