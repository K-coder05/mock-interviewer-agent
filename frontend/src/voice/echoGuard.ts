// Echo guard: speech recognition keeps running while the Interviewer speaks, so it can hear the
// Interviewer's own voice through the speakers. A transcript that closely matches what the
// Interviewer is saying is that echo and is discarded; anything else is the Candidate (and,
// while the Interviewer is speaking, a barge-in).
//
// "Closely matches": most of the transcript's words appear, in order, in the Interviewer's
// text (the longest common subsequence of words), allowing for recognition errors in a word.

/** The share of the transcript's words that must match, in order, to count as echo. */
const ECHO_THRESHOLD = 0.7;

function words(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/['’]/g, "")
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);
}

function editDistance(a: string, b: string): number {
  let previous = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const current = [i];
    for (let j = 1; j <= b.length; j++) {
      const substitution = previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1);
      current[j] = Math.min(previous[j] + 1, current[j - 1] + 1, substitution);
    }
    previous = current;
  }
  return previous[b.length];
}

// The same word, allowing a misrecognized letter or so in longer words ("nested"/"nestled").
function sameWord(heard: string, said: string): boolean {
  if (heard === said) return true;
  if (heard.length < 4 || said.length < 4) return false;
  return editDistance(heard, said) <= Math.floor(Math.max(heard.length, said.length) / 4);
}

function matchedInOrder(heard: string[], said: string[]): number {
  // longest common subsequence, one row at a time
  let previous = new Array<number>(said.length + 1).fill(0);
  for (const word of heard) {
    const current = [0];
    for (let j = 1; j <= said.length; j++) {
      current[j] = sameWord(word, said[j - 1])
        ? previous[j - 1] + 1
        : Math.max(previous[j], current[j - 1]);
    }
    previous = current;
  }
  return previous[said.length];
}

/** Whether `transcript` is the Interviewer's own voice: it closely matches `interviewerText`,
 * the text the Interviewer is (or was just) speaking. */
export function isEcho(transcript: string, interviewerText: string): boolean {
  const heard = words(transcript);
  const said = words(interviewerText);
  if (heard.length === 0 || said.length === 0) return false;
  return matchedInOrder(heard, said) / heard.length >= ECHO_THRESHOLD;
}
