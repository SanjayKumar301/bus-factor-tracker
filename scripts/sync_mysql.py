"""
Bus Factor Tracker — sync script (Phase 3), MySQL version

For each repo in repos.txt:
  1. Look up the repo's last_synced_at from a previous run (if any)
  2. Fetch repo metadata from GitHub
  3. Fetch per-contributor commit stats (pre-aggregated endpoint — cheap on rate limit)
  4. Fetch weekly commit activity (for WEEKLY_ACTIVITY / trend detection)
  5. Fetch issues updated since the last sync (incremental via GitHub's `since` param)
  6. Fetch pull requests updated since the last sync (incremental via early-exit pagination)
  7. Fetch releases updated since the last sync (incremental via early-exit pagination, same trick as PRs)
  8. Upsert everything into MySQL inside a single transaction per repo
  9. Compute a bus factor + risk snapshot (now including median issue response time) and insert it

Incremental sync: repeated runs only fetch issues/PRs that changed since the
last run, instead of re-pulling everything from scratch every time. Storage
was always safe to re-run (upserts don't create duplicates), but earlier
versions of this script wastefully re-fetched full history on every run.

Run:
    python scripts/sync_mysql.py
"""

import os
import time
from pathlib import Path
import requests
import mysql.connector
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Resolve paths from this file's location rather than the current directory,
# so the script also works when launched by Task Scheduler / cron from
# somewhere else.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPOS_FILE = PROJECT_ROOT / "repos.txt"
load_dotenv(PROJECT_ROOT / ".env")

# Deliberately NOT os.environ["GITHUB_TOKEN"] here — this module gets
# imported by the FastAPI backend (to reuse sync_repo() for the "add repo"
# feature), and a KeyError at import time would crash the entire backend
# just because GITHUB_TOKEN wasn't set, even for routes that don't need it.
# The check happens in main() below instead, for when this runs as a script.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
}
API_ROOT = "https://api.github.com"

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    port=int(os.environ.get("DB_PORT", "3306")),
    database=os.environ.get("DB_NAME", "bus_factor_tracker"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", ""),
)


def to_mysql_dt(iso_str):
    """
    Convert a GitHub timestamp like '2026-08-13T22:29:31Z' into the format
    MySQL's DATETIME columns expect: '2026-08-13 22:29:31'.
    MySQL doesn't understand the ISO 8601 'T' separator or trailing 'Z' —
    every datetime value going into the DB has to be passed through this.
    Returns None unchanged (for optional fields like merged_at).
    """
    if not iso_str:
        return None
    dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def http_get_with_retry(url, attempts=3):
    """
    requests.get(), retried on dropped connections. A long sync run makes
    thousands of requests, and one reset connection shouldn't fail a repo.
    HTTP error statuses are NOT retried here — they're handled by callers.
    """
    for attempt in range(1, attempts + 1):
        try:
            return requests.get(url, headers=HEADERS, timeout=30)
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as e:
            if attempt == attempts:
                raise
            print(f"    network error ({type(e).__name__}), retrying in {2 * attempt}s... ({url})")
            time.sleep(2 * attempt)


