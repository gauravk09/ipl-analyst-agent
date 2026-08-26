"""Grounded tools the agent will call. Stage 1: just `run_sql`.

Kept as a plain function for now (no framework yet) so the idea is visible.
Stage 2 wraps it as a LangGraph tool.
"""
import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "chinook.sqlite"

# Any query whose first keyword is not one of these is refused outright.
_ALLOWED_START = ("select", "with")


def run_sql(query: str, max_rows: int = 50) -> dict:
    """Run a READ-ONLY SQL query against Chinook and return real rows.

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


if __name__ == "__main__":
    # Proof: a real analytical query — top 5 artists by revenue — joining
    # InvoiceLine -> Track -> Album -> Artist. Every number below is from the DB.
    demo = """
        SELECT ar.Name AS artist,
               ROUND(SUM(il.UnitPrice * il.Quantity), 2) AS revenue
        FROM InvoiceLine il
        JOIN Track t  ON t.TrackId  = il.TrackId
        JOIN Album al ON al.AlbumId = t.AlbumId
        JOIN Artist ar ON ar.ArtistId = al.ArtistId
        GROUP BY ar.ArtistId
        ORDER BY revenue DESC
        LIMIT 5
    """
    result = run_sql(demo)
    print("columns:", result["columns"])
    for row in result["rows"]:
        print(f"  {row['artist']:25s} ${row['revenue']}")
    print("row_count:", result["row_count"], "truncated:", result["truncated"])

    print("\n--- read-only guard proof ---")
    print(run_sql("DELETE FROM Artist"))
    print(run_sql("SELECT 1; DROP TABLE Artist"))
