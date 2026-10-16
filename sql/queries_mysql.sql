-- Bus Factor Tracker — Core analytical queries (MySQL 8.0+ version)
-- These are the MySQL equivalents of the queries in the project guide's
-- Section 6. MySQL 8.0+ supports the same window function syntax as
-- Postgres, so both queries below are nearly identical to the originals —
-- the differences are called out in comments.

-- ============================================================
-- Query 1: Bus factor calculation using window functions
-- ============================================================
WITH ranked_contributors AS (
  SELECT
    repo_id,
    contributor_id,
    total_commits,
    SUM(total_commits) OVER (PARTITION BY repo_id) AS repo_total_commits,
    SUM(total_commits) OVER (
      PARTITION BY repo_id ORDER BY total_commits DESC
    ) AS running_total,
    ROW_NUMBER() OVER (
      PARTITION BY repo_id ORDER BY total_commits DESC
    ) AS contributor_rank
  FROM repo_contributor
)
SELECT repo_id, MIN(contributor_rank) AS bus_factor
FROM ranked_contributors
WHERE running_total >= 0.5 * repo_total_commits
GROUP BY repo_id;

-- Identical to the Postgres version — MySQL 8.0+ supports CTEs (WITH ...)
-- and window functions (SUM() OVER, ROW_NUMBER() OVER) with the same syntax.


-- ============================================================
-- Query 2: Repos trending toward risk (bus factor declined over time)
-- ============================================================
-- Compares each repo's LATEST snapshot against the most recent snapshot
-- taken at least 6 months before it.
--
-- Why not `s2.computed_at = s1.computed_at - INTERVAL 6 MONTH`? Snapshots
-- are taken whenever the sync runs, so two of them are essentially never
-- exactly 6 months apart to the second — an equality join returns nothing.
-- Instead, pick the newest snapshot that is *at least* 6 months older.
WITH latest AS (
  SELECT repo_id, MAX(computed_at) AS latest_at
  FROM bus_factor_snapshot
  GROUP BY repo_id
),
paired AS (
  SELECT
    l.repo_id,
    l.latest_at,
    (SELECT MAX(s.computed_at)
       FROM bus_factor_snapshot s
      WHERE s.repo_id = l.repo_id
        AND s.computed_at <= l.latest_at - INTERVAL 6 MONTH) AS baseline_at
  FROM latest l
)
SELECT
  r.owner,
  r.name,
  now_s.bus_factor  AS bus_factor_now,
  then_s.bus_factor AS bus_factor_6mo_ago,
  then_s.risk_level AS risk_then,
  now_s.risk_level  AS risk_now
FROM paired p
JOIN bus_factor_snapshot now_s  ON now_s.repo_id  = p.repo_id AND now_s.computed_at  = p.latest_at
JOIN bus_factor_snapshot then_s ON then_s.repo_id = p.repo_id AND then_s.computed_at = p.baseline_at
JOIN repository r ON r.repo_id = p.repo_id
WHERE now_s.bus_factor < then_s.bus_factor
ORDER BY (then_s.bus_factor - now_s.bus_factor) DESC;

-- Difference from Postgres: MySQL's interval syntax is
--   `computed_at - INTERVAL 6 MONTH`
-- instead of Postgres's
--   `computed_at - INTERVAL '6 months'`
-- (no quotes, unit comes after the number, singular unit name).
--
-- The same logic, with the look-back window as a parameter, is available as
-- the stored procedure sp_declining_repos(days) in sql/objects_mysql.sql.


-- ============================================================
-- Bonus: Median issue response time (percentile)
-- ============================================================
-- Postgres has PERCENTILE_CONT() built in for this. MySQL did not add
-- PERCENTILE_CONT until MySQL 8.0.28 (Jan 2022) — if your MySQL version
-- is older than that, you'll need a workaround. If you're on 8.0.28+:

SELECT
  repo_id,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_hours) AS median_response_hours
FROM (
  SELECT
    repo_id,
    TIMESTAMPDIFF(HOUR, created_at, first_response_at) AS response_hours
  FROM issue
  WHERE first_response_at IS NOT NULL
) AS response_times
GROUP BY repo_id;

-- If your MySQL version is older, here's a manual median workaround using
-- ROW_NUMBER() + COUNT() (works on any MySQL 8.0+ without PERCENTILE_CONT):

WITH ranked AS (
  SELECT
    repo_id,
    TIMESTAMPDIFF(HOUR, created_at, first_response_at) AS response_hours,
    ROW_NUMBER() OVER (PARTITION BY repo_id ORDER BY TIMESTAMPDIFF(HOUR, created_at, first_response_at)) AS rn,
    COUNT(*) OVER (PARTITION BY repo_id) AS cnt
  FROM issue
  WHERE first_response_at IS NOT NULL
)
SELECT repo_id, AVG(response_hours) AS median_response_hours
FROM ranked
WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))
GROUP BY repo_id;
