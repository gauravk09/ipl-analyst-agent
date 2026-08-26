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

from tools import run_sql as _run_sql, get_schema as _get_schema  # grounded functions

load_dotenv()

# --- 1. Wrap the plain functions as TOOLS the model is allowed to call -------
@tool
def get_schema() -> str:
    """List the tables in the cricket database and their columns. Call this
    FIRST when you are unsure of the exact table or column names."""
    return json.dumps(_get_schema())


@tool
def run_sql(query: str) -> str:
    """Run a READ-ONLY SQL query (SELECT/WITH only) against the IPL cricket DB
    and return the rows as JSON. Tables: matches, deliveries. If you don't know
    the columns, call get_schema first. season looks like '2016' or '2007/08'."""
    return json.dumps(_run_sql(query))


# Order matters only for how they're advertised; the model picks freely.
TOOLS = [get_schema, run_sql]

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
    "You are a cricket data analyst for the IPL. If you are unsure of the table "
    "or column names, call get_schema first. Then answer ONLY using numbers "
    "returned by run_sql: write SQL, read the rows, then answer in one sentence "
    "with the exact number. If run_sql cannot answer, say so plainly. Never "
    "invent a statistic."
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
graph = builder.compile(checkpointer=checkpointer)


def run_turn(text: str, thread_id: str) -> None:
    """One conversational turn. The thread_id selects WHICH conversation's
    saved memory to load and append to."""
    config = {"configurable": {"thread_id": thread_id}}
    result = graph.invoke({"messages": [HumanMessage(content=text)]}, config=config)
    print(f"[{thread_id}] Q: {text}")
    print(f"[{thread_id}] A: {result['messages'][-1].content}\n")


if __name__ == "__main__":
    # Same thread -> the follow-up can rely on memory ("he", "next season").
    run_turn("Who scored the most runs in IPL 2016, and how many?", thread_id="chat-1")
    run_turn("How many did he score the next season?", thread_id="chat-1")

    # A DIFFERENT thread has its own blank memory -> "he" means nothing here.
    run_turn("How many did he score the next season?", thread_id="chat-2")
