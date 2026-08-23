# Captured intake messages

## `raw/` — never committed

Real emails as downloaded from the mailbox, with real addresses and whatever was
attached. Gitignored. They stay on the machine that captured them.

## `redacted/` — committed on purpose

Fixtures the test suite replays. A file only reaches here after the personal
parts are replaced: sender and recipient addresses, names, phone numbers, and the
attachment swapped for a synthetic one. Putting a file here is a deliberate act.

These are what make a job board's format change *visible*. When Naukri quietly
alters its notification layout, the test replaying the fixture goes red and names
the reason. Without them a source silently dries up and looks like a slow week.
