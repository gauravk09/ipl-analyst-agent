# Tracing the agent with LangSmith

How this agent is instrumented for observability, how to read a trace, and how to
talk about it in an interview.

## 1. Setup

Install and set env vars (in `.env`, gitignored — never commit the key):

```
LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=<your key from smith.langchain.com → Settings → API Keys>
LANGSMITH_PROJECT=ipl-analyst-agent
# legacy aliases so any langchain version picks it up:
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<same key>
LANGCHAIN_PROJECT=ipl-analyst-agent
```

`pip install langsmith` (already in `requirements.txt`).

**That's the whole wiring for a LangChain/LangGraph app** — tracing is *automatic*
from the env vars. No code change is needed to capture the run tree. We added just
one thing (see §6): a `@traceable` parent on `answer()` / `answer_trace()`.

Run anything that calls the agent, then look in the UI:

```bash
./.venv/bin/python src/agent.py         # or the Streamlit app, or the eval
./.venv/bin/python scripts/trace_check.py    # confirms traces landed + prints spans
./.venv/bin/python scripts/trace_failures.py # forces an LLM timeout + a tool error
```

Traces appear at **smith.langchain.com → project `ipl-analyst-agent`**.

## 2. The vocabulary — trace, run, span

- A **trace** is one end-to-end execution — everything that happened to answer one
  question. It's a *tree* of steps.
- A **span** (LangSmith calls it a **run**) is a single unit of work in that tree:
  one LLM call, one tool call, one graph node. Spans **nest** — a child span happened
  inside its parent.
- The **root** span is the whole request; leaves are the individual LLM/tool calls.

Our tree for one question:

```
answer                     (root — the @traceable parent)
└─ LangGraph                (the graph run)
   ├─ brain    → ChatOpenAI (LLM span: prompt, response, tokens, latency)
   ├─ tools    → run_sql    (tool span: query in, rows out)
   ├─ brain    → ChatOpenAI (LLM span)
   ├─ verify                (plain span: the grounding gate)
   └─ … loops repeat
```

## 3. What is captured at each step

| Span type | What LangSmith records |
|---|---|
| **LLM** (`ChatOpenAI`) | the exact prompt, the response, **token counts**, **latency**, model + params, and any error. Cost is derived from tokens. |
| **Tool** (`run_sql`, `find_player`, `get_schema`) | the inputs (the SQL string) and the outputs (the rows / error). |
| **Chain / node** (`brain`, `verify`, the graph) | inputs/outputs of that step and its duration; groups its children. |
| **Errors** | status `error`, the exception message, and the stack trace, on whichever span failed. |

Verified live: LLM spans showed `tokens=1107…1832` and sub-second-to-2.7s latencies;
tool spans showed each `run_sql`; forced failures showed `APITimeoutError` and a
tool `RuntimeError` as red error runs.

## 4. Debugging a bad run (the workflow)

1. Open the trace for the bad request.
2. Walk the tree to the **red span** (or the one with wrong output).
3. Inspect **that span's inputs and outputs** — the exact prompt, the exact SQL, the
   exact rows.
4. Fix the layer that's actually wrong:
   - wrong number → look at the `run_sql` span: was the SQL wrong? (e.g. filtered a
     season label that doesn't exist — the "0 sixes" bug would show an empty result
     span).
   - hallucinated tool argument → the LLM span before the tool.
   - lost context → the prompt in the LLM span is missing history.
   - timeout / 500 → a red LLM span with the provider error.

The point: you fix the **right** layer because you can see each layer's I/O, instead
of guessing from a final wrong answer.

## 5. LangSmith vs OpenTelemetry

- **OpenTelemetry (OTel)** is a vendor-neutral open standard for telemetry (traces,
  metrics, logs) across *any* system. You instrument once and export to any backend
  (Jaeger, Datadog, Grafana, Honeycomb). It is not LLM-aware — a span is a generic
  span.
- **LangSmith** is *LLM-native*: it understands prompts, token usage, tool calls, and
  it ties into **evals and datasets** (turn traced runs into a test set, run
  LLM-as-judge on production traces). Great UI for prompt/response debugging.

**When to use which:** LangSmith when you're in the LangChain/LangGraph ecosystem and
want LLM-aware debugging + evals in one place. OTel when you need one standard across a
polyglot microservice stack, or must ship to an existing observability backend. They
compose — LangChain can also export via OTel — so "LangSmith for LLM depth, OTel for
system-wide standardization" is a defensible answer.

## 6. The one code change we made, and why

The agent uses `interrupt_before=["tools"]`, so `answer()` resumes with several
`graph.invoke(None)` calls. Each `invoke` is its own root run — so **one question would
fragment into several traces.** We wrapped `answer()` / `answer_trace()` in
`@traceable(run_type="chain", name="answer")`, which opens one parent run; all the
sub-invokes nest under it, giving **one clean trace per question.** This is the kind of
"gotcha" worth mentioning: auto-tracing captures everything, but multi-call control
flow needs a parent span to read as a single request.

## 7. Interview Q&A

**Q1. What is a trace, and what's a span?**
A trace is one end-to-end request rendered as a tree of steps; a span (run) is one step
— an LLM call, a tool call, a node. Spans nest; the root is the whole request.

**Q2. How would you debug a bad agent run in production?**
Open its trace, walk to the failing/anomalous span, read that span's exact inputs and
outputs, and fix the layer that's actually wrong — wrong SQL lives in the tool span, a
bad tool argument in the LLM span before it, a context loss in the prompt. You debug the
right layer instead of guessing from the final answer.

**Q3. LangSmith vs OpenTelemetry — when each?**
OTel is a vendor-neutral standard for any system, exportable to any backend but not
LLM-aware. LangSmith is LLM-native (prompts, tokens, tool calls) with evals/datasets
built in. LangSmith for LLM-depth debugging inside the LangChain ecosystem; OTel for
polyglot, system-wide standardization or an existing backend. They can compose.

**Q4. What do you capture per LLM call, and why does it matter?**
The prompt, the response, prompt/completion tokens, latency, model + params, and errors.
Tokens → cost and blow-up detection; latency → p95 monitoring; prompt/response → catching
regressions when you change a prompt.

**Q5. How would you MONITOR this in production, not just debug one run?**
Traces plus aggregates: p50/p95 latency, error rate, tokens/cost per request, tool
failure rate; alert on thresholds; sample at high volume. Attach metadata (thread_id,
user, version) so you can slice. Run **online evals** (heuristics or LLM-as-judge) on a
sample of production traces, and capture user feedback (👍/👎) onto the trace. That's the
difference between "I can see one trace" and "I know the system's health."

**Q6 (bonus). The three pillars of observability?**
Traces (the story of one request), metrics (aggregate numbers over time), logs (discrete
events). Observability is all three; a trace is the LLM-agent's most useful one because
the failure is usually *where* in the multi-step flow it went wrong.
