"""
Bus Factor Tracker — FastAPI backend (Phase 5 + repo management)

Serves data that was already collected and computed by sync_mysql.py.
Most endpoints here only read from MySQL, which is why they respond in
milliseconds rather than the 10-15 seconds the sync script takes per repo.
See the note in the project README about why these two pieces are
deliberately separate.

The exception is POST /api/repos (adding a new repo to track), which calls
GitHub directly and DOES take 10-15 seconds — same cost as one repo in the
sync script, because it reuses that exact same sync_repo() function rather
than duplicating the logic.

Run:
    uvicorn main:app --reload --port 8000

Then visit http://localhost:8000/docs for interactive API docs (FastAPI
generates this automatically from the code below — nothing extra needed).
"""

import os
import sys
from pathlib import Path
from typing import Optional

import requests as gh_requests
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from mysql.connector import MySQLConnection

from db import get_connection

# Load .env from the backend folder first, then fall back to the project
# root's .env — this way GITHUB_TOKEN only has to exist in one place if
# you're already using it for the sync script.
load_dotenv(Path(__file__).parent / ".env")
load_dotenv(Path(__file__).parent.parent / ".env")

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPOS_FILE = Path(__file__).parent.parent / "repos.txt"

# Reuse the exact same sync_repo() function the sync script uses, instead of
# duplicating GitHub-fetching/upsert logic here. This is the same reasoning
# as everything else in this project: one source of truth for how a repo
# gets synced, whether that's triggered by the batch script or by a user
# clicking "add" in the UI.
sys.path.append(str(Path(__file__).parent.parent / "scripts"))
from sync_mysql import sync_repo, assess_risk  # noqa: E402

app = FastAPI(
    title="Bus Factor Tracker API",
    description="Tracks bus factor / maintainer burnout risk across open-source repositories.",
    version="1.0.0",
)

# Allow the React dev server (Phase 6) to call this API from the browser.
# Vite's default port is 5173, Create React App's is 3000 — both included
# so it works regardless of which you end up using.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)




# ---------------------------------------------------------------------------
# Response models — these double as API documentation (visible in /docs)
# and give the frontend a predictable, typed shape to build against.
# ---------------------------------------------------------------------------

class RepoSummary(BaseModel):
    repo_id: int
    owner: str
    name: str
    primary_language: Optional[str]
    stars: int
    is_archived: bool
    bus_factor: Optional[int]
    top_contributor_pct: Optional[float]
    active_contributor_count: Optional[int]
    median_issue_response_hours: Optional[float]
    activity_change_pct: Optional[float]
    top_contributor_days_inactive: Optional[int]
    days_since_last_release: Optional[int]
    risk_level: Optional[str]
    computed_at: Optional[str]


class GitHubSearchResult(BaseModel):
    owner: str
    name: str
    full_name: str
    description: Optional[str]
    stars: int
    language: Optional[str]


class AddRepoRequest(BaseModel):
    owner: str
    name: str


class ContributorBreakdown(BaseModel):
    github_username: str
    total_commits: int
    additions: int
    deletions: int
    commit_share_pct: float


class RepoDetail(RepoSummary):
    forks: int
    created_at: Optional[str]
    risk_drivers: list[str]
    contributors: list[ContributorBreakdown]


class DecliningRepo(BaseModel):
    owner: str
    name: str
    then_at: str
    now_at: str
    bus_factor_then: int
    bus_factor_now: int
    risk_then: str
    risk_now: str


class RiskAlert(BaseModel):
    alert_id: int
    owner: str
    name: str
    previous_level: str
    new_level: str
    created_at: str


class SnapshotPoint(BaseModel):
    computed_at: str
    bus_factor: int
    top_contributor_pct: Optional[float]
    risk_level: str


class DashboardSummary(BaseModel):
    total_repos_tracked: int
    critical_count: int
    high_count: int
    medium_count: int
    healthy_count: int


# ---------------------------------------------------------------------------
# Every "repo + its latest snapshot" read goes through the v_repo_latest_snapshot
# view (sql/objects_mysql.sql), so the latest-row-per-group logic lives in the
# database once instead of being repeated in each endpoint.
# ---------------------------------------------------------------------------

