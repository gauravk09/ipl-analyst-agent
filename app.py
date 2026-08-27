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


sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
from agent import (build_agent, run_agent, graph as DEFAULT_GRAPH,
                   DEFAULT_BASE_URL, DEFAULT_MODEL)
from langsmith.run_helpers import tracing_context


@st.cache_resource(show_spinner=False)
def get_user_graph(api_key, base_url, model):
    """One compiled graph per (key, base_url, model) — the USER's own model, so
    the app never uses the server's .env keys."""
    return build_agent(api_key, base_url, model)


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


def render_charts(charts, prefix):
    """Show each chart with a download button (keys unique per message)."""
    for i, path in enumerate(charts):
        st.image(path)
        with open(path, "rb") as f:
            st.download_button(
                "Download chart", f.read(), file_name=os.path.basename(path),
                mime="image/png", key=f"dl_{prefix}_{i}", icon=":material/download:")


if "thread_id" not in st.session_state:
    st.session_state.thread_id = f"ui-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Your API key")
    st.markdown(
        "Bring your own **OpenAI-compatible** key — this app never uses anyone "
        "else's. Works with OpenAI, Ollama Cloud, DeepSeek, or any compatible endpoint."
    )
    api_key = st.text_input("API key", type="password",
                            placeholder="sk-…", label_visibility="collapsed")
    base_url = st.text_input("Base URL", value="https://api.openai.com/v1")
    model = st.text_input("Model", value="gpt-4o-mini")
    tracing = st.toggle("LangSmith tracing", value=False,
                        help="Off by default. On sends traces to LangSmith using "
                             "the LANGSMITH_API_KEY in the environment (if set).")

    with st.expander("How to try it"):
        st.markdown(
            "1. Get a key from your provider (e.g. platform.openai.com).\n"
            "2. Paste it above. For OpenAI keep the defaults; for others set the "
            "Base URL + Model (e.g. `https://ollama.com/v1` + `gpt-oss:120b`).\n"
            "3. Ask a question, or tap a suggestion chip.\n"
            "4. Tracing is optional — leave it **off** unless you want LangSmith."
        )

    st.divider()
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

# Use the user's own key if given; else fall back to .env (local dev); else stop.
have_env = bool(os.environ.get("OLLAMA_API_KEY"))
agent_graph = get_user_graph(api_key, base_url, model) if api_key else (
    DEFAULT_GRAPH if have_env else None)
if agent_graph is None:
    st.info("👈 Enter an OpenAI-compatible API key in the sidebar to start.")
    st.stop()

for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        render_charts(msg.get("charts", []), prefix=str(idx))
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
            with tracing_context(enabled=tracing):  # off unless the user opts in
                content, messages = run_agent(
                    agent_graph, prompt, st.session_state.thread_id)
        st.markdown(content)
        charts = charts_from(messages)
        render_charts(charts, prefix="live")
        sql = queries_from(messages)
        if sql:
            with st.expander("SQL the agent ran"):
                for q in sql:
                    st.code(q, language="sql")
    st.session_state.messages.append(
        {"role": "assistant", "content": content, "sql": sql, "charts": charts})
    st.rerun()