def get_json(url, retries=5, initial_wait=2, max_wait=10):
    """
    GET a GitHub API URL. Handles the 202 'stats being computed, try again'
    case with capped exponential backoff (2s, 4s, 8s, 10s, 10s) — the
    stats/contributors and stats/commit_activity endpoints compute their
    result asynchronously on a cache miss. Capped at max_wait so one slow
    repo can't stall the whole sync run for 90+ seconds; total worst case
    here is ~34s before giving up.
    """
    wait = initial_wait
    for attempt in range(retries):
        resp = http_get_with_retry(url)
        if resp.status_code == 202:
            print(f"    stats not ready yet, retrying in {wait}s... ({url})")
            time.sleep(wait)
            wait = min(wait * 2, max_wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Gave up waiting for {url} after {retries} attempts")


def fetch_repo_metadata(owner, repo):
    return get_json(f"{API_ROOT}/repos/{owner}/{repo}")


def fetch_contributor_stats(owner, repo):
    """Pre-aggregated weekly stats per contributor. One call, not one per commit."""
    data = get_json(f"{API_ROOT}/repos/{owner}/{repo}/stats/contributors")
    return data or []


def fetch_commit_activity(owner, repo, contributor_stats=None):
    """
    Total commits per week for the last year. One call.

    GitHub sometimes keeps answering 202 ("still computing") for this
    endpoint indefinitely, even when stats/contributors for the same repo is
    ready. Rather than failing the whole repo, fall back to summing the
    per-week commit counts in the contributor stats we already fetched
    (slightly undercounts commits from authors without a GitHub account).
    """
    try:
        data = get_json(f"{API_ROOT}/repos/{owner}/{repo}/stats/commit_activity")
        return data or []
    except RuntimeError:
        if not contributor_stats:
            raise
        print("    commit_activity not ready — deriving weekly totals from contributor stats")
        totals = {}
        for entry in contributor_stats:
            for w in entry.get("weeks", []):
                totals[w["w"]] = totals.get(w["w"], 0) + w.get("c", 0)
        return [{"week": week, "total": totals[week]} for week in sorted(totals)[-52:]]


def get_paginated(url, max_pages=3, per_page=100, stop_before=None, updated_field="updated_at"):
    """
    Pagination helper, capped at max_pages so a single huge repo can't blow
    the rate limit or make one sync run take forever.

    If stop_before is given (an ISO 8601 timestamp string), pagination stops
    as soon as it hits an item whose `updated_field` is older than that
    cutoff. This works because GitHub returns issues/PRs sorted by most-
    recently-updated first (sort=updated&direction=desc) — so once we see
    one old item, everything after it on every subsequent page is guaranteed
    to be even older, and there's no point fetching further pages.
    """
    results = []
    for page in range(1, max_pages + 1):
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}per_page={per_page}&page={page}"
        try:
            data = get_json(page_url)
        except requests.exceptions.HTTPError as e:
            if page == 1 and e.response is not None and e.response.status_code == 404:
                # A 404 on the FIRST page of /pulls, /issues, or /releases
                # usually doesn't mean the repo is broken — it means that
                # feature is disabled on this repo (e.g. FFmpeg/FFmpeg
                # disables GitHub pull requests entirely; all contributions
                # go through a mailing list instead). Treat it as "zero
                # items", not a sync failure.
                return []
            raise
        if not data:
            break

        if stop_before:
            hit_cutoff = False
            for item in data:
                item_time = item.get(updated_field)
                if item_time is None:
                    # e.g. a draft release with no published_at yet — we can't
                    # tell its age, so include it rather than risk using an
                    # unknown value to wrongly trigger early-exit.
                    results.append(item)
                    continue
                if item_time < stop_before:
                    hit_cutoff = True
                    break
                results.append(item)
            if hit_cutoff:
                break
        else:
            results.extend(data)

        if len(data) < per_page:
            break  # last page
    return results


def fetch_issues(owner, repo, since=None):
    """
    Issues (state=all), most-recently-updated first.
    If `since` is given, GitHub filters server-side and only returns issues
    updated after that timestamp — the cheapest possible incremental fetch,
    since GitHub does the filtering, not us.
    Note: GitHub's /issues endpoint also returns pull requests mixed in
    (a PR is technically an issue in GitHub's data model) — we filter
    those out by checking for the absence of a 'pull_request' key.
    """
    url = f"{API_ROOT}/repos/{owner}/{repo}/issues?state=all&sort=updated&direction=desc"
    if since:
        url += f"&since={since}"
    raw = get_paginated(url)
    return [item for item in raw if "pull_request" not in item]


def fetch_pull_requests(owner, repo, since=None):
    """
    Pull requests, most-recently-updated first. GitHub's /pulls endpoint has
    no `since` param (unlike /issues), so incremental fetching is done via
    early-exit pagination instead — see get_paginated()'s stop_before logic.
    """
    url = f"{API_ROOT}/repos/{owner}/{repo}/pulls?state=all&sort=updated&direction=desc"
    return get_paginated(url, stop_before=since)


