# Mock Interviewer

A single-candidate practice tool for live coding interviews that grades the candidate's process — clarifying, designing, communicating, coding and self-testing — rather than a hidden test suite.

## Sessions

**Session**:
One timed attempt at one pasted problem, together with its event log and report. Retrying a problem creates a new Session.
_Avoid_: Interview (as a noun outside UI copy), attempt, run

**Candidate**:
The person practicing; the only user.
_Avoid_: User (in interviewer-facing contexts), interviewee

**Abandoned Session**:
A Session that stopped without ending — the Candidate left or the app crashed — and never received an end. It can still be reported on.

**Interviewer**:
The Claude-powered persona that converses with the Candidate during a Session.
_Avoid_: Agent (in user-facing text), bot, tutor

**Problem Brief**:
The hidden analysis of the problem produced once at Session start: approaches, pitfalls, Edge-Case Categories, default clarification answers and follow-ups.
_Avoid_: Solution, answer key

**Phase**:
A descriptive label for where the Session currently is (Clarify, Approach, Implement, Test, Wrap-up). A label, not a gate: it can move backwards.
_Avoid_: Stage, step

**Style**:
The persona preset (or free-text description) that shapes the Interviewer's tone and probing. Never changes how a Session is scored.
_Avoid_: Difficulty, company mode

## Interviewer speech

**Probe**:
An assessment question from the Interviewer (complexity, trade-offs, "what happens if…"). Not help; never counts against the Candidate.

**Hint**:
Help given because the Candidate is stuck, always carrying a level from 1 (probing question) to 4 (concrete next step).
_Avoid_: Tip, clue

**Trigger**:
A condition the Session detects that warrants considering an Interviewer reaction (silence, a finished Run, a time checkpoint…). A Trigger may result in silence.

**Nudge**:
An unprompted Interviewer utterance actually spoken in response to a Trigger such as silence, stuckness or time.
_Avoid_: Interjection (when meaning only nudges), prompt

**Clarification**:
A question the Candidate asked about the problem together with its binding answer — given by the Interviewer, or, when the problem leaves it open, the assumption the Candidate chose to state.

## Testing

**Run**:
One execution of the Candidate's editor buffer. A Run is not itself a test; it may contain zero or many Candidate Tests.
_Avoid_: Test, submission, execution

**Candidate Test**:
One concrete input the Candidate chose in order to check behavior. Either **executed** (it ran as part of a Run) or **traced** (spoken and walked through by hand).
_Avoid_: Test case (unqualified), example

**Verified Test**:
A Candidate Test whose expected result the Candidate stated (an assert, or an expectation said or written alongside it). A test that ran without a stated expectation is **unverified**.

**Edge-Case Category**:
A class of inputs (empty, single element, duplicates…) listed privately in the Problem Brief and used only to grade the completeness of the Candidate's testing.
_Avoid_: Hidden test, test case

## Feedback

**Report**:
The post-Session evaluation: rubric scores with timestamped evidence, Overall Signal, strengths, improvements and testing breakdown.
_Avoid_: Scorecard, grade

**Overall Signal**:
The single verdict on a Report — Strong No, No, Lean No, Lean Hire, Hire or Strong Hire — derived mechanically from the weighted rubric scores.
_Avoid_: Verdict, result, pass/fail

**Ideal Walkthrough**:
The Report section describing how a strong Candidate would have solved the problem; its code is hidden until the Candidate chooses to reveal it.
_Avoid_: Solution, answer
