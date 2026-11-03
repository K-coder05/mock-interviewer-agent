# 13: Reconnect and Abandoned Sessions

**What to build:** If I refresh the tab mid-Session it reconnects and resumes with nothing lost and the timer still correct. If the app crashed and a Session was left hanging, it becomes an Abandoned Session that I can still generate a Report for.

**Blocked by:** 05 (First Report end to end)

**Status:** ready-for-agent

- [ ] Client sends its last seen `seq` on reconnect; server replays missed events; timer continues on wall clock
- [ ] On backend startup, `live` Sessions with no events in the configured window (10 min) become `abandoned`
- [ ] Abandoned Sessions don't auto-generate a Report; a Generate report button triggers it
- [ ] Live Session tests cover reconnect replay and abandoned marking
