-- Bus Factor Tracker — MySQL Schema
-- Run this once against a fresh database:
--   mysql -u root -p bus_factor_tracker < schema.sql
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
    github_account_created_at  DATE
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
    bus_factor                   INT NOT NULL,
    top_contributor_pct          FLOAT,
    active_contributor_count     INT,
    median_issue_response_hours  FLOAT,
    risk_level                   ENUM('Critical', 'High', 'Medium', 'Healthy'),
    FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Helpful indexes for the analytical queries in the project guide
CREATE INDEX idx_repo_contributor_repo ON repo_contributor(repo_id);
CREATE INDEX idx_issue_repo ON issue(repo_id);
CREATE INDEX idx_snapshot_repo_time ON bus_factor_snapshot(repo_id, computed_at);
