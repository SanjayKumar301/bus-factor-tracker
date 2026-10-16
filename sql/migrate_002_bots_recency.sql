-- Migration 002 — bot filtering, per-week contributor commits, recency-based
-- bus factor and versioned scoring.
-- For databases created before this change. Run ONCE, after migration 001:
--   mysql -u root -p bus_factor_tracker < sql/migrate_002_bots_recency.sql
-- then re-create the views / routines / triggers:
--   mysql -u root -p bus_factor_tracker < sql/objects_mysql.sql
-- (Fresh installs don't need this — schema_mysql.sql already includes it.)

-- Automation accounts (dependabot[bot], k8s-ci-robot, ...) are kept in the
-- data but excluded from every bus factor and activity calculation.
ALTER TABLE contributor
    ADD COLUMN is_bot BOOLEAN NOT NULL DEFAULT FALSE;

-- Commits per contributor per week, from GitHub's stats/contributors
-- breakdown (only weeks with at least one commit are stored). This is what
-- lets the bus factor be computed for any time window, and as of any past
-- date (history backfill).
CREATE TABLE contributor_weekly_commits (
    repo_id         INT NOT NULL,
    contributor_id  INT NOT NULL,
    week_start      DATE NOT NULL,
    commits         INT NOT NULL,
    PRIMARY KEY (repo_id, contributor_id, week_start),
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (contributor_id) REFERENCES contributor(contributor_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_cwc_repo_week ON contributor_weekly_commits(repo_id, week_start);

-- Recency-based measurements (last 52 weeks, bots excluded) and the version
-- of the scoring method that produced each snapshot. Version 1 = original
-- all-time method; version 2 = bots excluded + recency-based bus factor.
-- Snapshots of different versions are never compared with each other.
ALTER TABLE bus_factor_snapshot
    ADD COLUMN recent_bus_factor           INT     NULL AFTER bus_factor,
    ADD COLUMN recent_top_contributor_pct  FLOAT   NULL AFTER top_contributor_pct,
    ADD COLUMN recent_commit_count         INT     NULL AFTER recent_top_contributor_pct,
    ADD COLUMN scoring_version             TINYINT NOT NULL DEFAULT 1 AFTER risk_level;

CREATE INDEX idx_snapshot_repo_version_time ON bus_factor_snapshot(repo_id, scoring_version, computed_at);
