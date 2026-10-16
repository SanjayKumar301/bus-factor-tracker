"""
One-off maintenance: recompute stored issue first-response times with the
bot-aware rule in sync_mysql.fetch_first_response_at (first comment from a
person other than the issue's author, bots excluded), then re-score every
repo so today's snapshot uses the corrected times.

Earlier versions of the sync took the very first comment, which on several
projects is an automatic bot reply posted seconds after the issue opens.

The issue table stores GitHub's issue id, but the comments API needs the
issue number, so each repo's most recently updated issues are listed once to
map ids to numbers (same capped fetch the sync uses). Issues outside that
window can't be re-checked; their stored time came from the old, bot-blind
rule, so it is cleared (NULL = unknown) rather than kept.

Run:
    python scripts/refresh_first_responses.py
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import mysql.connector

import sync_mysql as s


def refresh_repo(conn, repo_id, owner, name):
    cur = conn.cursor()
    cur.execute(
        "SELECT issue_id FROM issue WHERE repo_id = %s AND first_response_at IS NOT NULL",
        (repo_id,),
    )
    stored = {row[0] for row in cur.fetchall()}
    if not stored:
        cur.close()
        return 0, 0, 0

    listed = {i["id"]: i for i in s.fetch_issues(owner, name) if i["id"] in stored}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {
            issue_id: pool.submit(s.fetch_first_response_at, owner, name, issue["number"],
                                  (issue.get("user") or {}).get("login"))
            for issue_id, issue in listed.items()
        }
        new_times = {issue_id: f.result() for issue_id, f in futures.items()}

    # Not re-checkable -> unknown.
    for issue_id in stored - set(listed):
        new_times[issue_id] = None

    changed = 0
    for issue_id, first_response_at in new_times.items():
        cur.execute(
            """
            UPDATE issue SET first_response_at = %s
            WHERE issue_id = %s AND NOT (first_response_at <=> %s)
            """,
            (s.to_mysql_dt(first_response_at), issue_id, s.to_mysql_dt(first_response_at)),
        )
        changed += cur.rowcount
    cur.close()
    return len(stored), len(listed), changed


def main():
    conn = mysql.connector.connect(**s.DB_CONFIG)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SELECT repo_id, owner, name FROM repository ORDER BY repo_id")
    repos = cur.fetchall()
    cur.close()

    totals = [0, 0, 0]
    for repo_id, owner, name in repos:
        try:
            stored, checked, changed = refresh_repo(conn, repo_id, owner, name)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  FAILED on {owner}/{name}: {e}")
            continue
        totals = [a + b for a, b in zip(totals, (stored, checked, changed))]
        if stored:
            print(f"{owner}/{name}: {checked}/{stored} re-checked, {changed} changed")

    print(f"\nIssues with a response: {totals[0]}, re-checked: {totals[1]}, changed: {totals[2]}")

    # Re-score: a new snapshot for today from the corrected data (no GitHub calls).
    print("\nRe-scoring all repos...")
    for repo_id, owner, name in repos:
        cur = conn.cursor()
        try:
            print(f"{owner}/{name}")
            s.compute_and_insert_snapshot(cur, repo_id)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"  FAILED on {owner}/{name}: {e}")
        finally:
            cur.close()
    conn.close()
    print(f"Done at {datetime.now():%H:%M:%S}")


if __name__ == "__main__":
    main()
