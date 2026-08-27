"""Confirm traces actually reached LangSmith, and print what was captured.

Run AFTER a query has executed (in a separate process, so traces flush):
    python scripts/trace_check.py
"""
import os
import time
from dotenv import load_dotenv
from langsmith import Client

load_dotenv()
client = Client()
project = os.environ["LANGSMITH_PROJECT"]

# Traces upload in the background, so poll briefly for the newest root runs.
roots = []
for _ in range(15):
    roots = list(client.list_runs(project_name=project, is_root=True, limit=5))
    if roots:
        break
    time.sleep(2)

print(f"=== {len(roots)} recent root traces in project '{project}' ===")
for r in roots:
    dur = (r.end_time - r.start_time).total_seconds() if r.end_time else None
    print(f"- {r.name:14s} status={r.status:8s} {dur}s")

print("\n=== recent LLM spans (prompt/response/tokens/latency captured here) ===")
for r in client.list_runs(project_name=project, run_type="llm", limit=5):
    dur = (r.end_time - r.start_time).total_seconds() if r.end_time else None
    print(f"- {r.name:16s} status={r.status:8s} tokens={r.total_tokens} latency={dur}s")

print("\n=== recent tool spans (inputs/outputs captured here) ===")
for r in client.list_runs(project_name=project, run_type="tool", limit=6):
    print(f"- {r.name:14s} status={r.status}")
