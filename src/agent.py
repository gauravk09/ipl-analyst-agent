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

from tools import run_sql as _run_sql  # our grounded, read-only function

load_dotenv()

# --- 1. Wrap the plain function as a TOOL the model is allowed to call -------
@tool
def run_sql(query: str) -> str:
    """Run a READ-ONLY SQL query (SELECT/WITH only) against the IPL cricket DB
    and return the rows as JSON.

    Tables:
      matches(match_id, date, season, city, venue, team1, team2,
              toss_winner, toss_decision, winner, win_by_runs, win_by_wickets,
              result, player_of_match, gender, match_type)
      deliveries(match_id, innings, batting_team, over, ball,
                 batter, bowler, non_striker,
                 runs_batter, runs_extras, runs_total,
                 wicket_kind, player_out, fielders)
    Notes: season looks like '2016' or '2007/08'. runs_batter excludes extras.
    """
    return json.dumps(_run_sql(query))


TOOLS = [run_sql]

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
    "You are a cricket data analyst for the IPL. Answer ONLY using numbers "
    "returned by the run_sql tool. Write SQL, read the rows, then answer in one "
    "sentence with the exact number. If run_sql cannot answer, say so plainly. "
    "Never invent a statistic."
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
graph = builder.compile()


if __name__ == "__main__":
    question = "Who scored the most runs in IPL season 2016, and how many?"
    print(f"Q: {question}\n")
    for step in graph.stream(
        {"messages": [HumanMessage(content=question)]},
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()
