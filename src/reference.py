"""Curated, human-supplied domain knowledge. NOT derivable from the data.

This is the honest answer to "how is this general?": franchise identity across a
rename cannot be inferred from the tables (nothing links 'Delhi Daredevils' to
'Delhi Capitals'). It is curated once by a human and frozen — map/curate, never
auto-guess. Only CLEAR renames/spellings of the SAME franchise are grouped.
Franchises that merely share a city but are genuinely different (Deccan Chargers
vs Sunrisers Hyderabad; Gujarat Lions vs Titans; Pune Warriors vs Rising Pune)
are deliberately left separate — that is a judgment call, confirmed with a human.
"""

FRANCHISE_GROUPS = {
    "Delhi Capitals": ["Delhi Capitals", "Delhi Daredevils"],
    "Punjab Kings": ["Punjab Kings", "Kings XI Punjab"],
    "Royal Challengers Bengaluru": ["Royal Challengers Bengaluru", "Royal Challengers Bangalore"],
    "Rising Pune Supergiant": ["Rising Pune Supergiant", "Rising Pune Supergiants"],
}

SEASON_NOTE = (
    "Season labels: split-year seasons look like '2020/21' (means the 2020 season) "
    "or '2007/08' (means 2008); the rest are single years like '2016'. If a season "
    "filter returns no rows, run SELECT DISTINCT season to find the right label."
)


def reference_text() -> str:
    """The curated knowledge, rendered for the system prompt."""
    lines = ["Franchise name history — when the user names a franchise, match ALL of its names:"]
    for canon, names in FRANCHISE_GROUPS.items():
        lines.append(f"  - {canon}: {names}")
    lines.append(SEASON_NOTE)
    return "\n".join(lines)
