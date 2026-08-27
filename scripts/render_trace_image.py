"""Render a clean LangSmith trace's key spans into a PNG for the README.

Runs one simple question, then draws the meaningful spans (brain LLM calls, tool
calls, verify) from that REAL trace — pulled via the LangSmith SDK.
Run: python scripts/render_trace_image.py
"""
import os
import sys
import time
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from langsmith import Client

load_dotenv()
sys.path.insert(0, "src")
from agent import answer

Q = "How many matches have Delhi Capitals won in total?"
answer(Q, "readme-trace")           # create a clean, simple trace
time.sleep(4)                        # let it upload

client = Client()
project = os.environ["LANGSMITH_PROJECT"]
root = next(r for r in client.list_runs(project_name=project, is_root=True, limit=10)
            if r.name in ("answer", "answer_trace"))
runs = [r for r in client.list_runs(project_name=project, limit=300)
        if getattr(r, "trace_id", None) == root.trace_id]

# Keep only meaningful spans, in time order.
keep = [r for r in runs if r.run_type in ("llm", "tool")
        or (r.run_type == "chain" and r.name == "verify")]
keep.sort(key=lambda r: r.start_time)

rows = [("root", f"answer  ·  question: {Q}", "#e6edf3")]
for r in keep:
    d = f"{(r.end_time - r.start_time).total_seconds():.2f}s" if r.end_time else "…"
    if r.run_type == "llm":
        rows.append(("llm", f"brain → LLM   ·   {r.total_tokens} tokens   ·   {d}", "#58a6ff"))
    elif r.run_type == "tool":
        try:
            raw = r.inputs.get("input", "")
            arg = json.loads(raw) if isinstance(raw, str) and raw.startswith("{") else raw
        except Exception:
            arg = r.inputs
        rows.append(("tool", f"tool: {r.name}({str(arg)[:60]})", "#3fb950"))
    else:
        rows.append(("verify", f"verify   ·   grounding gate   ·   {d}", "#bc8cff"))

fig, ax = plt.subplots(figsize=(11, 0.55 * len(rows) + 0.6))
ax.axis("off")
ax.set_xlim(0, 1)
ax.set_ylim(0, len(rows) + 0.5)
for i, (kind, txt, color) in enumerate(rows):
    y = len(rows) - i
    indent = 0.02 if kind == "root" else 0.06
    weight = "bold" if kind == "root" else "normal"
    ax.text(indent, y, ("" if kind == "root" else "└─ ") + txt,
            family="monospace", fontsize=12.5, color=color, weight=weight)
fig.savefig("docs/images/langsmith-trace.png", dpi=150, facecolor="#0d1117",
            bbox_inches="tight")
print("wrote docs/images/langsmith-trace.png  (", len(rows), "spans )")
