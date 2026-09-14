# Callout: a plan glob on the next line is not a discovery scan

**Plan**: 00405
**Audience**: everyone

`plan_number_helper` denied multi-line commands it had no business judging: an
`echo` on one line could reach across the newline and borrow a glob character
from the next line's unrelated command, so listing the files of ONE named plan
folder — whose number is already written in the path — was refused as a hunt
for the next plan number. The `;` spelling of the same command was allowed
throughout.

A `\<newline>` line continuation is now handled too. That really does join two
lines into one command, and the rules here had never seen it in the normalised
form the rest of the daemon uses, so the genuine `echo \<newline> <plan-dir>/0*` discovery idiom had been slipping through.
