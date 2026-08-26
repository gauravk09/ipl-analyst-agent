# Bug journal

Grouped by lesson, not by date. Each entry: what happened, why, the fix, what
FOUND it. Ends with a tally of what caught each bug.

## Lesson: a grounded number can still be wrong — the QUERY must be right, not just the answer

### B1 — an empty result got reported as a confident "0"
- **Happened:** "How many sixes in IPL 2020?" → agent answered **"0 sixes."** Real
  answer: **736**.
- **Why:** the 2020 season is stored as `2020/21`. The agent filtered
  `season='2020'`, which matched **zero rows**. `COUNT(*)` over zero rows is `0` —
  a real SQL number — so the agent grounded to it and reported 0 with full
  confidence. Grounding to a query result is necessary but NOT sufficient: the
  *query* was wrong, and an empty match masquerades as a legitimate zero.
- **First fix attempt (REJECTED):** "treat any 0/empty result as a red flag and
  retry." Killed by a counterexample: *"How many wickets did Kohli take in IPL
  2026?"* is a **legitimate zero** (season 2026 exists, Kohli bowled 264 balls
  career, but 0 wickets in 2026). A rule that distrusts every zero would wrongly
  reject a correct answer.
- **Correct fix:** the discriminator is NOT "result == 0". It is **"does each
  filter literal exist in its column's domain?"** `season='2020'` → absent (real
  label '2020/21') → spurious zero, fix the query. `season='2026'` + `bowler='V
  Kohli'` → both present → 0 is a TRUE answer, report it. Structural version:
  parse WHERE equality literals (sqlglot) and check each against SELECT DISTINCT.
- **VERIFIED:** after the prompt fix, "sixes in 2020" → 736 (agent found the
  2020/21 label), and "Kohli wickets in 2026" → 0 (true zero kept). Both correct.
  Caveat: this is PROMPT-level (soft); the sqlglot validator is the hard version.
- **Found by:** adversarial probing + source verification. The correct fix was
  forced by the user's counterexample — the first fix was over-eager.

## Lesson: a real number is not always the right answer — rate stats need a qualifier

### B2 — strike-rate "leader" who faced 4 balls
- **Happened:** "Highest strike rate in IPL history?" → **"Auqib Nabi, 350.0."**
- **Why:** strike rate = runs/balls * 100. With 14 runs off 4 balls that's 350,
  and it tops the list. Technically grounded, practically meaningless — no minimum
  balls faced. This is the min/max-without-threshold trap.
- **Fix:** treat this as a **clarify** outcome, not answer-or-refuse. The question
  is underspecified; silently picking a threshold is a hidden guess. The agent
  should ASK "over a minimum of how many balls?" This gives three outcomes —
  answer / clarify / refuse (mirrors the grounded-analytics repo).
- **Found by:** adversarial probing (a known trap question). Clarify framing
  suggested by the user.
- **VERIFIED:** hardened agent now replies "over a minimum of how many balls?"
  instead of returning the 4-ball leader.

## Lesson: a failing test is a disagreement between two ideas — sometimes the TEST is wrong

### B3 — eval reported FAIL on a correct refusal (curly apostrophe)
- **Happened:** the scoreboard failed "What is Kohli's salary?" even though the
  agent refused correctly ("I'm sorry, but I don't have that information").
- **Why:** the refusal marker list had `don't have` with a STRAIGHT apostrophe;
  the model emitted a CURLY one (’). Substring match missed → false FAIL. Same
  family as every prior string-matching bug: it produced a wrong verdict, here a
  false failure rather than a false pass.
- **Fix:** normalise curly → straight quotes before matching.
- **Found by:** the eval run itself — a case I KNEW should pass failed, so the
  disagreement was in the test, not the agent.

## Tally — what found each bug
- B1: adversarial probe + source verification.
- B2: adversarial probe.
- B3: the scoreboard caught its own bug (a known-good case failed).
