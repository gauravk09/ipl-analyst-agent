"""Unit test the verifier's grounding gate directly, with synthetic trajectories.

We can't easily make the model fabricate, so we hand-build message lists and
assert verify() bounces ungrounded numbers while passing grounded ones, echoed
question numbers (years), refusals, and clarifications.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from agent import verify
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage


def tool_msg(content):
    return ToolMessage(content=content, name="run_sql", tool_call_id="x")


def bounced(result):
    return "messages" in result  # verify only returns messages when it rejects


CASES = [
    # (label, messages, expect_bounce)
    ("grounded number accepted",
     [HumanMessage(content="most runs in 2016?"),
      tool_msg('{"rows":[{"runs":973}]}'),
      AIMessage(content="V Kohli scored 973 runs.")], False),

    ("fabricated number bounced",
     [HumanMessage(content="how many sixes in 2020?"),
      tool_msg('{"rows":[{"c":736}]}'),
      AIMessage(content="There were 999 sixes.")], True),

    ("echoed year not flagged (true zero)",
     [HumanMessage(content="wickets for V Kohli in IPL 2026?"),
      tool_msg('{"rows":[{"w":0}]}'),
      AIMessage(content="V Kohli took 0 wickets in IPL 2026.")], False),

    ("refusal passes through",
     [HumanMessage(content="Kohli's salary?"),
      AIMessage(content="Sorry, the database does not contain salary data.")], False),

    ("clarifying question passes through",
     [HumanMessage(content="highest strike rate?"),
      AIMessage(content="Over a minimum of how many balls faced?")], False),
]

if __name__ == "__main__":
    passed = 0
    for label, msgs, expect_bounce in CASES:
        result = verify({"messages": msgs, "verify_attempts": 0})
        ok = bounced(result) == expect_bounce
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {label} (expected bounce={expect_bounce})")
    print(f"\nSCORE: {passed}/{len(CASES)}")
    sys.exit(0 if passed == len(CASES) else 1)