def fetch_releases(owner, repo, since=None):
    """
    Releases, newest-first (GitHub's default order for this endpoint).
    Like /pulls, the /releases endpoint has no `since` param, so this uses
    the same early-exit pagination trick as fetch_pull_requests(): stop as
    soon as we hit a release published before our cutoff.
    """
    url = f"{API_ROOT}/repos/{owner}/{repo}/releases"
    return get_paginated(url, max_pages=2, stop_before=since, updated_field="published_at")


def fetch_first_response_at(owner, repo, issue_number):
    """
    GitHub doesn't give first-response time directly — it has to be derived
    from the first comment on an issue. One extra API call per issue, so
    this is deliberately only used for a capped, recent subset of issues
    (see MAX_ISSUES_FOR_RESPONSE_TIME below) to keep rate-limit usage sane.
    """
    url = f"{API_ROOT}/repos/{owner}/{repo}/issues/{issue_number}/comments?per_page=1"
    comments = get_json(url)
    if comments:
        return comments[0]["created_at"]
    return None


def get_previous_sync_time(cur, owner, repo):
    """
    Looks up last_synced_at from a prior run, if this repo has been synced
    before. Returns None for a first-time sync (meaning: fetch everything).
    Must be called BEFORE upsert_repo(), which overwrites last_synced_at
    with the current time.
    """
    cur.execute("SELECT last_synced_at FROM repository WHERE owner = %s AND name = %s", (owner, repo))
    row = cur.fetchone()
    if row and row[0]:
        return row[0]
    return None


def upsert_repo(cur, owner, repo, meta):
    cur.execute(
        """
        INSERT INTO repository (owner, name, primary_language, stars, forks, created_at, is_archived, last_synced_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            primary_language = VALUES(primary_language),
            stars = VALUES(stars),
            forks = VALUES(forks),
            is_archived = VALUES(is_archived),
            last_synced_at = NOW()
        """,
        (
            owner,
            repo,
            meta.get("language"),
            meta.get("stargazers_count", 0),
            meta.get("forks_count", 0),
            meta.get("created_at", "")[:10] if meta.get("created_at") else None,
            meta.get("archived", False),
        ),
    )
    # MySQL's ON DUPLICATE KEY UPDATE doesn't return the id via RETURNING like Postgres,
    # so fetch it explicitly.
    cur.execute("SELECT repo_id FROM repository WHERE owner = %s AND name = %s", (owner, repo))
    return cur.fetchone()[0]


def upsert_contributor(cur, username):
    cur.execute(
        """
        INSERT INTO contributor (github_username)
        VALUES (%s)
        ON DUPLICATE KEY UPDATE github_username = VALUES(github_username)
        """,
        (username,),
    )
    cur.execute("SELECT contributor_id FROM contributor WHERE github_username = %s", (username,))
    return cur.fetchone()[0]


def upsert_repo_contributor(cur, repo_id, contributor_id, total_commits, additions, deletions,
                            first_commit_at, last_commit_at):
    cur.execute(
        """
        INSERT INTO repo_contributor
            (repo_id, contributor_id, total_commits, additions, deletions, first_commit_at, last_commit_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            total_commits = VALUES(total_commits),
            additions = VALUES(additions),
            deletions = VALUES(deletions),
            first_commit_at = VALUES(first_commit_at),
            last_commit_at = VALUES(last_commit_at)
        """,
        (repo_id, contributor_id, total_commits, additions, deletions, first_commit_at, last_commit_at),
    )


def commit_week_range(weeks):
    """
    First and last week (as 'YYYY-MM-DD' week-start dates) in which a
    contributor made at least one commit, from the stats/contributors
    per-week breakdown. Week precision is enough for burnout signals,
    which look at gaps of months, not days.
    """
    active = [w["w"] for w in weeks if w.get("c", 0) > 0]
    if not active:
        return None, None
    return (
        time.strftime("%Y-%m-%d", time.gmtime(min(active))),
        time.strftime("%Y-%m-%d", time.gmtime(max(active))),
    )


def upsert_weekly_activity(cur, repo_id, commit_activity):
    for week in commit_activity:
        week_start = time.strftime("%Y-%m-%d", time.gmtime(week["week"]))
        cur.execute(
            """
            INSERT INTO weekly_activity (repo_id, week_start, commit_count)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE commit_count = VALUES(commit_count)
            """,
            (repo_id, week_start, week.get("total", 0)),
        )


