# 03: Problem prep and a text-chat Interviewer

**What to build:** When I click Start, the app prepares a hidden Problem Brief while showing "Interviewer is reading the problem…". I can add private notes and pick a Style (three presets or free text). The Interviewer then greets me and restates the problem. I can type to it at any time and always get a short, streamed, conversational reply. When I ask a clarifying question it answers consistently with my private notes and the Problem Brief; if neither covers it, it asks what I'd assume and treats my assumption as binding. Clarifications appear under the problem.

**Blocked by:** 01 (Skeleton: start a Session and type code)

**Status:** ready-for-agent

- [ ] Problem prep produces a Problem Brief (approaches, insights, pitfalls, Edge-Case Categories, default clarification answers, follow-ups), stored hidden on the Session
- [ ] Prep failure after one retry returns to setup with input intact and creates no Session
- [ ] Private notes and the Problem Brief are never sent to the client
- [ ] Style preset or free text is stored in settings and shapes only the persona section of the prompt
- [ ] Interviewer greets and restates the problem; typed messages always get a streamed reply (`interviewer_delta` / `interviewer_done`)
- [ ] Decision-call context is rebuilt from the event log each time; system prompt (persona, problem, Brief) is prompt-cached
- [ ] `record_clarification` logs a `clarification` event with `by` interviewer/candidate and the UI appends it under the problem
- [ ] Interviewer never gives the solution, writes code or proposes test inputs (system-prompt rules)
- [ ] Live Session tests with a scripted fake model cover a typed exchange and a clarification with `by: candidate`
