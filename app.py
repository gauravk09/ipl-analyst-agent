"""Streamlit chat UI for the grounded IPL analyst agent.

Run:  streamlit run app.py
"""
import os
import json
import uuid
import pathlib
import sys

import streamlit as st

st.set_page_config(page_title="IPL analyst agent",
                   page_icon=":material/sports_cricket:", layout="centered")

# The agent graph, in DOT so it renders natively (no external image needed).
GRAPH_DOT = """
digraph {
  rankdir=LR; node [shape=box, style=rounded, fontname="Helvetica"];
  start [shape=circle, label="", width=0.2];
  end   [shape=doublecircle, label="", width=0.2];
  start -> brain;
  brain -> tools  [label="tool?"];
  tools -> brain;
  brain -> verify [label="answer"];
  verify -> brain [label="ungrounded"];
  verify -> end   [label="ok"];
}
"""

SUGGESTIONS = {
    ":orange[:material/sports_cricket:] Most runs in 2016": "Who scored the most runs in IPL 2016?",
    ":blue[:material/emoji_events:] Most titles": "Which team has won the most IPL matches overall?",
    ":green[:material/query_stats:] Sixes in 2020": "How many sixes were hit in IPL 2020?",
    ":violet[:material/groups:] Delhi total wins": "How many matches have Delhi Capitals won in total?",
}


@st.cache_resource
def load_agent():
    """Build the LangGraph agent once and reuse it across reruns."""
    sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
    from agent import answer_trace
    return answer_trace


def queries_from(messages) -> list:
    """Pull the run_sql queries the agent actually executed, for transparency."""
    out = []
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            if tc["name"] == "run_sql":
                out.append(tc["args"].get("query", ""))
    return out


def charts_from(messages) -> list:
    """Pull chart image paths the plot tool produced."""
    out = []
    for m in messages:
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "plot":
            try:
                p = json.loads(m.content).get("path")
                if p and os.path.exists(p):
                    out.append(p)
            except (ValueError, TypeError):
                pass
    return out


answer_trace = load_agent()

if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"ui-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("About")
    st.markdown(
        "Ask the IPL database in plain English. Every number is **computed by SQL "
        "and verified** — the agent refuses when the data can't answer and asks "
        "when a question is ambiguous. It never invents a statistic."
    )
    st.subheader("The agent graph")
    st.graphviz_chart(GRAPH_DOT)
    st.caption(
        "**brain** writes SQL → **tools** run it → **verify** checks every number "
        "is grounded before answering; ungrounded answers bounce back."
    )
    st.subheader("Data")
    st.markdown(
        "**matches** (1,243) · **deliveries** (295,732)\n\nIPL 2008–2026, from Cricsheet."
    )

st.title(":material/sports_cricket: IPL analyst agent")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        for chart in msg.get("charts", []):
            st.image(chart)
        if msg.get("sql"):
            with st.expander("SQL the agent ran"):
                for q in msg["sql"]:
                    st.code(q, language="sql")

prompt = None
if not st.session_state.messages:
    picked = st.pills("Try asking:", list(SUGGESTIONS), label_visibility="collapsed")
    if picked:
        prompt = SUGGESTIONS[picked]

typed = st.chat_input("Ask about the IPL…", submit_mode="disable")
if typed:
    prompt = typed

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Querying the database…"):
            content, messages = answer_trace(prompt, st.session_state.thread_id)
        st.markdown(content)
        charts = charts_from(messages)
        for chart in charts:
            st.image(chart)
        sql = queries_from(messages)
        if sql:
            with st.expander("SQL the agent ran"):
                for q in sql:
                    st.code(q, language="sql")
    st.session_state.messages.append(
        {"role": "assistant", "content": content, "sql": sql, "charts": charts})
    st.rerun()
