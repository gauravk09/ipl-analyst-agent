"""Grounded tools the agent will call. Stage 1: just `run_sql`.

Kept as a plain function for now (no framework yet) so the idea is visible.
Stage 2 wraps it as a LangGraph tool.
"""
import sqlite3
import pathlib

from reference import PLAYER_ALIASES  # curated full-name -> data-name for stars

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "cricket.sqlite"

# Any query whose first keyword is not one of these is refused outright.
_ALLOWED_START = ("select", "with")


def run_sql(query: str, max_rows: int = 50) -> dict:
    """Run a READ-ONLY SQL query against the IPL cricket DB and return real rows.

    Read-only is enforced two ways, belt and suspenders:
      1. The connection is opened in `mode=ro`, so the SQLite driver itself
         rejects any write — it is mechanically impossible, not a request.
      2. A cheap first-keyword check refuses non-SELECT statements with a
         clean message instead of a cryptic driver error, and blocks the
         `;`-chaining trick used to smuggle a second statement.

    Returns a structured, grounded result: the columns, the rows, how many
    there were, and whether we truncated. The model never sees a number that
    did not come out of this function.
    """
    q = query.strip().rstrip(";").strip()
    first = q.lower().split(None, 1)[0] if q else ""
    if first not in _ALLOWED_START:
        return {"error": f"refused: only SELECT/WITH queries allowed, got '{first}'"}
    if ";" in q:
        return {"error": "refused: multiple statements are not allowed"}

    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.execute(q)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]
        return {
            "columns": columns,
            "rows": [dict(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    except sqlite3.Error as e:
        # A failed query is information the agent uses to fix itself, not a crash.
        return {"error": f"sql error: {e}"}
    finally:
        con.close()


def get_schema() -> dict:
    """Return every table and its columns by introspecting the live DB.

    Generic: reads `sqlite_master` for table names, then `PRAGMA table_info`
    for each table's columns. Zero hardcoding — point this at any SQLite file
    and it describes itself. The table names come from the DB, not from user
    input, so interpolating them into PRAGMA is safe.
    """
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {
            t: [{"name": c[1], "type": c[2]} for c in con.execute(f"PRAGMA table_info({t})")]
            for t in tables
        }
    finally:
        con.close()


def plot(chart_type: str, title: str, series: list,
         xlabel: str = "", ylabel: str = "", ylabel2: str = "") -> dict:
    """Draw a chart from data the agent ALREADY got via run_sql and save a PNG.
    Option A: the agent passes data only — no arbitrary code — so charts stay
    grounded and safe.

    series: list of {"name": str, "points": [[label, value], ...]} plus OPTIONAL
    per-series "type" ('bar' or 'line', defaults to chart_type) and "axis"
    ('primary' or 'secondary'). Use a secondary axis + mixed types when two
    quantities have different scales — e.g. strike-rate as bars on the primary
    axis and runs as a line on the secondary axis. Series align on the union of
    labels (missing -> 0 for bars, gap for lines).
    """
    import matplotlib
    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    import hashlib

    charts_dir = DB_PATH.parent.parent / "charts"
    charts_dir.mkdir(exist_ok=True)
    key = hashlib.md5(f"{chart_type}{title}{series}".encode()).hexdigest()[:10]
    path = charts_dir / f"chart_{key}.png"

    maps = [{str(lbl): val for lbl, val in s.get("points", [])} for s in series]
    labels = sorted({lbl for m in maps for lbl in m},
                    key=lambda s: (0, int(s)) if s.isdigit() else (1, s))
    idx = list(range(len(labels)))

    fig, ax = plt.subplots(figsize=(10, 5))
    need2 = any(s.get("axis") == "secondary" for s in series)
    ax2 = ax.twinx() if need2 else None

    def axis_for(s):
        return ax2 if (s.get("axis") == "secondary" and ax2) else ax

    def type_for(s):
        return s.get("type") or chart_type

    nb = sum(1 for s in series if type_for(s) == "bar")
    width = 0.8 / max(nb, 1)
    bi = 0
    for s, m in zip(series, maps):
        a, name = axis_for(s), s.get("name")
        if type_for(s) == "bar":
            a.bar([j + bi * width for j in idx], [m.get(l, 0) for l in labels],
                  width=width, label=name)
            bi += 1
        else:
            a.plot(idx, [m.get(l) for l in labels], marker="o", label=name)

    ax.set_xticks([j + width * (nb - 1) / 2 for j in idx] if nb else idx)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if ax2 and ylabel2:
        ax2.set_ylabel(ylabel2)

    handles, lbls = ax.get_legend_handles_labels()
    if ax2:
        h2, l2 = ax2.get_legend_handles_labels()
        handles, lbls = handles + h2, lbls + l2
    if len(series) > 1:
        ax.legend(handles, lbls, loc="upper left", fontsize=8)

    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return {"path": str(path), "series": [s.get("name") for s in series], "title": title}


def find_player(name: str, limit: int = 12) -> dict:
    """Resolve a player name to the exact name(s) in the data.

    The data uses an 'initial surname' format ('V Kohli', 'I Sharma'), so a user's
    full first name won't substring-match. We match on the SURNAME (last token),
    then, if a first name was given, narrow by its initial ('Ishant Sharma' ->
    'I Sharma'). Returns candidates so the agent uses one match, asks on several,
    or refuses on none. Parameterised — the name is data, never concatenated.
    """
    alias = PLAYER_ALIASES.get(name.strip().lower())
    if alias:  # a curated star name — resolve directly, no ambiguity
        return {"candidates": [alias]}

    tokens = [t for t in name.replace(".", " ").split() if t]
    if not tokens:
        return {"candidates": []}
    surname = tokens[-1]
    initial = tokens[0][0].upper() if len(tokens) > 1 else None

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = con.execute(
            """SELECT DISTINCT name FROM (
                   SELECT batter AS name FROM deliveries
                   UNION SELECT bowler FROM deliveries
               ) WHERE name LIKE ? ORDER BY name""",
            (f"%{surname}",),
        ).fetchall()
        names = [r[0] for r in rows]
        if initial:  # narrow by first initial, but fall back if that empties it
            narrowed = [n for n in names if n.split() and n.split()[0][:1].upper() == initial]
            names = narrowed or names
        return {"candidates": names[:limit]}
    finally:
        con.close()


if __name__ == "__main__":
    # Proof: real cricket queries. Every number below is computed by SQLite.
    print("--- Top 5 IPL run scorers (all seasons) ---")
    top_bat = run_sql("""
        SELECT batter, SUM(runs_batter) AS runs
        FROM deliveries
        GROUP BY batter
        ORDER BY runs DESC
        LIMIT 5
    """)
    for row in top_bat["rows"]:
        print(f"  {row['batter']:20s} {row['runs']}")

    print("\n--- Top 5 wicket takers (bowler-credited kinds only) ---")
    top_bowl = run_sql("""
        SELECT bowler, COUNT(*) AS wickets
        FROM deliveries
        WHERE wicket_kind IN ('bowled','caught','lbw','stumped',
                              'caught and bowled','hit wicket')
        GROUP BY bowler
        ORDER BY wickets DESC
        LIMIT 5
    """)
    for row in top_bowl["rows"]:
        print(f"  {row['bowler']:20s} {row['wickets']}")

    print("\n--- read-only guard proof ---")
    print(run_sql("DELETE FROM Artist"))
    print(run_sql("SELECT 1; DROP TABLE Artist"))
