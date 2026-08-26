"""Transform Cricsheet IPL match JSONs into a clean SQLite DB.

Two tables:
  matches     - one row per game (teams, venue, result, POTM)
  deliveries  - one row per ball (batter, bowler, runs, wicket)

Run once:  python scripts/build_cricket_db.py
"""
import json
import glob
import sqlite3
import pathlib
import zipfile
import urllib.request

RAW = pathlib.Path("data/raw/ipl_json")
OUT = pathlib.Path("data/cricket.sqlite")
URL = "https://cricsheet.org/downloads/ipl_json.zip"

# Self-contained: download + unzip the raw match files if they aren't here yet,
# so `python scripts/build_cricket_db.py` reproduces the DB from nothing.
if not any(RAW.glob("*.json")):
    RAW.mkdir(parents=True, exist_ok=True)
    zip_path = RAW.parent / "ipl_json.zip"
    if not zip_path.exists():
        print(f"downloading {URL} ...")
        urllib.request.urlretrieve(URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(RAW)

con = sqlite3.connect(OUT)
con.executescript(
    """
    DROP TABLE IF EXISTS matches;
    DROP TABLE IF EXISTS deliveries;
    CREATE TABLE matches (
        match_id INTEGER PRIMARY KEY,
        date TEXT, season TEXT, city TEXT, venue TEXT,
        team1 TEXT, team2 TEXT,
        toss_winner TEXT, toss_decision TEXT,
        winner TEXT, win_by_runs INTEGER, win_by_wickets INTEGER,
        result TEXT, player_of_match TEXT,
        gender TEXT, match_type TEXT
    );
    CREATE TABLE deliveries (
        match_id INTEGER, innings INTEGER, batting_team TEXT,
        over INTEGER, ball TEXT,
        batter TEXT, bowler TEXT, non_striker TEXT,
        runs_batter INTEGER, runs_extras INTEGER, runs_total INTEGER,
        wicket_kind TEXT, player_out TEXT, fielders TEXT
    );
    """
)

files = sorted(glob.glob(str(RAW / "*.json")))
m_rows, d_rows = [], []

for path in files:
    d = json.load(open(path))
    info = d["info"]
    mid = int(pathlib.Path(path).stem)
    teams = info.get("teams", [None, None])
    outcome = info.get("outcome", {})
    by = outcome.get("by", {})
    pom = info.get("player_of_match")

    m_rows.append((
        mid,
        (info.get("dates") or [None])[0],
        str(info.get("season", "")),
        info.get("city"),
        info.get("venue"),
        teams[0] if len(teams) > 0 else None,
        teams[1] if len(teams) > 1 else None,
        info.get("toss", {}).get("winner"),
        info.get("toss", {}).get("decision"),
        outcome.get("winner"),
        by.get("runs"),
        by.get("wickets"),
        outcome.get("result"),          # e.g. 'tie', 'no result' when no winner
        pom[0] if pom else None,
        info.get("gender"),
        info.get("match_type"),
    ))

    for i, inn in enumerate(d.get("innings", []), start=1):
        team = inn.get("team")
        for over in inn.get("overs", []):
            onum = over.get("over")
            for ball in over.get("deliveries", []):
                runs = ball.get("runs", {})
                wk = (ball.get("wickets") or [{}])[0] if ball.get("wickets") else {}
                fielders = wk.get("fielders")
                fld = ", ".join(f.get("name", "") for f in fielders) if fielders else None
                d_rows.append((
                    mid, i, team, onum, ball.get("actual_delivery"),
                    ball.get("batter"), ball.get("bowler"), ball.get("non_striker"),
                    runs.get("batter", 0), runs.get("extras", 0), runs.get("total", 0),
                    wk.get("kind"), wk.get("player_out"), fld,
                ))

con.executemany(f"INSERT INTO matches VALUES ({','.join('?'*16)})", m_rows)
con.executemany(f"INSERT INTO deliveries VALUES ({','.join('?'*14)})", d_rows)
con.executescript(
    """
    CREATE INDEX idx_deliv_batter ON deliveries(batter);
    CREATE INDEX idx_deliv_bowler ON deliveries(bowler);
    CREATE INDEX idx_deliv_match  ON deliveries(match_id);
    """
)
con.commit()
print(f"matches:    {len(m_rows)}")
print(f"deliveries: {len(d_rows)}")
print(f"seasons:    {sorted({r[2] for r in m_rows})}")
print(f"FROZEN -> {OUT}")
con.close()
