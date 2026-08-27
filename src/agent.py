"""Stage 2: the agent loop as an explicit LangGraph graph.

Run:  python src/agent.py
"""
import os
import re
import json
from typing import Annotated
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver
from langsmith import traceable   # LangSmith tracing (auto-captures the graph)

from tools import (run_sql as _run_sql, get_schema as _get_schema,
                   find_player as _find_player, plot as _plot)   # grounded functions
from reference import reference_text, SEASON_YEAR  # curated domain knowledge

load_dotenv()

# --- 1. Wrap the plain functions as TOOLS the model is allowed to call -------
@tool
def get_schema() -> str:
    """List the tables in the cricket database and their columns. Call this
    FIRST when you are unsure of the exact table or column names."""
    return json.dumps(_get_schema())


@tool
def find_player(name: str) -> str:
    """Find the exact player name(s) in the data for a full or partial name
    ('Virat Kohli', 'Ishant Sharma', 'Kohli'). The data uses 'initial surname'
    form (V Kohli, I Sharma); this handles that. Call it before filtering on a
    player. Several candidates -> ASK which one; none -> the player isn't here."""
    return json.dumps(_find_player(name))


@tool
def plot(chart_type: str, title: str, series: list,
         ylabel: str = "", ylabel2: str = "") -> str:
    """Draw a chart and save it. chart_type is the default 'bar' or 'line'. series
    is a list of {"name", "points": [[label, value], ...]} — one entry per
    player/category. Each series may ALSO set "type" ('bar'|'line') and "axis"
    ('primary'|'secondary'). For two quantities on different scales (e.g.
    strike-rate vs runs), put one as bars on the primary axis and the other as a
    line on the secondary axis (axis:'secondary'), and set ylabel + ylabel2.
    Values come from run_sql, never invented. After drawing, ALSO state the key
    numbers in words."""
    return json.dumps(_plot(chart_type, title, series, ylabel=ylabel, ylabel2=ylabel2))


@tool
def run_sql(query: str) -> str:
    """Run a READ-ONLY SQL query (SELECT/WITH only) against the IPL cricket DB
    and return the rows as JSON. Tables: matches, deliveries. If you don't know
    the columns, call get_schema first. season looks like '2016' or '2007/08'."""
    return json.dumps(_run_sql(query))


# Order matters only for how they're advertised; the model picks freely.
TOOLS = [get_schema, find_player, run_sql, plot]

# --- 2. The model (any OpenAI-compatible endpoint), TOLD about the tools -----
DEFAULT_BASE_URL = "https://ollama.com/v1"
DEFAULT_MODEL = "gpt-oss:120b"  # 20b is ~2.6x faster but drops to 9/11 on evals


def make_llm(api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
             reasoning_effort=None):
    """Bind the tools to an OpenAI-compatible chat model. Any key/endpoint works
    (OpenAI, Ollama Cloud, DeepSeek, …), so a shared app can use the USER's key.
    reasoning_effort='low' roughly halves latency on gpt-oss (reasoning tokens
    dominate); only passed when set, since non-reasoning models reject it."""
    kwargs = dict(model=model, base_url=base_url, api_key=api_key, temperature=0)
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    return ChatOpenAI(**kwargs).bind_tools(TOOLS)


# Default model from .env (Ollama Cloud), with low reasoning effort for speed.
# An empty key is fine at import time — the app builds its own model from a
# user-supplied key instead of this default.
llm_with_tools = make_llm(os.environ.get("OLLAMA_API_KEY", ""), reasoning_effort="low")

# --- 3. STATE: the shared notepad. Just a growing list of messages ----------
# add_messages is a "reducer": when a node returns messages, they are APPENDED
# to the list rather than replacing it. That append is what accumulates the
# question, the model's tool call, and the tool's rows over the loop.
class State(TypedDict):
    messages: Annotated[list, add_messages]
    verify_attempts: int   # plain overwrite channel (no reducer): a retry counter


