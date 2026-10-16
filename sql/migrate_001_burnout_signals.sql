-- Migration 001 — burnout signals + risk alerts
-- For databases created with an older schema_mysql.sql. Run ONCE:
--   mysql -u root -p bus_factor_tracker < sql/migrate_001_burnout_signals.sql
-- (Fresh installs don't need this — schema_mysql.sql already includes it.)
--
-- Then (re)create the views / routines / triggers:
--   mysql -u root -p bus_factor_tracker < sql/objects_mysql.sql

-- Burnout signals, computed per snapshot by sync_mysql.py:
--   activity_change_pct            avg weekly commits, last 12 weeks vs the 40 weeks before (%)
--   top_contributor_days_inactive  days since the top contributor's last commit
--   days_since_last_release        days since the most recent GitHub release
ALTER TABLE bus_factor_snapshot
    ADD COLUMN activity_change_pct           FLOAT NULL AFTER median_issue_response_hours,
    ADD COLUMN top_contributor_days_inactive INT   NULL AFTER activity_change_pct,
    ADD COLUMN days_since_last_release       INT   NULL AFTER top_contributor_days_inactive;

-- One row per time a repo's risk level got WORSE between consecutive
-- snapshots. Written only by the trg_snapshot_risk_alert trigger.
CREATE TABLE risk_alert (
    alert_id        INT AUTO_INCREMENT PRIMARY KEY,
    repo_id         INT NOT NULL,
    snapshot_id     INT NOT NULL,
    previous_level  ENUM('Critical', 'High', 'Medium', 'Healthy') NOT NULL,
    new_level       ENUM('Critical', 'High', 'Medium', 'Healthy') NOT NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id) REFERENCES bus_factor_snapshot(snapshot_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_risk_alert_time ON risk_alert(created_at);
