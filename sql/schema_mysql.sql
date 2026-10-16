-- Bus Factor Tracker — MySQL Schema
-- Run this once against a fresh database:
--   mysql -u root -p bus_factor_tracker < sql/schema_mysql.sql
--   mysql -u root -p bus_factor_tracker < sql/objects_mysql.sql
--
-- (create the database first:  CREATE DATABASE bus_factor_tracker;)

CREATE TABLE repository (
    repo_id           INT AUTO_INCREMENT PRIMARY KEY,
    owner             VARCHAR(255) NOT NULL,
    name              VARCHAR(255) NOT NULL,
    primary_language  VARCHAR(100),
    stars             INT DEFAULT 0,
    forks             INT DEFAULT 0,
    created_at        DATE,
    is_archived       BOOLEAN DEFAULT FALSE,
    last_synced_at    DATETIME,
    UNIQUE KEY uq_owner_name (owner, name)
) ENGINE=InnoDB;

CREATE TABLE contributor (
    contributor_id             INT AUTO_INCREMENT PRIMARY KEY,
    github_username            VARCHAR(255) NOT NULL UNIQUE,
    github_account_created_at  DATE,
    is_bot                     BOOLEAN NOT NULL DEFAULT FALSE  -- excluded from bus factor / activity
) ENGINE=InnoDB;

CREATE TABLE repo_contributor (
    repo_id          INT NOT NULL,
    contributor_id   INT NOT NULL,
    total_commits    INT NOT NULL DEFAULT 0,
    additions        INT DEFAULT 0,
    deletions        INT DEFAULT 0,
    first_commit_at  DATE,
    last_commit_at   DATE,
    PRIMARY KEY (repo_id, contributor_id),
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (contributor_id) REFERENCES contributor(contributor_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Commits per contributor per week (weeks with at least one commit only),
-- from GitHub's stats/contributors breakdown. Lets the bus factor be computed
-- for any time window and as of any past date (history backfill).
CREATE TABLE contributor_weekly_commits (
    repo_id         INT NOT NULL,
    contributor_id  INT NOT NULL,
    week_start      DATE NOT NULL,
    commits         INT NOT NULL,
    PRIMARY KEY (repo_id, contributor_id, week_start),
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (contributor_id) REFERENCES contributor(contributor_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE issue (
    issue_id          BIGINT PRIMARY KEY,        -- GitHub's own issue id, so no collisions across repos
    repo_id           INT NOT NULL,
    opened_by         INT,
    state             VARCHAR(20) NOT NULL,
    created_at        DATETIME NOT NULL,
    first_response_at DATETIME,
    closed_at         DATETIME,
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (opened_by) REFERENCES contributor(contributor_id)
) ENGINE=InnoDB;

CREATE TABLE pull_request (
    pr_id       BIGINT PRIMARY KEY,
    repo_id     INT NOT NULL,
    opened_by   INT,
    state       VARCHAR(20) NOT NULL,
    created_at  DATETIME NOT NULL,
    merged_at   DATETIME,
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (opened_by) REFERENCES contributor(contributor_id)
) ENGINE=InnoDB;

-- Note: "release" is a reserved word in MySQL (used in RELEASE SAVEPOINT), so
-- this table is named repo_release instead to avoid needing backticks everywhere.
CREATE TABLE repo_release (
    release_id    BIGINT PRIMARY KEY,
    repo_id       INT NOT NULL,
    published_by  INT,
    tag_name      VARCHAR(100),
    published_at  DATETIME,
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE,
    FOREIGN KEY (published_by) REFERENCES contributor(contributor_id)
) ENGINE=InnoDB;

CREATE TABLE weekly_activity (
    repo_id      INT NOT NULL,
    week_start   DATE NOT NULL,
    commit_count INT DEFAULT 0,
    PRIMARY KEY (repo_id, week_start),
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE bus_factor_snapshot (
    snapshot_id                  INT AUTO_INCREMENT PRIMARY KEY,
    repo_id                      INT NOT NULL,
    computed_at                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    bus_factor                   INT NOT NULL,             -- all-time, bots excluded (v2)
    recent_bus_factor            INT,                      -- last 52 weeks, bots excluded
    top_contributor_pct          FLOAT,
    recent_top_contributor_pct   FLOAT,
    recent_commit_count          INT,
    active_contributor_count     INT,
    median_issue_response_hours  FLOAT,
    -- burnout signals (see compute_and_insert_snapshot in sync_mysql.py)
    activity_change_pct            FLOAT,   -- avg weekly commits, last 12 weeks vs the 40 before (%)
    top_contributor_days_inactive  INT,     -- days since the top contributor's last commit
    days_since_last_release        INT,
    risk_level                   ENUM('Critical', 'High', 'Medium', 'Healthy'),
    scoring_version              TINYINT NOT NULL DEFAULT 1, -- snapshots are only compared within a version
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- One row per time a repo's risk level got WORSE between consecutive
-- snapshots. Written only by the trg_snapshot_risk_alert trigger
-- (sql/objects_mysql.sql).
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

-- Helpful indexes for the analytical queries in the project guide
CREATE INDEX idx_repo_contributor_repo ON repo_contributor(repo_id);
CREATE INDEX idx_issue_repo ON issue(repo_id);
CREATE INDEX idx_snapshot_repo_time ON bus_factor_snapshot(repo_id, computed_at);
CREATE INDEX idx_risk_alert_time ON risk_alert(created_at);
CREATE INDEX idx_snapshot_repo_version_time ON bus_factor_snapshot(repo_id, scoring_version, computed_at);
CREATE INDEX idx_cwc_repo_week ON contributor_weekly_commits(repo_id, week_start);

-- Views, the stored function/procedure and the trigger live in
-- sql/objects_mysql.sql — run that file after this one.
