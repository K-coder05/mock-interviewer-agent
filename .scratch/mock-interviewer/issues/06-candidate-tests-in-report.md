# 06: Candidate Tests in the Report

**What to build:** The Report shows the Candidate Tests I wrote or spoke: each marked executed or traced, and verified (I stated the expected result) or unverified. Prints whose expected value I never stated are listed separately as "ran but not verified". Only now are the Edge-Case Categories I missed revealed.

**Blocked by:** 02 (Run your code), 05 (First Report end to end)

**Status:** ready-for-agent

- [ ] Executed tests extracted from code via syntax-tree analysis: asserts, calls under the main guard, printed calls, stdin inputs
- [ ] Traced tests are tagged from the transcript by the model at Report time
- [ ] Asserts are verified; a printed call is verified only if the expected value was said or commented within ~30 s
- [ ] Testing breakdown groups tests by category and lists missed Edge-Case Categories from the Problem Brief
- [ ] Testing rubric rewards stated expectations
- [ ] Report seam tests cover each extraction form and the verified/unverified rules
