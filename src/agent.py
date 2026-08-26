"""Stage 2: the agent loop as an explicit LangGraph graph.

Run:  python src/agent.py
"""
import os
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

from tools import (run_sql as _run_sql, get_schema as _get_schema,
                   find_player as _find_player)   # grounded functions
from reference import reference_text              # curated domain knowledge

load_dotenv()

# --- 1. Wrap the plain functions as TOOLS the model is allowed to call -------
@tool
def get_schema() -> str:
    """List the tables in the cricket database and their columns. Call this
    FIRST when you are unsure of the exact table or column names."""
    return json.dumps(_get_schema())


@tool
def find_player(fragment: str) -> str:
    """Find the exact player name(s) in the data matching a fragment (e.g.
    'Kohli', 'Sharma'). Call this before filtering on a player. If it returns
    several candidates, ASK the user which one; if none, the player isn't in
    the data."""
    return json.dumps(_find_player(fragment))


@tool
def run_sql(query: str) -> str:
    """Run a READ-ONLY SQL query (SELECT/WITH only) against the IPL cricket DB
    and return the rows as JSON. Tables: matches, deliveries. If you don't know
    the columns, call get_schema first. season looks like '2016' or '2007/08'."""
    return json.dumps(_run_sql(query))


# Order matters only for how they're advertised; the model picks freely.
TOOLS = [get_schema, find_player, run_sql]

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


SYSTEM = SystemMessage(content=(
    "You are a cricket data analyst for the IPL. Follow these rules exactly:\n"
    "1. GROUND: Answer only using numbers returned by run_sql. Never invent a statistic.\n"
    "2. SCHEMA: If unsure of table or column names, call get_schema first.\n"
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
    "6. PLAYERS: To filter on a player, call find_player first. If it returns "
    "several candidates, ASK the user which one; if none, refuse.\n"
    "7. FRANCHISES: A team that was renamed appears under multiple names in the "
    "data. When the user names such a franchise, match ALL its names (see below).\n\n"
    + reference_text() +
    "\n\nOtherwise answer in one sentence with the exact number."
))


# --- 4. BRAIN node: call the model on the current conversation --------------
def brain(state: State) -> dict:
    response = llm_with_tools.invoke([SYSTEM] + state["messages"])
    return {"messages": [response]}  # appended by the reducer


# --- 5. ROUTER: did the model ask for a tool, or is it done? ----------------
def should_continue(state: State) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


# --- 6. Build the graph: nodes, then edges ----------------------------------
builder = StateGraph(State)
builder.add_node("brain", brain)
builder.add_node("tools", ToolNode(TOOLS))     # runs the requested tool calls
builder.add_edge(START, "brain")               # always start at the brain
builder.add_conditional_edges("brain", should_continue, {"tools": "tools", END: END})
builder.add_edge("tools", "brain")             # THE LOOP: after tools, think again

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


def answer(text: str, thread_id: str) -> str:
    """Run a question end-to-end, auto-approving every tool (no human gate).
    Used for probing and, later, the eval harness. Returns the final text."""
    cfg = {"configurable": {"thread_id": thread_id}}
    graph.invoke({"messages": [HumanMessage(content=text)]}, cfg)
    while True:
        snap = graph.get_state(cfg)
        if not snap.next:
            return snap.values["messages"][-1].content
        graph.invoke(None, cfg)  # resume through any interrupt


if __name__ == "__main__":
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-1", approve_sql=True)
    ask("Which bowler has taken the most wickets, and how many?",
        thread_id="appr-2", approve_sql=False)