# Introspect the live schema once at startup and inject it, so the model never
# guesses a column name (still generic — works on any DB — but always present).
SCHEMA_TEXT = "\n".join(
    f"  {t}({', '.join(c['name'] for c in cols)})" for t, cols in _get_schema().items()
)

SYSTEM = SystemMessage(content=(
    "You are a cricket data analyst for the IPL. The database schema — use ONLY "
    "these columns, never invent one:\n" + SCHEMA_TEXT + "\n\nFollow these rules exactly:\n"
    "1. GROUND: Answer only using numbers returned by run_sql. Never invent a statistic.\n"
    "2. SCHEMA: The schema above is authoritative. If a query errors with 'no such "
    "column', you guessed — re-read the schema above; never invent a column name.\n"
    "3. EMPTY/ZERO RESULTS: If a query returns no rows or a 0/NULL aggregate, do "
    "NOT assume the answer is zero yet. First verify that each value you filtered "
    "on actually EXISTS in its column (e.g. SELECT DISTINCT season). If a filter "
    "value is absent (e.g. season '2020' when the data uses '2020/21'), your query "
    "was wrong — fix it and rerun. Only if every filter value truly exists is a "
    "zero a real answer, which you should then report plainly.\n"
    "4. AMBIGUOUS RATE STATS: If asked for an extreme of a rate/ratio (highest "
    "strike rate, best economy or average) with no minimum sample specified, do "
    "NOT return an unqualified extreme and do NOT silently pick a threshold. Ask "
    "ONE clarifying question (e.g. 'over a minimum of how many balls faced?'). But "
    "if the user DID give a minimum, use it and answer directly — never ask again.\n"
    "5. REFUSE: If the data genuinely cannot answer (not in the schema), say so.\n"
    "6. PLAYERS: To resolve any player name, use the find_player tool — do NOT "
    "hand-write DISTINCT queries. If it returns exactly ONE candidate, USE it "
    "(do not ask — one match is unambiguous). If it returns several, ask which "
    "one, unless one exactly matches what the user wrote (then use that). If it "
    "returns none, refuse.\n"
    "7. FRANCHISES: A team that was renamed appears under multiple names in the "
    "data. When the user names such a franchise, match ALL its names (see below).\n"
    "8. CHARTS: If the answer is a series (per season/year) OR a comparison across "
    "categories or players, you MUST call plot. Pass series as a list of {name, "
    "points:[[label,value],...]} — one entry per line/group (one per player for a "
    "comparison). Use values from run_sql. Each series may set type ('bar'/'line') "
    "and axis ('primary'/'secondary'); when two quantities have different scales "
    "(e.g. strike-rate vs runs), use bars on the primary axis and a line on the "
    "secondary axis, with ylabel and ylabel2. Then also state the key numbers. Skip "
    "charts only for single-number answers. If the user asks for a chart, graph, "
    "plot, bar, line, trend or a secondary axis, you MUST call plot.\n"
    "9. CONCISE & ON-SCOPE: Answer ONLY what the user asked; do NOT volunteer extra "
    "statistics. Every number you state must be grounded by a query, so extra numbers "
    "mean extra work and a cluttered answer — give the requested figure(s) and stop.\n"
    "10. SPEED: Issue INDEPENDENT tool calls together in ONE turn (e.g. resolve both "
    "players at once, or run two independent queries together) — they run in parallel. "
    "Prefer ONE consolidated query over several small ones.\n\n"
    + reference_text() +
    "\n\nOtherwise answer in one sentence with the exact number."
))


# --- 5. ROUTER: tool wanted -> tools; else -> verify (not straight to END) --
def should_continue(state: State) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else "verify"


# --- 5b. VERIFIER: a deterministic grounding gate before any answer ships ---
REFUSE_MARKERS = ("cannot", "can't", "does not contain", "doesn't contain",
                  "no information", "not in the", "unable", "don't have",
                  "do not have", "not available", "sorry")
MAX_VERIFY = 2


def _numbers(text: str) -> set:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text or "")}


