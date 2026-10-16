-- Bus Factor Tracker — views, stored routines and triggers (MySQL 8.0+)
-- Safe to re-run: every object is dropped and recreated.
--   mysql -u root -p bus_factor_tracker < sql/objects_mysql.sql
--
-- Uses DELIMITER, so run it through the mysql command-line client (or
-- MySQL Workbench), not a driver that sends the file as one statement.
--
-- Snapshots carry a scoring_version (1 = original all-time method,
-- 2 = bots excluded + recency-based bus factor). Everything below only ever
-- compares snapshots of the same version, so a change of method is never
-- mistaken for a change in the project.

-- ============================================================
-- Function: fn_risk_rank(level) — 1 = Healthy ... 4 = Critical
-- ============================================================
-- risk_level is an ENUM ordered Critical, High, Medium, Healthy, so its
-- internal index runs the "wrong" way for comparisons. This gives one place
-- that defines "worse than", used by the trigger, the procedure and the API.
DROP FUNCTION IF EXISTS fn_risk_rank;
DELIMITER $$
CREATE FUNCTION fn_risk_rank(p_level VARCHAR(10))
RETURNS INT
DETERMINISTIC
NO SQL
BEGIN
    RETURN FIELD(p_level, 'Healthy', 'Medium', 'High', 'Critical');
END$$
DELIMITER ;


-- ============================================================
-- View: v_repo_latest_snapshot — every repo + its newest snapshot
-- ============================================================
-- Newest = highest scoring_version first, then latest computed_at (history
-- backfill inserts past-dated snapshots, so insertion order is not time
-- order). LEFT JOIN so repos with no snapshot yet still appear.
-- effective_* is what the risk level is based on: the last-12-months value
-- when the repo had enough recent commits, otherwise the all-time value.
CREATE OR REPLACE VIEW v_repo_latest_snapshot AS
SELECT
    r.repo_id,
    r.owner,
    r.name,
    r.primary_language,
    r.stars,
    r.forks,
    r.created_at,
    r.is_archived,
    r.last_synced_at,
    s.snapshot_id,
    s.computed_at,
    s.scoring_version,
    s.bus_factor,
    s.recent_bus_factor,
    COALESCE(s.recent_bus_factor, s.bus_factor)                    AS effective_bus_factor,
    s.top_contributor_pct,
    s.recent_top_contributor_pct,
    COALESCE(s.recent_top_contributor_pct, s.top_contributor_pct)  AS effective_top_contributor_pct,
    s.recent_commit_count,
    s.active_contributor_count,
    s.median_issue_response_hours,
    s.activity_change_pct,
    s.top_contributor_days_inactive,
    s.days_since_last_release,
    s.risk_level
FROM repository r
LEFT JOIN bus_factor_snapshot s
    ON s.snapshot_id = (
        SELECT s2.snapshot_id
        FROM bus_factor_snapshot s2
        WHERE s2.repo_id = r.repo_id
        ORDER BY s2.scoring_version DESC, s2.computed_at DESC, s2.snapshot_id DESC
        LIMIT 1
    );


-- ============================================================
-- Procedure: sp_declining_repos(p_days)
-- ============================================================
-- Parameterised version of Query 2 in queries_mysql.sql: compares each
-- repo's latest snapshot with the newest snapshot of the SAME scoring
-- version taken at least p_days earlier, and returns repos whose effective
-- bus factor fell or whose risk level got worse.
--   CALL sp_declining_repos(180);   -- ~6 months
--   CALL sp_declining_repos(30);    -- last month
DROP PROCEDURE IF EXISTS sp_declining_repos;
DELIMITER $$
CREATE PROCEDURE sp_declining_repos(IN p_days INT)
BEGIN
    WITH latest AS (
        SELECT repo_id, snapshot_id, computed_at, scoring_version
        FROM v_repo_latest_snapshot
        WHERE snapshot_id IS NOT NULL
    ),
    paired AS (
        SELECT
            l.repo_id,
            l.snapshot_id AS now_id,
            (SELECT s.snapshot_id
               FROM bus_factor_snapshot s
              WHERE s.repo_id = l.repo_id
                AND s.scoring_version = l.scoring_version
                AND s.computed_at <= l.computed_at - INTERVAL p_days DAY
              ORDER BY s.computed_at DESC, s.snapshot_id DESC
              LIMIT 1) AS then_id
        FROM latest l
    )
    SELECT
        r.owner,
        r.name,
        then_s.computed_at AS then_at,
        now_s.computed_at  AS now_at,
        COALESCE(then_s.recent_bus_factor, then_s.bus_factor) AS bus_factor_then,
        COALESCE(now_s.recent_bus_factor, now_s.bus_factor)   AS bus_factor_now,
        then_s.risk_level  AS risk_then,
        now_s.risk_level   AS risk_now
    FROM paired p
    JOIN bus_factor_snapshot now_s  ON now_s.snapshot_id  = p.now_id
    JOIN bus_factor_snapshot then_s ON then_s.snapshot_id = p.then_id
    JOIN repository r ON r.repo_id = p.repo_id
    WHERE COALESCE(now_s.recent_bus_factor, now_s.bus_factor)
              < COALESCE(then_s.recent_bus_factor, then_s.bus_factor)
       OR fn_risk_rank(now_s.risk_level) > fn_risk_rank(then_s.risk_level)
    ORDER BY
        fn_risk_rank(now_s.risk_level) - fn_risk_rank(then_s.risk_level) DESC,
        COALESCE(then_s.recent_bus_factor, then_s.bus_factor)
            - COALESCE(now_s.recent_bus_factor, now_s.bus_factor) DESC;
END$$
DELIMITER ;


-- ============================================================
-- Trigger: trg_snapshot_risk_alert
-- ============================================================
-- Fires after every new snapshot. If the repo's risk level is worse than in
-- the snapshot just before it in time (same scoring version), it records a
-- row in risk_alert dated at the snapshot's own computed_at — so alerts
-- produced while back-filling history carry the date the risk actually rose.
-- Because it runs inside the sync's per-repo transaction, a rolled-back sync
-- leaves no orphan alert behind.
DROP TRIGGER IF EXISTS trg_snapshot_risk_alert;
DELIMITER $$
CREATE TRIGGER trg_snapshot_risk_alert
AFTER INSERT ON bus_factor_snapshot
FOR EACH ROW
BEGIN
    DECLARE v_prev_level VARCHAR(10);

    -- Scalar subquery (not SELECT ... INTO) so "no previous snapshot"
    -- just yields NULL instead of a no-data warning.
    SET v_prev_level = (
        SELECT s.risk_level
        FROM bus_factor_snapshot s
        WHERE s.repo_id = NEW.repo_id
          AND s.scoring_version = NEW.scoring_version
          AND s.snapshot_id <> NEW.snapshot_id
          AND s.computed_at < NEW.computed_at
        ORDER BY s.computed_at DESC, s.snapshot_id DESC
        LIMIT 1
    );

    IF v_prev_level IS NOT NULL
       AND fn_risk_rank(NEW.risk_level) > fn_risk_rank(v_prev_level) THEN
        INSERT INTO risk_alert (repo_id, snapshot_id, previous_level, new_level, created_at)
        VALUES (NEW.repo_id, NEW.snapshot_id, v_prev_level, NEW.risk_level, NEW.computed_at);
    END IF;
END$$
DELIMITER ;
