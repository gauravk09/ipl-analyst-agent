"""Streamlit chat UI for the grounded IPL analyst agent.

Run:  streamlit run app.py
"""
import os
import re
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

# (base_url, model) presets. The chosen model MUST support tool/function calling.
PROVIDER_PRESETS = {
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Ollama Cloud": ("https://ollama.com/v1", "gpt-oss:120b"),
    "DeepSeek": ("https://api.deepseek.com", "deepseek-chat"),
    "Custom": (None, None),
}


def apply_preset():
    url, model = PROVIDER_PRESETS[st.session_state.provider]
    if url:
        st.session_state.cfg_url, st.session_state.cfg_model = url, model


def friendly_error(err):
    """Map a provider exception to a plain headline + fix."""
    s = str(err).lower()
    if any(k in s for k in ("401", "invalid api key", "incorrect api key",
                            "unauthorized", "authentication")):
        return "API key rejected", "Check your API key and Base URL in the sidebar."
    if any(k in s for k in ("tool", "function call", "function_call", "tool_calls")):
        return ("This model may not support tool calling",
                "Pick a model that supports tools — e.g. OpenAI `gpt-4o-mini`, or "
                "`gpt-oss:120b` on Ollama Cloud.")
    if any(k in s for k in ("404", "does not exist", "model_not_found", "not found")):
        return "Model not found", "Check the Model name and Base URL for this provider."
    if any(k in s for k in ("connection", "connect", "timeout", "getaddrinfo",
                            "name or service", "failed to establish")):
        return "Couldn't reach the endpoint", "Check the Base URL (and your internet)."
    return "Something went wrong", "Check your key, Base URL and Model, then try again."


sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))
from agent import (build_agent, run_agent_events, graph as DEFAULT_GRAPH,
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
                if p and os.path.exists(p) and p not in out:  # dedupe redraws
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
st.session_state.setdefault("cfg_url", "https://api.openai.com/v1")
st.session_state.setdefault("cfg_model", "gpt-4o-mini")

with st.sidebar:
    st.header("Your API key")
    st.markdown(
        "Bring your own **OpenAI-compatible** key — this app never uses anyone "
        "else's. The model must support **tool/function calling**."
    )
    st.selectbox("Provider preset", list(PROVIDER_PRESETS), key="provider",
                 on_change=apply_preset)
    api_key = st.text_input("API key", type="password", key="api_key",
                            placeholder="your provider's key")
    base_url = st.text_input("Base URL", key="cfg_url")
    model = st.text_input("Model", key="cfg_model")
    tracing = st.toggle("LangSmith tracing", value=False,
                        help="Off by default. On sends traces to LangSmith using "
                             "the LANGSMITH_API_KEY in the environment (if set).")

    with st.expander("How to try it"):
        st.markdown(
            "**1. Pick a provider preset** — it fills the Base URL + Model for you.\n\n"
            "**2. Paste that provider's API key.**\n\n"
            "**3. Ask a question**, or tap a suggestion chip.\n\n"
            "---\n"
            "**Ollama Cloud example** (free models, hosted):\n"
            "- Provider: `Ollama Cloud`\n"
            "- Base URL: `https://ollama.com/v1`\n"
            "- Model: `gpt-oss:120b`\n"
            "- Key: from [ollama.com](https://ollama.com) → Settings → API keys\n\n"
            "**Local Ollama** (on your machine): Base URL `http://localhost:11434/v1`, "
            "Model e.g. `qwen2.5` — pick one that supports tools.\n\n"
            "Tracing is optional — leave it **off** unless you want LangSmith."
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
        tid = st.session_state.thread_id
        status = st.status("Working…", expanded=True)
        answer_box = st.empty()
        content = ""
        try:
            with tracing_context(enabled=tracing):  # off unless the user opts in
                for kind, payload in run_agent_events(agent_graph, prompt, tid):
                    if kind == "status":
                        status.write(f":material/bolt: {payload}")
                    else:  # answer tokens stream into the box
                        content += payload
                        answer_box.markdown(content)
            messages = agent_graph.get_state(
                {"configurable": {"thread_id": tid}}).values["messages"]
        except Exception as e:
            status.update(label="Error", state="error")
            head, hint = friendly_error(e)
            st.error(f"**{head}** — {hint}")
            with st.expander("Technical detail"):
                st.code(str(e))
            st.session_state.messages.pop()  # drop the unanswered question
            st.stop()
        status.update(label="Done", state="complete", expanded=False)
        # A numeric answer with no tool call suggests the model ignored tools.
        used_tool = any(getattr(m, "type", None) == "tool" for m in messages)
        if not used_tool and re.search(r"\d", content) and not content.strip().endswith("?"):
            st.warning("The model answered without querying the database — it may not "
                       "support tool calling. Try `gpt-4o-mini` or `gpt-oss:120b`.")
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
