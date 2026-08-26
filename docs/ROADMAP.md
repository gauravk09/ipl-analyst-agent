# Roadmap

The journey: progress, what was learned, pushbacks that changed the design.

## The build path (each stage = one concept)
1. **Bundle DB + `run_sql` tool** — a grounded tool that returns real rows.  ✅ DONE
2. **Agent loop with `run_sql`** — nodes / edges / state, the reason-act loop.  ✅ DONE
3. **`get_schema` tool** — multiple tools + conditional routing.
4. **Multi-turn memory** — state persistence (checkpointer / threads).
5. **Approve-before-run** — human-in-the-loop (interrupt).
6. **Grounded answer + refusal** — answer welded to rows; abstain when unanswerable.
7. **Data dictionary (RAG)** — retrieval as a tool.
8. **Eval harness** — assert the ACTUAL answer (the moat).
9. **Planner + writer + checker** — multi-agent subgraph (capstone).

## Pushbacks that changed the design
- Repeated: "representative, not a toy" and "just pick and build."
- Final reset: "maximize MY learning, domain doesn't matter." → dropped trading;
  chose a deterministic, concept-dense, zero-friction vehicle (SQL analyst).

## Open questions
- ~~Which model handles tool-calling well on Ollama Cloud?~~ RESOLVED: `gpt-oss:120b`
  emits OpenAI-style tool calls correctly (verified stage 2: wrote its own JOIN,
  answered Kohli 973 for 2016 — the real number).

## Success definition
Given a DB question, the agent returns an answer welded to query rows, refuses the
unanswerable ones, and the eval suite asserts the ACTUAL values — not just no-crash.
