import { describe, expect, it } from "vitest";
import { isEcho } from "./echoGuard";

const SPOKEN = "Good start. What's the time complexity of your nested loop, and can we do better?";

describe("isEcho", () => {
  it("discards the Interviewer's own sentence heard back", () => {
    expect(isEcho("what's the time complexity of your nested loop", SPOKEN)).toBe(true);
  });

  it("discards a short interim fragment of what the Interviewer is saying", () => {
    expect(isEcho("good start", SPOKEN)).toBe(true);
    expect(isEcho("nested", SPOKEN)).toBe(true);
  });

  it("ignores case, punctuation and apostrophes", () => {
    expect(isEcho("Whats the TIME complexity?!", SPOKEN)).toBe(true);
  });

  it("tolerates recognition errors in a few words", () => {
    // "your" heard as "you're", "nested" as "nestled", "better" as "bettor"
    expect(isEcho("you're nestled loop and can we do bettor", SPOKEN)).toBe(true);
  });

  it("lets the Candidate's own words through (barge-in)", () => {
    expect(isEcho("wait can I ask something first", SPOKEN)).toBe(false);
    expect(isEcho("I think it's quadratic", SPOKEN)).toBe(false);
  });

  it("lets through speech that only shares a few words with the Interviewer's", () => {
    expect(isEcho("the complexity is n squared because of the loop", SPOKEN)).toBe(false);
  });

  it("needs the words in the order the Interviewer said them", () => {
    expect(isEcho("better do we can", SPOKEN)).toBe(false);
  });

  it("discards nothing when the Interviewer has said nothing", () => {
    expect(isEcho("good start", "")).toBe(false);
    expect(isEcho("   ", SPOKEN)).toBe(false);
  });
});
