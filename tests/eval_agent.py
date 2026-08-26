"""The scoreboard. Asserts the ACTUAL answer value AND how it was reached.

Case types:
  value   - a numeric fact. Asserted twice: the number appears in the final text
            (correctness) AND in an actual run_sql result (grounding — a memorised
            number can't pass). This is the trajectory check.
  refuse  - the data can't answer; the agent must decline.
  clarify - the question is underspecified; the agent must ask.
  answer  - a "must stay quiet" case: a normal/qualified question that must NOT be
            over-refused or over-clarified; it must produce a grounded number.

Gold values verified against the source DB and real-world knowledge.
Run:  python tests/eval_agent.py     (exit code 1 if any case fails)
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from agent import answer_trace

REFUSE_MARKERS = (
    "cannot", "can't", "can not", "does not contain", "doesn't contain",
    "no information", "not in the", "unable", "don't have", "do not have",
    "not available", "isn't in", "is not in", "sorry",
)

CASES = [
    dict(type="value",   q="How many sixes were hit in IPL 2020?",                     number=736),
    dict(type="value",   q="Who scored the most runs in IPL 2016?",                    number=973, substr="Kohli"),
    dict(type="value",   q="How many matches have Delhi Capitals won in total?",       number=125),
    dict(type="value",   q="Which team has won the most IPL matches overall?",         number=155, substr="Mumbai"),
    dict(type="value",   q="How many wickets did V Kohli take in IPL 2026?",           number=0),
    # must-stay-quiet: a plain answerable question must NOT be refused.
    dict(type="value",   q="How many matches did Chennai Super Kings win in 2018?",    number=11),
    # coverage: player-vs-player with an 'initial surname' opponent (Ishant -> I Sharma).
    dict(type="value",   q="How many runs did Virat Kohli score off Ishant Sharma, and off how many balls?",
         numbers=[112, 79]),
    dict(type="refuse",  q="What is Virat Kohli's annual salary?"),
    dict(type="clarify", q="Which batter has the highest strike rate in IPL history?"),
    # must-stay-quiet: a QUALIFIED rate question must ANSWER, not over-clarify.
    dict(type="answer",  q="Which batter has the highest strike rate in IPL, minimum 1000 balls faced?"),
]


def numbers_in(text: str) -> set:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text or "")}


def run_sql_numbers(messages) -> set:
    """Numbers that actually came out of run_sql tool results (the grounding set)."""
    nums = set()
    for m in messages:
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "run_sql":
            nums |= numbers_in(m.content)
    return nums


def ran_sql(messages) -> bool:
    return any(getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "run_sql"
               for m in messages)


def sql_errored(messages) -> bool:
    """A run_sql that returned an error = the agent wrote a bad query (e.g. a
    guessed column). A correct-but-messy path is a hidden fragility; flag it."""
    return any(getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "run_sql"
               and '"error"' in (m.content or "") for m in messages)


def check(case, ans, messages):
    low = (ans or "").lower().replace("’", "'").replace("‘", "'")
    t = case["type"]

    if t == "refuse":
        return any(m in low for m in REFUSE_MARKERS), "must refuse (data absent)"

    if t == "clarify":
        return "?" in ans, "must ask a clarifying question"

    if t == "answer":  # must-stay-quiet: must ANSWER, not over-clarify or refuse.
        # A name is a valid answer, so don't demand a number — demand that it
        # queried, didn't error, isn't a clarifying question, and didn't refuse.
        refused = any(m in low for m in REFUSE_MARKERS)
        over_clarified = ans.strip().endswith("?")
        answered = ran_sql(messages) and not sql_errored(messages)
        return (answered and not over_clarified and not refused), \
            "must answer (grounded), not over-clarify or refuse"

    # value: every expected number stated in the text AND grounded in a run_sql
    # result, and no run_sql errored along the way (clean trajectory).
    wanted = case.get("numbers") or [case["number"]]
    stated = all(w in numbers_in(ans) for w in wanted)
    grounded = all(w in run_sql_numbers(messages) for w in wanted)
    ok = stated and grounded and not sql_errored(messages)
    if "substr" in case:
        ok = ok and case["substr"].lower() in low
    detail = f"must state+ground {wanted}"
    if sql_errored(messages):
        detail += " [a run_sql ERRORED — messy path]"
    elif not stated:
        detail += " [NOT stated]"
    elif not grounded:
        detail += " [NOT grounded]"
    return ok, detail


if __name__ == "__main__":
    passed = 0
    for i, case in enumerate(CASES):
        ans, messages = answer_trace(case["q"], thread_id=f"eval-{i}")
        ok, why = check(case, ans, messages)
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] ({case['type']}) {case['q']}")
        print(f"       expect: {why}")
        print(f"       got:    {(ans or '').strip()[:105]}")
    total = len(CASES)
    print(f"\nSCORE: {passed}/{total}")
    sys.exit(0 if passed == total else 1)
