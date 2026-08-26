"""The scoreboard. Asserts the ACTUAL answer value, not status or shape.

A test that passes a wrong answer is worse than no test, so the numeric cases
check that the exact expected number appears in the agent's reply. Gold values
were verified against the source DB and against real-world knowledge (e.g. Kohli's
973 in 2016 is a well-known record).

Run:  python tests/eval_agent.py     (exit code 1 if any case fails)
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from agent import answer

REFUSE_MARKERS = (
    "cannot", "can't", "can not", "does not contain", "doesn't contain",
    "no information", "not in the", "unable", "don't have", "do not have",
    "not available", "isn't in", "is not in",
)

# Each case pins a real, verified fact — or a required NON-answer (refuse/clarify).
CASES = [
    dict(q="How many sixes were hit in IPL 2020?",                       number=736),
    dict(q="Who scored the most runs in IPL 2016?",                      number=973, substr="Kohli"),
    dict(q="How many matches have Delhi Capitals won in total?",         number=125),   # incl. Daredevils
    dict(q="Which team has won the most IPL matches overall?",           number=155, substr="Mumbai"),
    dict(q="How many wickets did V Kohli take in IPL 2026?",             number=0),      # legitimate zero
    dict(q="What is Virat Kohli's annual salary?",                       outcome="refuse"),
    dict(q="Which batter has the highest strike rate in IPL history?",   outcome="clarify"),
]


def numbers_in(text: str) -> set:
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def check(case: dict, ans: str) -> tuple:
    # Normalise curly apostrophes/quotes to straight — the model emits ' and "
    # which broke substring matches on a genuinely-correct refusal (see BUGS B3).
    low = ans.lower().replace("’", "'").replace("‘", "'")
    if case.get("outcome") == "refuse":
        return any(m in low for m in REFUSE_MARKERS), "must refuse (data absent)"
    if case.get("outcome") == "clarify":
        return "?" in ans, "must ask a clarifying question"
    ok = case["number"] in numbers_in(ans)
    if "substr" in case:
        ok = ok and case["substr"].lower() in low
    return ok, f"must state {case['number']}" + (f" + '{case['substr']}'" if "substr" in case else "")


if __name__ == "__main__":
    passed = 0
    for i, case in enumerate(CASES):
        ans = answer(case["q"], thread_id=f"eval-{i}")
        ok, why = check(case, ans)
        passed += ok
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case['q']}")
        print(f"       expect: {why}")
        print(f"       got:    {ans.strip()[:110]}")
    total = len(CASES)
    print(f"\nSCORE: {passed}/{total}")
    sys.exit(0 if passed == total else 1)
