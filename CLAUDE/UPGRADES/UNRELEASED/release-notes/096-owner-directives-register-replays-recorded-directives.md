# Callout: owner directives register replays recorded directives to a coordinator seat

**Plan**: 00636
**Audience**: operators

The new `owner_directives_register` UserPromptSubmit handler records each owner directive once, in `options.directives`, and replays the list to a team coordinator seat on the first human prompt of a session and every `prompt_interval` prompts (default 10), so a directive given once is checked rather than asked again. It is silent until a directive is listed, never denies and is never terminal. A repeated id or wording collapses to one entry. A declared worker, a session with no team and a sub-agent are untouched; an unreadable role stays armed, as in the owner-wait stop guard. The replay is a recorded request, not a fresh human instruction and not a citable approval.

Detecting a repeated directive from the bus, writing into the register and detecting a seat that re-asked one are not built. The upgrade adds the handler's config entry; nothing else needs changing.
