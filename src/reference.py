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

# Season labels in the data are irregular: some are single years, some span two.
# The calendar year each maps to is NOT derivable by a rule (2007/08 -> 2008 and
# 2009/10 -> 2010 use the END year, but 2020/21 -> 2020 uses the START year because
# of COVID scheduling). So it is curated explicitly, once.
SEASON_YEAR = {
    "2007/08": 2008, "2009": 2009, "2009/10": 2010, "2011": 2011, "2012": 2012,
    "2013": 2013, "2014": 2014, "2015": 2015, "2016": 2016, "2017": 2017,
    "2018": 2018, "2019": 2019, "2020/21": 2020, "2021": 2021, "2022": 2022,
    "2023": 2023, "2024": 2024, "2025": 2025, "2026": 2026,
}

SEASON_NOTE = (
    "Season labels in the data are like '2016', '2007/08' or '2020/21'. If a season "
    "filter returns no rows, run SELECT DISTINCT season to find the right label. "
    "When REPORTING a season to the user, give its calendar year, not the slash "
    "label: 2007/08 -> 2008, 2009/10 -> 2010, 2020/21 -> 2020; all others are the "
    "year itself. e.g. say 'the 2008 season', never 'the 2007/08 season'."
)


def reference_text() -> str:
    """The curated knowledge, rendered for the system prompt."""
    lines = ["Franchise name history — when the user names a franchise, match ALL of its names:"]
    for canon, names in FRANCHISE_GROUPS.items():
        lines.append(f"  - {canon}: {names}")
    lines.append(SEASON_NOTE)
    return "\n".join(lines)
