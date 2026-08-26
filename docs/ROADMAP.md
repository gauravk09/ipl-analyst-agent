# Roadmap

The journey: progress, what was learned, pushbacks that changed the design.

## The build path (each stage = one concept)
1. **Bundle DB + `run_sql` tool** — a grounded tool that returns real rows.  ✅ DONE
2. **Agent loop with `run_sql`** — nodes / edges / state, the reason-act loop.  ✅ DONE
3. **`get_schema` tool** — multiple tools + conditional routing.  ✅ DONE
4. **Multi-turn memory** — state persistence (checkpointer / threads).  ✅ DONE
5. **Approve-before-run** — human-in-the-loop (interrupt).  ✅ DONE
6. **Grounded answer + refusal** — answer welded to rows; abstain when unanswerable.  ✅ DONE
   (three outcomes: answer / clarify / refuse; empty-result discriminator = filter
   value in column domain, not result==0. Prompt-level; sqlglot validator deferred.)
7. **Curated dictionary + entity resolution** (was "RAG") — give the agent
   external knowledge; resolve ambiguity by asking.  ✅ DONE
   - Franchise rename groups (Delhi Daredevils=Capitals etc.) → correct totals.
   - `find_player`: distinct → nearest → ask if ambiguous (no embeddings).
8. **Eval harness** — assert the ACTUAL answer (the moat).  ✅ DONE (7/7: values
   736/973/125/155/0 + verified refuse + clarify; caught its own apostrophe bug B3).
9. **Verifier node** — multi-node wiring + independent verification (capstone).  ✅ DONE
   Chose a hybrid verifier over a full planner/writer/checker split (that was ceremony
   for single-query Q&A). Deterministic grounding gate: every number in an answer must
   trace to a run_sql result or the user's question, else bounce back to the brain
   (max 2 retries). Clarify/refuse pass through. Unit-tested 5/5; eval still 9/9.

## Pushbacks that changed the design
- Repeated: "representative, not a toy" and "just pick and build."
- Final reset: "maximize MY learning, domain doesn't matter." → dropped trading;
  chose a deterministic, concept-dense, zero-friction vehicle (SQL analyst).
- "Does RAG even fit? Most questions answer by querying." → correct. RAG needs
  knowledge that is BOTH not-in-tables AND too-large-for-prompt; our gaps (season
  format, franchise renames, name variants) are small + fixed. Dropped RAG. Renames
  → curated dictionary; name variants → distinct + ask (user's suggestion).

## Open questions
- ~~Which model handles tool-calling well on Ollama Cloud?~~ RESOLVED: `gpt-oss:120b`
  emits OpenAI-style tool calls correctly (verified stage 2: wrote its own JOIN,
  answered Kohli 973 for 2016 — the real number).

## Success definition
Given a DB question, the agent returns an answer welded to query rows, refuses the
unanswerable ones, and the eval suite asserts the ACTUAL values — not just no-crash.