SUMMARY_COLUMNS = """
    repo_id, owner, name, primary_language, stars, is_archived,
    bus_factor, top_contributor_pct, active_contributor_count,
    median_issue_response_hours, activity_change_pct,
    top_contributor_days_inactive, days_since_last_release,
    risk_level, computed_at
"""

FLOAT_FIELDS = ("top_contributor_pct", "median_issue_response_hours", "activity_change_pct")
DATE_FIELDS = ("computed_at", "created_at", "then_at", "now_at")


def to_json_types(row):
    """Convert datetime / Decimal values from MySQL into plain JSON types."""
    for key in DATE_FIELDS:
        if row.get(key) is not None:
            row[key] = row[key].isoformat()
    for key in FLOAT_FIELDS:
        if row.get(key) is not None:
            row[key] = float(row[key])
    if "is_archived" in row:
        row["is_archived"] = bool(row["is_archived"])
    return row


@app.get("/api/repos", response_model=list[RepoSummary])
def list_repos(
    risk: Optional[str] = Query(None, description="Filter by risk level: Critical, High, Medium, Healthy"),
    sort: str = Query("risk", description="Sort by: risk (worst first), stars, name"),
    conn: MySQLConnection = Depends(get_connection),
):
    """
    Risk-ranked list of all tracked repos with their latest snapshot.
    This is the main dashboard endpoint — powers the repo list / table view.
    """
    cur = conn.cursor(dictionary=True)

    where_clause = ""
    params = []
    if risk:
        where_clause = "WHERE risk_level = %s"
        params.append(risk)

    # fn_risk_rank() is the stored function from sql/objects_mysql.sql
    # (Healthy = 1 ... Critical = 4); repos with no snapshot yet sort last.
    order_clause = {
        "risk": "fn_risk_rank(risk_level) DESC, bus_factor ASC",
        "stars": "stars DESC",
        "name": "owner ASC, name ASC",
    }.get(sort, "fn_risk_rank(risk_level) DESC, bus_factor ASC")

    cur.execute(
        f"""
        SELECT {SUMMARY_COLUMNS}
        FROM v_repo_latest_snapshot
        {where_clause}
        ORDER BY {order_clause}
        """,
        params,
    )
    rows = cur.fetchall()
    cur.close()

    return [to_json_types(row) for row in rows]


@app.get("/api/repos/{owner}/{name}", response_model=RepoDetail)
def get_repo_detail(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Full detail view for a single repo: metadata, latest snapshot, and its
    contributor breakdown (for the "who actually did the work" view).
    """
    cur = conn.cursor(dictionary=True)

    cur.execute(
        f"""
        SELECT {SUMMARY_COLUMNS}, forks, created_at
        FROM v_repo_latest_snapshot
        WHERE owner = %s AND name = %s
        """,
        (owner, name),
    )
    repo = cur.fetchone()
    if repo is None:
        cur.close()
        raise HTTPException(status_code=404, detail=f"Repo {owner}/{name} not found — has it been synced yet?")

    cur.execute(
        """
        SELECT
            c.github_username,
            rc.total_commits,
            rc.additions,
            rc.deletions,
            -- Window function: the repo's total is computed once for the
            -- whole result, not re-summed per row by a correlated subquery.
            ROUND(100 * rc.total_commits / NULLIF(SUM(rc.total_commits) OVER (), 0), 1) AS commit_share_pct
        FROM repo_contributor rc
        JOIN contributor c ON c.contributor_id = rc.contributor_id
        WHERE rc.repo_id = %s
        ORDER BY rc.total_commits DESC
        """,
        (repo["repo_id"],),
    )
    contributors = cur.fetchall()
    cur.close()

    for c in contributors:
        c["commit_share_pct"] = float(c["commit_share_pct"]) if c["commit_share_pct"] is not None else 0.0

    to_json_types(repo)

    # Same function (and thresholds) the sync used to pick risk_level, so
    # the explanation always matches the stored score.
    repo["risk_drivers"] = []
    if repo["bus_factor"] is not None:
        _, repo["risk_drivers"] = assess_risk(
            bus_factor=repo["bus_factor"],
            top_contributor_pct=repo["top_contributor_pct"],
            median_issue_response_hours=repo["median_issue_response_hours"],
            activity_change_pct=repo["activity_change_pct"],
            top_contributor_days_inactive=repo["top_contributor_days_inactive"],
            days_since_last_release=repo["days_since_last_release"],
            is_archived=repo["is_archived"],
        )

    repo["contributors"] = contributors
    return repo


@app.get("/api/repos/{owner}/{name}/trend", response_model=list[SnapshotPoint])
def get_repo_trend(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Full snapshot history for one repo — powers the "bus factor over time"
    trend chart. Only meaningful once sync_mysql.py has been run more than
    once for this repo (each run adds one snapshot row).
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT s.computed_at, s.bus_factor, s.top_contributor_pct, s.risk_level
        FROM bus_factor_snapshot s
        JOIN repository r ON r.repo_id = s.repo_id
        WHERE r.owner = %s AND r.name = %s
        ORDER BY s.computed_at ASC
        """,
        (owner, name),
    )
    rows = cur.fetchall()
    cur.close()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No snapshot history for {owner}/{name} yet")

    for row in rows:
        row["computed_at"] = row["computed_at"].isoformat()
        if row["top_contributor_pct"] is not None:
            row["top_contributor_pct"] = float(row["top_contributor_pct"])

    return rows