def upsert_issue(cur, repo_id, opened_by_id, issue, first_response_at):
    cur.execute(
        """
        INSERT INTO issue (issue_id, repo_id, opened_by, state, created_at, first_response_at, closed_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            state = VALUES(state),
            first_response_at = VALUES(first_response_at),
            closed_at = VALUES(closed_at)
        """,
        (
            issue["id"],
            repo_id,
            opened_by_id,
            issue["state"],
            to_mysql_dt(issue["created_at"]),
            to_mysql_dt(first_response_at),
            to_mysql_dt(issue.get("closed_at")),
        ),
    )


def upsert_pull_request(cur, repo_id, opened_by_id, pr):
    cur.execute(
        """
        INSERT INTO pull_request (pr_id, repo_id, opened_by, state, created_at, merged_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            state = VALUES(state),
            merged_at = VALUES(merged_at)
        """,
        (pr["id"], repo_id, opened_by_id, pr["state"], to_mysql_dt(pr["created_at"]), to_mysql_dt(pr.get("merged_at"))),
    )


def upsert_release(cur, repo_id, published_by_id, release):
    cur.execute(
        """
        INSERT INTO repo_release (release_id, repo_id, published_by, tag_name, published_at)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            tag_name = VALUES(tag_name),
            published_at = VALUES(published_at)
        """,
        (release["id"], repo_id, published_by_id, release.get("tag_name"), to_mysql_dt(release.get("published_at"))),
    )


# Risk thresholds. Shared by the scoring below and by the backend's
# "why is this repo at risk" explanation, so the two can never disagree.
SLOW_RESPONSE_HOURS = 24 * 30        # median first response slower than a month
ACTIVITY_DROP_PCT = -50.0            # commits/week fell by half or more
MAINTAINER_INACTIVE_DAYS = 180       # top contributor silent for ~6 months...
KEY_MAINTAINER_PCT = 25.0            # ...but only counts if they wrote at least this share of commits
STALE_RELEASE_DAYS = 365             # informational only — many healthy repos don't tag releases

RISK_LEVELS = ["Healthy", "Medium", "High", "Critical"]


def assess_risk(bus_factor, top_contributor_pct, median_issue_response_hours, activity_change_pct,
                top_contributor_days_inactive, days_since_last_release, is_archived):
    """
    Returns (risk_level, drivers) where drivers is a list of plain-English
    reasons. Bus factor sets the base level; each independent burnout
    warning sign bumps it up one level (capped at Critical). An archived
    repo is Critical outright — its maintainers have said so.
    """
    drivers = []

    if bus_factor == 1:
        level = 3
    elif bus_factor == 2:
        level = 2
    elif bus_factor <= 4:
        level = 1
    else:
        level = 0
    share = f" (top contributor: {top_contributor_pct:g}% of commits)" if top_contributor_pct is not None else ""
    if bus_factor <= 2:
        people = "1 person wrote" if bus_factor == 1 else f"{bus_factor} people wrote"
        drivers.append(f"Bus factor {bus_factor}: {people} at least half of all commits{share}")
    else:
        drivers.append(f"Bus factor {bus_factor}: work is spread across several people{share}")

    if is_archived:
        level = 3
        drivers.insert(0, "Repository is archived by its owner — no longer maintained")

    if median_issue_response_hours is not None and median_issue_response_hours > SLOW_RESPONSE_HOURS:
        level += 1
        drivers.append(f"Slow issue responses: median {median_issue_response_hours / 24:.0f} days to first reply")

    if activity_change_pct is not None and activity_change_pct <= ACTIVITY_DROP_PCT:
        level += 1
        drivers.append(f"Commit activity down {abs(activity_change_pct):.0f}% in the last 12 weeks vs the 40 before")

    # In a large project the all-time top contributor may have written only
    # ~10% of the code, and their leaving is routine turnover, not a risk.
    # It only signals burnout when the project actually leans on that person.
    if (top_contributor_days_inactive is not None
            and top_contributor_days_inactive > MAINTAINER_INACTIVE_DAYS
            and top_contributor_pct is not None
            and top_contributor_pct >= KEY_MAINTAINER_PCT):
        level += 1
        drivers.append(f"Top contributor ({top_contributor_pct:g}% of commits) has not committed in "
                       f"{top_contributor_days_inactive} days")

    if days_since_last_release is not None and days_since_last_release > STALE_RELEASE_DAYS:
        drivers.append(f"No release in {days_since_last_release} days")

    return RISK_LEVELS[min(level, 3)], drivers


