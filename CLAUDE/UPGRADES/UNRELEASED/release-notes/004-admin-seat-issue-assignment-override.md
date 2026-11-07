# Callout: a repository admin seat is no longer locked out by a non-admin's issue assignment

**Plan**: 00573
**Audience**: client projects

The assignment guard and `issue-validity` used to block any work tied to an issue assigned to another account, which also locked out a repository admin seat (an inactive non-admin assignee left an issue uneditable until a human reassigned it by hand). Now, when the signed-in account is a repository admin (read from GitHub) and every other assignee is a non-admin, the guard allows the work with an advisory naming the assignee and the takeover command, and `issue-validity N --claim` performs a recorded takeover: it switches the assignee to the admin, re-reads to verify the admin is the only assignee, and posts one short comment naming the previous assignee(s). The duplicate-work protection is unchanged for non-admin seats, an admin still respects another admin's assignment, and a permission that cannot be read never grants the override.