@app.get("/api/stats/summary", response_model=DashboardSummary)
def get_dashboard_summary(conn: MySQLConnection = Depends(get_connection)):
    """
    Aggregate counts for a dashboard header — e.g. "12 Critical, 8 High,
    20 Medium, 40 Healthy out of 80 repos tracked".
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT
            COUNT(*) AS total_repos_tracked,
            SUM(CASE WHEN risk_level = 'Critical' THEN 1 ELSE 0 END) AS critical_count,
            SUM(CASE WHEN risk_level = 'High' THEN 1 ELSE 0 END) AS high_count,
            SUM(CASE WHEN risk_level = 'Medium' THEN 1 ELSE 0 END) AS medium_count,
            SUM(CASE WHEN risk_level = 'Healthy' THEN 1 ELSE 0 END) AS healthy_count
        FROM v_repo_latest_snapshot
        """
    )
    row = cur.fetchone()
    cur.close()

    # SUM() over zero matching rows returns NULL, not 0 — normalize that.
    for key in ("critical_count", "high_count", "medium_count", "healthy_count"):
        row[key] = int(row[key]) if row[key] is not None else 0

    return row


@app.get("/api/stats/declining", response_model=list[DecliningRepo])
def get_declining_repos(
    days: int = Query(180, ge=1, description="Compare the latest snapshot with one at least this many days older"),
    conn: MySQLConnection = Depends(get_connection),
):
    """
    Repos whose bus factor fell or whose risk level worsened over the given
    window. Runs the sp_declining_repos stored procedure.
    """
    cur = conn.cursor(dictionary=True)
    cur.callproc("sp_declining_repos", (days,))
    rows = []
    for result in cur.stored_results():
        rows.extend(result.fetchall())
    cur.close()

    # Depending on the mysql-connector version, stored_results() rows come
    # back as dicts (dictionary cursor) or as tuples in the procedure's
    # column order — accept both.
    keys = ("owner", "name", "then_at", "now_at", "bus_factor_then", "bus_factor_now", "risk_then", "risk_now")
    return [to_json_types(dict(row) if isinstance(row, dict) else dict(zip(keys, row))) for row in rows]


@app.get("/api/alerts", response_model=list[RiskAlert])
def get_alerts(
    limit: int = Query(20, ge=1, le=200),
    conn: MySQLConnection = Depends(get_connection),
):
    """
    Most recent risk-level increases. Rows are written by the
    trg_snapshot_risk_alert trigger whenever a sync produces a snapshot
    that's riskier than the repo's previous one.
    """
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT a.alert_id, r.owner, r.name, a.previous_level, a.new_level, a.created_at
        FROM risk_alert a
        JOIN repository r ON r.repo_id = a.repo_id
        ORDER BY a.created_at DESC, a.alert_id DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    cur.close()
    return [to_json_types(row) for row in rows]


