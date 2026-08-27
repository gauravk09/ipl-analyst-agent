"""Deterministic unit test of the plot tool (no model involved).

The eval's chart case checks whether the AGENT chooses to chart (behavioural, can
wobble). This checks the TOOL itself always produces a valid file — single series,
multi-series, bar and line.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from tools import plot

CASES = [
    ("single bar", plot("bar", "one series",
                        [{"name": "Matches", "points": [["2008", 58], ["2009", 57]]}])),
    ("multi bar (comparison)", plot("bar", "two players",
                        [{"name": "Dhoni", "points": [["2008", 414], ["2009", 332]]},
                         {"name": "Pant",  "points": [["2016", 198], ["2017", 366]]}])),
    ("line", plot("line", "trend",
                  [{"name": "Runs", "points": [["2008", 10], ["2009", 20], ["2010", 15]]}])),
]

if __name__ == "__main__":
    passed = 0
    for label, result in CASES:
        path = result.get("path")
        ok = bool(path) and os.path.exists(path) and os.path.getsize(path) > 0
        passed += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {label} -> {path}")
    print(f"\nSCORE: {passed}/{len(CASES)}")
    sys.exit(0 if passed == len(CASES) else 1)
