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

## Lesson: an over-eager gate is a real bug — "must stay quiet" cases catch it

### B4 — find_player over-clarified on an exact name
- **Happened:** "How many wickets did V Kohli take in IPL 2026?" → agent asked
  "T Kohli or V Kohli?" instead of answering 0. The user had already given the
  full exact name.
- **Why:** stage 7's find_player rule said "several candidates → ask." `find_player
  ("Kohli")` returns two names, so it asked — ignoring that the user's exact name
  'V Kohli' was one of them. A gate that fires when it shouldn't.
- **Fix:** if the user's name exactly matches a candidate, USE it; only ask when
  several match and none is exact.
- **Found by:** the HARDENED eval — the new must-stay-quiet / grounding check on a
  value case turned a silent over-clarification into a red test. The old suite
  (final-text only) would have missed it. Regression introduced by stage 7,
  caught by stage 8+.

### B7 — over-clarified again on a single non-exact match
- **Happened:** "Show Mike Hussey season-wise runs" → find_player returned the one
  candidate "MEK Hussey", but the agent asked "is this who you meant?" instead of
  using it. Surfaced while building the chart tool.
- **Why:** rule 6 said "use it if it EXACTLY matches the user's text", and "Mike
  Hussey" != "MEK Hussey" character-for-character, so with one non-exact candidate
  the rule was silent and the agent defaulted to asking.
- **Fix:** if find_player returns exactly ONE candidate, use it (one match is
  unambiguous); ask only when several match and none is exact.
- **Found by:** manual testing of the new visualizer feature.

## Lesson: the internal data format is not the user-facing answer (grounding vs presentation)

### B5 — raw season label leaked into the answer
- **Happened:** "from when did IPL start?" → "The IPL started in the 2007/08
  season." The query was right (MIN season = 2007/08); the presentation was the
  DB's internal label, not the human year the user wanted (2008).
- **Why:** curated season knowledge was used only for FILTERING (input), never for
  PRESENTING (output). Two extra twists: the label→year map is IRREGULAR (2007/08→
  2008 end-year, but 2020/21→2020 start-year, COVID) so it must be curated
  explicitly; AND naively answering "2008" would be BOUNCED by the verifier, since
  2008 isn't literally in a result containing "2007/08".
- **Fix:** explicit SEASON_YEAR map. (1) Prompt: report the calendar year, not the
  slash label. (2) Verifier: a season label in a result also grounds its mapped
  year, so the human answer passes. Both halves needed.
- **Found by:** the user driving the Streamlit UI by hand — a bug the eval's
  fixed questions never exercised.

## Lesson: a correct answer via a messy path is a hidden fragility (coverage + trajectory)

### B6 — column guessing + a name-resolver blind to the data format
- **Happened:** "runs Kohli scored off Ishant, in how many balls?" → correct answer
  (112 off 79), but the trail was messy: the agent guessed a non-existent `striker`
  column (recovered), and hand-rolled `SELECT DISTINCT bowler LIKE …` searches
  instead of using find_player — because find_player (naive substring) couldn't turn
  'Ishant' into the data's 'I Sharma'.
- **Why:** (1) the agent wrote SQL before knowing the columns; (2) find_player matched
  raw substrings, blind to the data's 'initial surname' format (V Kohli, I Sharma).
- **Fix:** (1) inject the introspected schema into the system prompt (no guessing,
  still generic); (2) rewrite find_player to match SURNAME + first INITIAL
  ('Ishant Sharma' → 'I Sharma'); (3) prompt: use find_player, not manual DISTINCT.
- **Eval gap:** the suite had NO player-vs-player case, and asserted only
  values/grounding — never path cleanliness — so a messy-but-correct run passed.
  Added a coverage case AND a trajectory assertion (no run_sql may error). Also
  fixed the must-answer check, which over-specified "contains a number" (a player
  name is a valid answer) — the test was wrong, not the agent.
- **Found by:** the user driving the Streamlit UI. The eval could not have caught
  it: wrong coverage + final-answer-only. Now it can.

## Tally — what found each bug
- B1: adversarial probe + source verification.
- B2: adversarial probe.
- B3: the scoreboard caught its own bug (a known-good case failed).
- B4: the hardened eval (grounding + must-stay-quiet) caught a stage-7 regression.
- B5: driving the UI by hand (a presentation bug invisible to value-only evals).
- B6: driving the UI by hand; exposed an eval coverage + trajectory gap, now closed.

## Lesson: over-answering + a grounding verifier = query explosion

### B8 — a combo-chart answer ran ~40 LLM calls and 20+ queries
- **Happened:** "Compare Dhoni vs de Kock … SR bars + runs line" → the agent drew
  the chart correctly, then volunteered ~20 extra stats (total matches, runs,
  common seasons, seasons with 300+, …). Final answer was a bloated "Corrected
  answer" dump of 56 messages; two queries errored and recovered.
- **Why:** no conciseness constraint. The verifier requires EVERY stated number to
  be grounded, so a chatty answer forces one query per volunteered stat — a query
  explosion. The "Corrected answer" prefix is the verifier bounce.
- **Fix:** rule 9 (CONCISE & ON-SCOPE) — answer only what's asked, don't volunteer
  extra statistics. Re-run of the same question: 40→14 LLM calls, 20→6 queries,
  concise on-scope answer.
- **Found by:** inspecting a shared LangSmith trace (real production observability).

## Lesson: reasoning tokens dominate latency — measure, then turn the right knob

### B9 — the combo question took ~115–200s
- **Happened:** "Compare Dhoni vs de Kock … SR bars + runs line" took 115s+ (once 202s).
- **Why:** measured, not guessed. Per-call latency of gpt-oss:120b was ~19.5s with
  ~1,400 output tokens — almost all *reasoning* tokens. Times ~14 sequential agent
  round trips = ~2–3 minutes. (Exactly the "reasoning tokens are 99% of the bill"
  lesson.)
- **Fix (stacked):** (1) `reasoning_effort=low` → 19.5s→8.2s per call, same eval
  score; (2) broaden the "must draw a chart" trigger (the question said 'bars'/'line',
  not 'chart', so it was skipping the plot); (3) prompt to BATCH independent tool
  calls + consolidate queries → 14→8 calls, 9→2 queries.
- **Result:** combo **115s → 37.9s**, chart restored, eval still **11/11**.
- **Found by:** the user reporting the latency; isolated per-call timing pinpointed
  reasoning tokens as the cause.

## Lesson: a household name that "looks missing" erodes trust — curate the stars

### B10 — agent asked "which Rohit Sharma?" for a superstar
- **Happened:** "Compare … Rohit Sharma …" → agent asked "which Rohit Sharma: R
  Sharma, RG Sharma, or Raghu Sharma?" — making it look like the dataset lacks
  Rohit. He's there as **RG Sharma** (7,331 IPL runs).
- **Why:** the data stores players as "initials surname" (RG Sharma). find_player
  matches surname + FIRST initial, so "Rohit Sharma" → initial 'R' → three R-Sharmas,
  none exactly "Rohit". Full first name → initials can't be derived by rule.
- **Fix:** a curated PLAYER_ALIASES map (full name → data name) for ~30 stars, checked
  first in find_player. "Rohit Sharma" → "RG Sharma" directly. Non-stars still use the
  fuzzy surname+initial path. Also: rule 4 now says if a minimum IS given, answer (don't
  re-ask) — killing a flaky over-clarify.
- **Found by:** capturing a Streamlit screenshot for the README — the Rohit clarify
  showed up on camera. (Driving the UI finds what fixed evals don't.)
