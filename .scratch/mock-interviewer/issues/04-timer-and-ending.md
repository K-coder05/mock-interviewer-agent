# 04: Timer and ending a Session

**What to build:** A countdown timer (default 45 min, chosen on setup) starts when the Interviewer's greeting begins. It turns red at 5 minutes left with a warning. At 0:00 the Interviewer says time is up and asks for any last thought; the Session ends automatically 60 s later. I can click End Interview at any time. The Interviewer closes politely with no verdict.

**Blocked by:** 03 (Problem prep and a text-chat Interviewer)

**Status:** ready-for-agent

- [ ] Duration is chosen on setup and stored in settings
- [ ] Timer starts at greeting, not at Session creation; `timer` updates reach the UI
- [ ] 5-minute warning turns the timer red
- [ ] At 0:00 the Interviewer prompts for a last thought; auto-end after the configured grace (60 s) unless ended earlier
- [ ] End Interview and auto-end both emit `session_ended` (reason user/timeout, final code) and set status `ended`
- [ ] Live Session tests with the fake clock cover warning, grace and auto-end
