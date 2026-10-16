-- Bus Factor Tracker — views, stored routines and triggers (MySQL 8.0+)
-- Safe to re-run: every object is dropped and recreated.
--   mysql -u root -p bus_factor_tracker < sql/objects_mysql.sql
--
-- Uses DELIMITER, so run it through the mysql command-line client (or
-- MySQL Workbench), not a driver that sends the file as one statement.

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
-- "Latest row per group" was previously repeated as a correlated subquery
-- in every backend endpoint. Picking by snapshot_id (not MAX(computed_at))
-- also avoids returning two rows if two snapshots share the same second.
-- LEFT JOIN so repos that have never produced a snapshot still appear.
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
    s.bus_factor,
    s.top_contributor_pct,
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
        ORDER BY s2.computed_at DESC, s2.snapshot_id DESC
        LIMIT 1
    );


-- ============================================================
-- Procedure: sp_declining_repos(p_days)
-- ============================================================
-- Parameterised version of Query 2 in queries_mysql.sql: compares each
-- repo's latest snapshot with the newest snapshot at least p_days older,
-- and returns repos whose bus factor fell or whose risk level got worse.
--   CALL sp_declining_repos(180);   -- ~6 months
--   CALL sp_declining_repos(7);     -- last week (useful while history is short)
DROP PROCEDURE IF EXISTS sp_declining_repos;
DELIMITER $$
CREATE PROCEDURE sp_declining_repos(IN p_days INT)
BEGIN
    WITH latest AS (
        SELECT repo_id, snapshot_id, computed_at
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
        then_s.bus_factor  AS bus_factor_then,
        now_s.bus_factor   AS bus_factor_now,
        then_s.risk_level  AS risk_then,
        now_s.risk_level   AS risk_now
    FROM paired p
    JOIN bus_factor_snapshot now_s  ON now_s.snapshot_id  = p.now_id
    JOIN bus_factor_snapshot then_s ON then_s.snapshot_id = p.then_id
    JOIN repository r ON r.repo_id = p.repo_id
    WHERE now_s.bus_factor < then_s.bus_factor
       OR fn_risk_rank(now_s.risk_level) > fn_risk_rank(then_s.risk_level)
    ORDER BY
        fn_risk_rank(now_s.risk_level) - fn_risk_rank(then_s.risk_level) DESC,
        then_s.bus_factor - now_s.bus_factor DESC;
END$$
DELIMITER ;


-- ============================================================
-- Trigger: trg_snapshot_risk_alert
-- ============================================================
-- Fires after every new snapshot. If the repo's risk level is worse than
-- in its previous snapshot, it records a row in risk_alert. Because it runs
-- inside the sync's per-repo transaction, a rolled-back sync leaves no
-- orphan alert behind.
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
          AND s.snapshot_id <> NEW.snapshot_id
        ORDER BY s.computed_at DESC, s.snapshot_id DESC
        LIMIT 1
    );

    IF v_prev_level IS NOT NULL
       AND fn_risk_rank(NEW.risk_level) > fn_risk_rank(v_prev_level) THEN
        INSERT INTO risk_alert (repo_id, snapshot_id, previous_level, new_level)
        VALUES (NEW.repo_id, NEW.snapshot_id, v_prev_level, NEW.risk_level);
    END IF;
END$$
DELIMITER ;
