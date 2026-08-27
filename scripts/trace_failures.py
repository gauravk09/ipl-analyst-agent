"""Force failures so you can see how errors surface in LangSmith.

Run:  python scripts/trace_failures.py   (then look for red/error runs in the UI)
"""
import os
import sys

sys.path.insert(0, "src")
from dotenv import load_dotenv
load_dotenv()
from langsmith import traceable
from langchain_openai import ChatOpenAI


@traceable(run_type="chain", name="llm_timeout_demo")
def llm_timeout_demo():
    # A 1ms timeout guarantees the LLM call fails -> a red LLM span with the error.
    bad = ChatOpenAI(model="gpt-oss:120b", base_url="https://ollama.com/v1",
                     api_key=os.environ["OLLAMA_API_KEY"], timeout=0.001, max_retries=0)
    return bad.invoke("Say hi").content


@traceable(run_type="tool", name="tool_error_demo")
def tool_error_demo():
    # A raised exception inside a tool -> the span is recorded as errored with the
    # stack trace, exactly how a real tool crash (DB down, bad API) would appear.
    raise RuntimeError("simulated DB outage: connection refused")


for label, fn in [("LLM timeout", llm_timeout_demo), ("Tool error", tool_error_demo)]:
    try:
        fn()
        print(f"{label}: unexpectedly succeeded")
    except Exception as e:  # traced as an error run BEFORE re-raising
        print(f"{label} failed as intended -> {type(e).__name__}: {str(e)[:90]}")