def compute_and_insert_snapshot(cur, repo_id):
    """
    Phase 4: bus factor, top-contributor %, active contributor count, and
    median issue response time are now all computed with SQL window
    functions (MySQL 8.0+), not Python loops. This is the version worth
    showing off in your report — it demonstrates CTEs, SUM() OVER(),
    ROW_NUMBER() OVER(), and a window-function-based median, all of which
    map directly to Section 6 of the project guide.
    """
    # --- Bus factor + top contributor % + active contributor count ---
    # Single CTE query: rank contributors by commits, build a running total,
    # and find the smallest rank at which the running total crosses 50% of
    # all commits to this repo. No PARTITION BY needed here (unlike the
    # multi-repo version in queries_mysql.sql) because we already scope to
    # one repo_id via WHERE — every row belongs to the same repo.
    cur.execute(
        """
        WITH ranked_contributors AS (
            SELECT
                contributor_id,
                total_commits,
                SUM(total_commits) OVER () AS repo_total_commits,
                SUM(total_commits) OVER (ORDER BY total_commits DESC) AS running_total,
                ROW_NUMBER() OVER (ORDER BY total_commits DESC) AS contributor_rank,
                COUNT(*) OVER () AS active_contributor_count
            FROM repo_contributor
            WHERE repo_id = %s
        )
        SELECT
            MIN(CASE WHEN running_total >= 0.5 * repo_total_commits THEN contributor_rank END) AS bus_factor,
            MAX(CASE WHEN contributor_rank = 1 THEN ROUND(100 * total_commits / repo_total_commits, 1) END) AS top_contributor_pct,
            MAX(active_contributor_count) AS active_contributor_count
        FROM ranked_contributors
        """,
        (repo_id,),
    )
    row = cur.fetchone()
    if row is None or row[0] is None:
        return  # no contributor data yet for this repo
    bus_factor = int(row[0])
    top_contributor_pct = float(row[1]) if row[1] is not None else None
    active_contributor_count = int(row[2])

    # --- Median issue first-response time ---
    # MySQL's PERCENTILE_CONT() only exists from 8.0.28 onward, so this uses
    # the portable ROW_NUMBER()-based median instead (works on any MySQL 8.0+):
    # rank response times, then average the middle one or two (for even counts).
    cur.execute(
        """
        WITH ranked AS (
            SELECT
                TIMESTAMPDIFF(HOUR, created_at, first_response_at) AS response_hours,
                ROW_NUMBER() OVER (ORDER BY TIMESTAMPDIFF(HOUR, created_at, first_response_at)) AS rn,
                COUNT(*) OVER () AS cnt
            FROM issue
            WHERE repo_id = %s AND first_response_at IS NOT NULL
        )
        SELECT AVG(response_hours) AS median_response_hours
        FROM ranked
        WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))
        """,
        (repo_id,),
    )
    median_row = cur.fetchone()
    median_issue_response_hours = float(median_row[0]) if median_row and median_row[0] is not None else None

    # --- Burnout signals ---
    # Commit activity trend: average commits/week over the last 12 weeks vs
    # the 40 weeks before that, measured from the repo's newest week of data.
    # A sharp drop means the people doing the work are slowing down — the
    # earliest visible sign of a maintainer burning out or drifting away.
    cur.execute(
        """
        SELECT
            AVG(CASE WHEN w.week_start >  m.latest_week - INTERVAL 12 WEEK
                     THEN w.commit_count END) AS recent_avg,
            AVG(CASE WHEN w.week_start <= m.latest_week - INTERVAL 12 WEEK
                      AND w.week_start >  m.latest_week - INTERVAL 52 WEEK
                     THEN w.commit_count END) AS baseline_avg
        FROM weekly_activity w
        JOIN (SELECT MAX(week_start) AS latest_week FROM weekly_activity WHERE repo_id = %s) m
        WHERE w.repo_id = %s
        """,
        (repo_id, repo_id),
    )
    recent_avg, baseline_avg = cur.fetchone()
    activity_change_pct = None
    if recent_avg is not None and baseline_avg:  # baseline of 0 / NULL -> no meaningful %
        activity_change_pct = round(100 * (float(recent_avg) - float(baseline_avg)) / float(baseline_avg), 1)

    # How long since the single biggest contributor last committed? If the
    # person the project depends on most has gone quiet, the bus factor
    # number is about to become a real outage.
    cur.execute(
        """
        SELECT DATEDIFF(CURDATE(), last_commit_at)
        FROM repo_contributor
        WHERE repo_id = %s
        ORDER BY total_commits DESC
        LIMIT 1
        """,
        (repo_id,),
    )
    inactive_row = cur.fetchone()
    top_contributor_days_inactive = int(inactive_row[0]) if inactive_row and inactive_row[0] is not None else None

    cur.execute(
        "SELECT DATEDIFF(CURDATE(), MAX(published_at)) FROM repo_release WHERE repo_id = %s",
        (repo_id,),
    )
    release_row = cur.fetchone()
    days_since_last_release = int(release_row[0]) if release_row and release_row[0] is not None else None

    cur.execute("SELECT is_archived FROM repository WHERE repo_id = %s", (repo_id,))
    is_archived = bool(cur.fetchone()[0])

    risk_level, _ = assess_risk(
        bus_factor=bus_factor,
        top_contributor_pct=top_contributor_pct,
        median_issue_response_hours=median_issue_response_hours,
        activity_change_pct=activity_change_pct,
        top_contributor_days_inactive=top_contributor_days_inactive,
        days_since_last_release=days_since_last_release,
        is_archived=is_archived,
    )

    cur.execute(
        """
        INSERT INTO bus_factor_snapshot
            (repo_id, bus_factor, top_contributor_pct, active_contributor_count,
             median_issue_response_hours, activity_change_pct,
             top_contributor_days_inactive, days_since_last_release, risk_level)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (repo_id, bus_factor, top_contributor_pct, active_contributor_count,
         median_issue_response_hours, activity_change_pct,
         top_contributor_days_inactive, days_since_last_release, risk_level),
    )
    median_str = f"{median_issue_response_hours:.0f}h" if median_issue_response_hours is not None else "n/a"
    print(f"    -> bus_factor={bus_factor}  risk={risk_level}  top_contributor={top_contributor_pct}%  median_response={median_str}"
          f"  activity_change={activity_change_pct}%  top_inactive_days={top_contributor_days_inactive}")


# How many of the most-recently-updated issues to fetch first-response-comment
# data for. Each one costs an extra API call, so this is capped deliberately —
# 30 recent issues is enough to get a meaningful median without risking the
# rate limit on repos with thousands of issues.
MAX_ISSUES_FOR_RESPONSE_TIME = 30


def sync_repo(conn, owner, repo):
    start = time.time()
    print(f"Syncing {owner}/{repo}...")

    # Look up when this repo was last synced, BEFORE we touch the repository
    # row (upsert_repo overwrites last_synced_at with the current time).
    # Uses its own short-lived cursor/transaction, separate from the main
    # sync transaction below.
    lookup_cur = conn.cursor()
    previous_sync = get_previous_sync_time(lookup_cur, owner, repo)
    lookup_cur.close()

    since_iso = None
    if previous_sync:
        since_iso = previous_sync.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"  incremental sync since {since_iso}")
    else:
        print(f"  first-time sync — fetching full history (capped)")

    meta = fetch_repo_metadata(owner, repo)
    contributor_stats = fetch_contributor_stats(owner, repo)  # always a full aggregate — GitHub has no incremental version
    commit_activity = fetch_commit_activity(owner, repo, contributor_stats)  # same — always a full aggregate
    issues = fetch_issues(owner, repo, since=since_iso)        # incremental via GitHub's `since` param
    pull_requests = fetch_pull_requests(owner, repo, since=since_iso)  # incremental via early-exit pagination
    releases = fetch_releases(owner, repo, since=since_iso)          # incremental via early-exit pagination, same as PRs

    # First-response-comment lookups are independent of each other, so fetch
    # them concurrently instead of one at a time — this is the single biggest
    # time cost per repo (up to MAX_ISSUES_FOR_RESPONSE_TIME extra API calls),
    # and running them in parallel cuts that wall-clock cost dramatically.
    # Done here, before the DB transaction opens, so network latency never
    # holds a MySQL transaction open.
    issues_needing_response_time = [
        issue for issue in issues[:MAX_ISSUES_FOR_RESPONSE_TIME]
        if issue.get("comments", 0) > 0
    ]
    first_response_map = {}
    if issues_needing_response_time:
        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = {
                pool.submit(fetch_first_response_at, owner, repo, issue["number"]): issue["number"]
                for issue in issues_needing_response_time
            }
            for future in futures:
                issue_number = futures[future]
                first_response_map[issue_number] = future.result()

    cur = conn.cursor()
    try:
        repo_id = upsert_repo(cur, owner, repo, meta)

        # --- contributors + their commit stats ---
        for entry in contributor_stats:
            author = entry.get("author")
            if not author:
                continue  # GitHub sometimes returns null author for deleted accounts
            username = author["login"]
            total_commits = entry.get("total", 0)
            additions = sum(w.get("a", 0) for w in entry.get("weeks", []))
            deletions = sum(w.get("d", 0) for w in entry.get("weeks", []))

            first_commit_at, last_commit_at = commit_week_range(entry.get("weeks", []))

            contributor_id = upsert_contributor(cur, username)
            upsert_repo_contributor(cur, repo_id, contributor_id, total_commits, additions, deletions,
                                    first_commit_at, last_commit_at)

        # --- weekly commit activity (for trend/backlog-style queries later) ---
        upsert_weekly_activity(cur, repo_id, commit_activity)

        # --- issues (first-response time already fetched concurrently above) ---
        for issue in issues:
            opened_by_id = None
            if issue.get("user"):
                opened_by_id = upsert_contributor(cur, issue["user"]["login"])

            first_response_at = first_response_map.get(issue["number"])
            upsert_issue(cur, repo_id, opened_by_id, issue, first_response_at)

        # --- pull requests ---
        for pr in pull_requests:
            opened_by_id = None
            if pr.get("user"):
                opened_by_id = upsert_contributor(cur, pr["user"]["login"])
            upsert_pull_request(cur, repo_id, opened_by_id, pr)

        # --- releases ---
        for release in releases:
            published_by_id = None
            if release.get("author"):
                published_by_id = upsert_contributor(cur, release["author"]["login"])
            upsert_release(cur, repo_id, published_by_id, release)

        compute_and_insert_snapshot(cur, repo_id)
        conn.commit()  # transaction commits only if everything above succeeded
    except Exception:
        conn.rollback()  # any failure rolls back the whole repo's changes
        raise
    finally:
        cur.close()

    elapsed = time.time() - start
    print(f"  done in {elapsed:.1f}s. ({len(issues)} issues, {len(pull_requests)} PRs, {len(releases)} releases)")


def main():
    if not GITHUB_TOKEN:
        raise RuntimeError(
            "GITHUB_TOKEN is not set. Copy .env.example to .env and fill in your GitHub personal access token."
        )

    run_start = time.time()
    with open(REPOS_FILE) as f:
        repo_list = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]

    conn = mysql.connector.connect(**DB_CONFIG)
    conn.autocommit = False  # we control commit/rollback manually, per repo
    try:
        for entry in repo_list:
            owner, repo = entry.split("/")
            try:
                sync_repo(conn, owner, repo)
            except Exception as e:
                print(f"  FAILED on {entry}: {e}")
            time.sleep(1)  # be polite to the API between repos
    finally:
        conn.close()

    total_elapsed = time.time() - run_start
    print(f"\nTotal sync run: {total_elapsed:.1f}s across {len(repo_list)} repos")


if __name__ == "__main__":
    main()
