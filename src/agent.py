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

# --- 2. The model, pointed at Ollama Cloud, TOLD about the tools ------------
llm = ChatOpenAI(
    model="gpt-oss:120b",
    base_url="https://ollama.com/v1",
    api_key=os.environ["OLLAMA_API_KEY"],
    temperature=0,
)
llm_with_tools = llm.bind_tools(TOOLS)

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
    "ONE clarifying question (e.g. 'over a minimum of how many balls faced?').\n"
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
    "charts only for single-number answers. If the user explicitly says 'chart', "
    "'graph', 'plot' or 'visualize', you MUST call plot.\n\n"
    + reference_text() +
    "\n\nOtherwise answer in one sentence with the exact number."
))


# --- 4. BRAIN node: call the model on the current conversation --------------
def brain(state: State) -> dict:
    response = llm_with_tools.invoke([SYSTEM] + state["messages"])
    return {"messages": [response]}  # appended by the reducer


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
builder = StateGraph(State)
builder.add_node("brain", brain)
builder.add_node("tools", ToolNode(TOOLS))     # runs the requested tool calls
builder.add_node("verify", verify)             # grounding gate before answering
builder.add_edge(START, "brain")               # always start at the brain
builder.add_conditional_edges("brain", should_continue, {"tools": "tools", "verify": "verify"})
builder.add_edge("tools", "brain")             # THE LOOP: after tools, think again
# verifier accepts (END) or bounces an ungrounded answer back to the brain.
builder.add_conditional_edges("verify", verify_route, {"brain": "brain", END: END})

# The checkpointer SAVES the whole state after every step, keyed by thread_id,
# and RELOADS it at the start of the next invoke with that same thread_id.
# MemorySaver keeps it in RAM (gone when the process exits). Swap in SqliteSaver
# for the same behaviour that survives a restart — identical interface.
checkpointer = MemorySaver()
# interrupt_before parks the graph in a saved checkpoint just before the `tools`
# node runs — the pause/resume from idea 3. Resume with graph.invoke(None, cfg).
graph = builder.compile(checkpointer=checkpointer, interrupt_before=["tools"])


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
    """Run a question end-to-end, auto-approving every tool (no human gate).
    Used for probing and, later, the eval harness. Returns the final text.

    The @traceable parent groups the several graph.invoke() calls (the interrupt
    makes us resume with invoke(None)) under ONE LangSmith trace per question."""
    cfg = {"configurable": {"thread_id": thread_id}}
    graph.invoke({"messages": [HumanMessage(content=text)]}, cfg)
    while True:
        snap = graph.get_state(cfg)
        if not snap.next:
            return snap.values["messages"][-1].content
        graph.invoke(None, cfg)  # resume through any interrupt


@traceable(run_type="chain", name="answer_trace")
def answer_trace(text: str, thread_id: str) -> tuple:
    """Like answer(), but also returns the full message list (the trajectory),
    so evals can check HOW the answer was reached, not just the final text."""
    cfg = {"configurable": {"thread_id": thread_id}}
    graph.invoke({"messages": [HumanMessage(content=text)]}, cfg)
    while True:
        snap = graph.get_state(cfg)
        if not snap.next:
            msgs = snap.values["messages"]
            return msgs[-1].content, msgs
        graph.invoke(None, cfg)


if __name__ == "__main__":
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-1", approve_sql=True)
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-2", approve_sql=False)