# ---------------------------------------------------------------------------
# repos.txt helpers — keep the tracked-repo file in sync with the database
# whenever a repo is added or removed through the UI, so re-running the
# batch sync script later still operates on the same repo list.
# ---------------------------------------------------------------------------

def _append_to_repos_file(owner: str, name: str):
    entry = f"{owner}/{name}"
    existing_lines = []
    if REPOS_FILE.exists():
        existing_lines = [line.strip() for line in REPOS_FILE.read_text().splitlines()]
    if entry not in existing_lines:
        with open(REPOS_FILE, "a") as f:
            f.write(f"\n{entry}\n")


def _remove_from_repos_file(owner: str, name: str):
    entry = f"{owner}/{name}"
    if not REPOS_FILE.exists():
        return
    lines = REPOS_FILE.read_text().splitlines()
    kept_lines = [line for line in lines if line.strip() != entry]
    REPOS_FILE.write_text("\n".join(kept_lines) + "\n")


# ---------------------------------------------------------------------------
# Repo management: search GitHub, add a new repo to track, remove one.
# ---------------------------------------------------------------------------

@app.get("/api/github/search", response_model=list[GitHubSearchResult])
def search_github_repos(q: str = Query(..., min_length=2)):
    """
    Server-side proxy to GitHub's repository search — powers the
    autocomplete suggestions in the "add repo" UI. Kept server-side so the
    GitHub token never has to be exposed to the browser.
    """
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=500, detail="GITHUB_TOKEN is not configured on the backend")

    resp = gh_requests.get(
        "https://api.github.com/search/repositories",
        params={"q": q, "per_page": 8, "sort": "stars", "order": "desc"},
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
    )
    if resp.status_code == 403:
        raise HTTPException(status_code=429, detail="GitHub API rate limit hit — try again shortly")
    resp.raise_for_status()

    items = resp.json().get("items", [])
    return [
        {
            "owner": item["owner"]["login"],
            "name": item["name"],
            "full_name": item["full_name"],
            "description": item.get("description"),
            "stars": item["stargazers_count"],
            "language": item.get("language"),
        }
        for item in items
    ]


@app.post("/api/repos", response_model=RepoSummary)
def add_repo(payload: AddRepoRequest, conn: MySQLConnection = Depends(get_connection)):
    """
    Add a new repo to track. This calls the SAME sync_repo() function the
    batch sync script uses — same GitHub calls, same transaction, same bus
    factor computation — so takes the same 10-15 seconds a single repo takes
    during a normal sync run. The frontend should show a loading state for
    this, not treat it like the other (instant) endpoints.
    """
    owner, name = payload.owner.strip(), payload.name.strip()
    if not owner or not name:
        raise HTTPException(status_code=400, detail="owner and name are required")

    try:
        sync_repo(conn, owner, name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not sync {owner}/{name}: {e}")

    _append_to_repos_file(owner, name)

    cur = conn.cursor(dictionary=True)
    cur.execute(
        f"SELECT {SUMMARY_COLUMNS} FROM v_repo_latest_snapshot WHERE owner = %s AND name = %s",
        (owner, name),
    )
    row = cur.fetchone()
    cur.close()

    return to_json_types(row)


@app.delete("/api/repos/{owner}/{name}")
def remove_repo(owner: str, name: str, conn: MySQLConnection = Depends(get_connection)):
    """
    Stop tracking a repo. Deleting the repository row cascades (via the
    ON DELETE CASCADE foreign keys in the schema) to remove its contributors,
    issues, PRs, releases, and snapshot history in the same operation —
    no separate cleanup queries needed.
    """
    cur = conn.cursor()
    cur.execute("SELECT repo_id FROM repository WHERE owner = %s AND name = %s", (owner, name))
    row = cur.fetchone()
    if row is None:
        cur.close()
        raise HTTPException(status_code=404, detail=f"{owner}/{name} is not currently tracked")

    cur.execute("DELETE FROM repository WHERE repo_id = %s", (row[0],))
    conn.commit()
    cur.close()

    _remove_from_repos_file(owner, name)
    return {"status": "removed", "owner": owner, "name": name}


@app.get("/")
def root():
    return {"message": "Bus Factor Tracker API — see /docs for available endpoints"}