def _grounded_numbers(messages) -> set:
    """Numbers that actually came out of run_sql results. A season label in a
    result also grounds its human calendar year (so an answer may report '2008'
    for a result containing '2007/08')."""
    out = set()
    for m in messages:
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "run_sql":
            content = m.content or ""
            out |= _numbers(content)
            for label, year in SEASON_YEAR.items():
                if label in content:
                    out.add(year)
    return out


def verify(state: State) -> dict:
    """Reject an answer that states a number which came from neither a run_sql
    result NOR the user's own question. Clarifications and refusals pass through."""
    msgs = state["messages"]
    content = msgs[-1].content or ""
    low = content.lower().replace("’", "'")
    if content.strip().endswith("?") or any(k in low for k in REFUSE_MARKERS):
        return {}  # a clarify/refuse — nothing to ground, accept

    question_nums = set()
    for m in msgs:
        if getattr(m, "type", None) == "human" and not str(m.content).startswith("[verifier]"):
            question_nums |= _numbers(m.content)
    suspicious = _numbers(content) - _grounded_numbers(msgs) - question_nums

    attempts = state.get("verify_attempts", 0)
    if suspicious and attempts < MAX_VERIFY:
        note = HumanMessage(content=(
            f"[verifier] These numbers in your answer did not come from any run_sql "
            f"result: {sorted(suspicious)}. Query the database to derive them, then "
            f"give a corrected answer."))
        return {"messages": [note], "verify_attempts": attempts + 1}
    return {}  # grounded, or gave up after MAX_VERIFY retries


def verify_route(state: State) -> str:
    last = state["messages"][-1]
    bounced = getattr(last, "type", None) == "human" and str(last.content).startswith("[verifier]")
    return "brain" if bounced else END


# --- 6. Build the graph: nodes, then edges ----------------------------------
def build_graph(llm_with_tools, checkpointer=None):
    """Compile the agent graph around a given model. Factored into a function so
    the app can build a graph per user (their own key) without touching tests/CLI."""
    def brain(state: State) -> dict:  # the LLM call, closed over this model
        return {"messages": [llm_with_tools.invoke([SYSTEM] + state["messages"])]}

    builder = StateGraph(State)
    builder.add_node("brain", brain)
    builder.add_node("tools", ToolNode(TOOLS))     # runs the requested tool calls
    builder.add_node("verify", verify)             # grounding gate before answering
    builder.add_edge(START, "brain")               # always start at the brain
    builder.add_conditional_edges("brain", should_continue, {"tools": "tools", "verify": "verify"})
    builder.add_edge("tools", "brain")             # THE LOOP: after tools, think again
    builder.add_conditional_edges("verify", verify_route, {"brain": "brain", END: END})
    # MemorySaver keeps per-conversation state in RAM; interrupt_before parks the
    # graph just before the tools node (pause/resume for human-in-the-loop).
    return builder.compile(checkpointer=checkpointer or MemorySaver(),
                           interrupt_before=["tools"])


