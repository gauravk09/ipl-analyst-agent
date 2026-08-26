# Decisions

Finalised choices only. Status: **LOCKED** / **AGREED** / **PARKED**.

## D1 — Project: a grounded data-analyst agent over SQLite — LOCKED
Ask a database questions in plain English. A LangGraph agent explores the schema,
writes SQL, runs it, recovers from its own errors, and answers ONLY from the rows
it got back — refusing when the DB can't answer.
- **Why (learning vehicle):** every agentic concept has a natural home; SQL is
  deterministic so evals can assert the real answer; grounding + refusal are
  unavoidable; zero data friction; domain-neutral (swap the DB later).
- **Rejected:** trading/news engine (data-sourcing friction, non-deterministic,
  weak open data for the interesting parts). Parked, not deleted.

## D2 — Learn on LangGraph — LOCKED
Model the agent loop as an explicit graph (nodes / edges / state).

## D3 — Model provider: Ollama Cloud, DeepSeek backup — LOCKED
Both via the OpenAI-compatible API → one client class, two configs.
Primary: `gpt-oss:120b` on Ollama Cloud. Keys in `.env` (gitignored).

## D4 — Data: bundled Chinook sample DB — LOCKED
Chinook (a music store: artists, albums, tracks, customers, invoices) as a ~1 MB
local SQLite file. Rich enough for joins, aggregations, and ambiguous questions.
- **Why:** standard, small, free, offline; realistic schema without setup.

## D5 — Grounding & guardrails — LOCKED
- Answers come ONLY from query rows; the model never invents a number.
- Refuse / abstain when the schema can't answer.
- `run_sql` is READ-ONLY (SELECT only) — no writes, no DDL. Enforced in code,
  not by asking the model nicely.
