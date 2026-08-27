"""Print the real step-by-step tree of the latest 'answer' trace, in plain terms.

Fetches the trace's runs in one query, then builds the tree in memory (fast).
"""
import os
import json
from collections import defaultdict
from dotenv import load_dotenv
from langsmith import Client

load_dotenv()
client = Client()
project = os.environ["LANGSMITH_PROJECT"]


def snip(x, n=140):
    s = x if isinstance(x, str) else json.dumps(x, default=str)
    return " ".join(s.split())[:n]


roots = [r for r in client.list_runs(project_name=project, is_root=True, limit=10)
         if r.name in ("answer", "answer_trace")]
root = next((r for r in roots if r.status == "success"), roots[0])

pool = list(client.list_runs(project_name=project, limit=300))
trace = [r for r in pool if getattr(r, "trace_id", None) == root.trace_id]
kids = defaultdict(list)
for r in trace:
    kids[r.parent_run_id].append(r)

print(f"TRACE: {root.name}   question: {snip(root.inputs)}")
print(f"({len(trace)} steps captured)\n")


def walk(run, depth=0):
    pad = "   " * depth
    dur = (run.end_time - run.start_time).total_seconds() if run.end_time and run.start_time else None
    tok = f" tokens={run.total_tokens}" if run.run_type == "llm" else ""
    print(f"{pad}• [{run.run_type}] {run.name} ({dur}s{tok}) {run.status}")
    if run.run_type == "tool":
        print(f"{pad}    in : {snip(run.inputs)}")
        print(f"{pad}    out: {snip(run.outputs)}")
    for child in sorted(kids.get(run.id, []), key=lambda r: r.start_time):
        walk(child, depth + 1)


walk(root)