def build_agent(api_key: str, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
    """A graph using a caller-supplied OpenAI-compatible model — so a shared app
    can run on the USER's key instead of the server's .env. Auto-enables low
    reasoning effort for gpt-oss (big speedup); left off for models that reject it."""
    effort = "low" if "gpt-oss" in model.lower() else None
    return build_graph(make_llm(api_key, base_url, model, reasoning_effort=effort))


graph = build_graph(llm_with_tools)  # default (from .env), used by the CLI + tests


def run_agent(graph, text: str, thread_id: str) -> tuple:
    """Invoke, then resume through any interrupts, until done. Returns
    (final_text, messages). Works on any graph (default or a per-user one)."""
    cfg = {"configurable": {"thread_id": thread_id}}
    graph.invoke({"messages": [HumanMessage(content=text)]}, cfg)
    while True:
        snap = graph.get_state(cfg)
        if not snap.next:
            msgs = snap.values["messages"]
            return msgs[-1].content, msgs
        graph.invoke(None, cfg)


_STATUS = {
    "get_schema": lambda a: "Reading the database schema",
    "find_player": lambda a: f"Resolving player: {a.get('name', '')}",
    "run_sql": lambda a: "Running a query",
    "plot": lambda a: "Drawing the chart",
}


def run_agent_events(graph, text: str, thread_id: str):
    """Generator yielding ('status', text) for each tool the agent is about to run,
    and ('token', text) for the streamed answer. Lets the UI show live progress
    during the tool phase, then the answer typing out."""
    cfg = {"configurable": {"thread_id": thread_id}}
    inp = {"messages": [HumanMessage(content=text)]}
    while True:
        for mode, data in graph.stream(inp, cfg, stream_mode=["updates", "messages"]):
            if mode == "updates":
                brain_out = data.get("brain")
                if brain_out:  # the brain just decided — announce any tools it wants
                    for tc in getattr(brain_out["messages"][-1], "tool_calls", None) or []:
                        fn = _STATUS.get(tc["name"])
                        yield ("status", fn(tc["args"]) if fn else tc["name"])
                if (data.get("verify") or {}).get("messages"):
                    yield ("status", "Re-checking figures (verifier)")
            else:  # ('messages') — stream only the brain's answer tokens
                chunk, meta = data
                if meta.get("langgraph_node") == "brain":
                    piece = getattr(chunk, "content", "") or ""
                    if piece:
                        yield ("token", piece)
        if not graph.get_state(cfg).next:
            return
        inp = None  # resume past the interrupt


def run_agent_stream(graph, text: str, thread_id: str):
    """Generator: yields answer text chunks as the model produces them (for a
    live typing effect), resuming through interrupts. Tool-call turns have empty
    content so they yield nothing; the final answer streams token by token.
    After it finishes, read the full trajectory with graph.get_state(...)."""
    cfg = {"configurable": {"thread_id": thread_id}}
    inp = {"messages": [HumanMessage(content=text)]}
    while True:
        for chunk, meta in graph.stream(inp, cfg, stream_mode="messages"):
            # Only the brain node's text is the answer; tool results (from the
            # tools node) also flow through here and must be skipped.
            if meta.get("langgraph_node") == "brain":
                piece = getattr(chunk, "content", "") or ""
                if piece:
                    yield piece
        if not graph.get_state(cfg).next:
            return
        inp = None  # resume past the interrupt


def ask(text: str, thread_id: str, approve_sql: bool) -> None:
    """Run one question. The graph pauses before every tool. We auto-approve
    read-only get_schema, but gate run_sql on the human's decision."""
    cfg = {"configurable": {"thread_id": thread_id}}
    print(f"Q: {text}")
    graph.invoke({"messages": [HumanMessage(content=text)]}, cfg)  # runs to first pause

    while True:
        snap = graph.get_state(cfg)
        if not snap.next:                        # nothing pending -> finished
            print(f"A: {snap.values['messages'][-1].content}\n")
            return
        pending = snap.values["messages"][-1].tool_calls
        for tc in pending:
            arg = tc["args"].get("query", tc["args"])
            print(f"  ⏸  wants {tc['name']}: {arg}")
        if {tc["name"] for tc in pending} == {"get_schema"}:
            print("  ✓ auto-approved (read-only schema lookup)")
            graph.invoke(None, cfg)              # resume
        elif approve_sql:
            print("  ✓ human APPROVED the SQL — running")
            graph.invoke(None, cfg)              # resume
        else:
            print("  ✗ human REJECTED — query never touched the DB\n")
            return


@traceable(run_type="chain", name="answer")
def answer(text: str, thread_id: str) -> str:
    """Run a question on the default graph, auto-approving tools. Returns the text.
    The @traceable parent groups the several resume-invokes into ONE trace."""
    return run_agent(graph, text, thread_id)[0]


@traceable(run_type="chain", name="answer_trace")
def answer_trace(text: str, thread_id: str) -> tuple:
    """Like answer(), but also returns the full message trajectory (for evals)."""
    return run_agent(graph, text, thread_id)


if __name__ == "__main__":
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-1", approve_sql=True)
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-2", approve_sql=False)
