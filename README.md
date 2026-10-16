# 🚌 Bus Factor Tracker

> *"I can tell you which of your project''s dependencies are one person away from going unmaintained."*

A full-stack DBMS project that estimates **bus factor** and **maintainer burnout risk** for real GitHub repositories using live public API data.

Built for **SEM 5 — Database Management Systems**.

---

## What Is Bus Factor?

**Bus factor** = the smallest number of top contributors whose combined commits account for ≥50% of total recent activity.

A bus factor of **1** means a single person''s absence would kill the project (critical risk). A bus factor of **4+** means the project is healthy and distributed.

---

## Features

- 📊 **Risk Dashboard** — Risk-ranked list of all tracked repos (Critical / High / Medium / Healthy)
- 📈 **Trend Charts** — Bus factor over time for each repo
- 🔍 **GitHub Search** — Add any public repo to the tracker via live GitHub search
- 🗑️ **Repo Management** — Add/remove repos; `repos.txt` stays in sync automatically
- ⚡ **FastAPI Backend** — Auto-generated `/docs` (Swagger UI) with all endpoints
- 🛢️ **MySQL Database** — Fully normalized schema (3NF), window functions, ACID transactions

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | MySQL |
| Backend | Python + FastAPI |
| Sync Script | Python (`scripts/sync_mysql.py`) |
| Frontend | React + Recharts (Vite) |

---

## Project Structure

```
bus-factor-tracker/
├── backend/
│   ├── main.py          # FastAPI app (all API endpoints)
│   ├── db.py            # MySQL connection helper
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── styles.css
│   │   └── components/
│   ├── index.html
│   └── package.json
├── scripts/
│   └── sync_mysql.py    # GitHub API → MySQL sync script
├── sql/
│   ├── schema_mysql.sql  # Full database schema
│   └── queries_mysql.sql # Analytics queries
├── repos.txt            # Curated list of repos to track
├── .env.example         # Environment variable template
└── requirements_mysql.txt
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- MySQL 8.0+
- A [GitHub Personal Access Token](https://github.com/settings/tokens) (read-only, public repos)

### 2. Database

```sql
source sql/schema_mysql.sql
source sql/objects_mysql.sql   -- view, stored function/procedure, trigger
```

Already have a database from an older schema? Run the migrations you haven't
run yet (each only once, in order) instead of the schema file, then the
objects file:

```sql
source sql/migrate_001_burnout_signals.sql
source sql/migrate_002_bots_recency.sql
source sql/objects_mysql.sql
```

### 3. Environment Variables

```bash
cp .env.example .env
# Edit .env — fill in GITHUB_TOKEN, DB_HOST, DB_USER, DB_PASSWORD
```

### 4. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
# Swagger UI → http://localhost:8000/docs
```

### 5. Sync Data

```bash
pip install -r requirements_mysql.txt
python scripts/sync_mysql.py
```

Each run adds one snapshot per repo, which is what the trend chart and
`sp_declining_repos` compare. To run it daily on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_sync_task.ps1   # registers a 09:00 daily task
powershell -ExecutionPolicy Bypass -File scripts\run_sync.ps1             # one run now, logged to logs\sync.log
```

### 6. Frontend

```bash
cd frontend
npm install
npm run dev
# App → http://localhost:5173
```

---

## Risk Scoring

Bots (`dependabot[bot]`, `k8s-ci-robot`, `pytorchmergebot`, ...) are excluded
from every calculation. The base level comes from the bus factor over the
**last 12 months**. If a repo had fewer than 10 commits in that time, the
all-time bus factor is used instead.

| Risk Level | Criteria |
|---|---|
| 🔴 Critical | Bus factor = 1, or the repo is archived |
| 🟠 High | Bus factor = 2 |
| 🟡 Medium | Bus factor 3–4 |
| 🟢 Healthy | Bus factor 5+ |

Each burnout warning sign then raises it one level (capped at Critical):

| Signal | Threshold |
|---|---|
| No recent work | no commits at all in the last 12 months |
| Slow issue responses | median first reply > 30 days (at least 5 answered issues) |
| Commit activity decline | last 12 weeks ≥ 50% below the 40 weeks before (only if the earlier period averaged ≥ 1 commit/week) |
| Top contributor gone quiet | no commit in > 180 days, if they wrote ≥ 25% of commits |

Days since the last release is shown but doesn't change the level. The
repo page lists the exact reasons behind each score; the thresholds live in
`assess_risk()` in `scripts/sync_mysql.py`.

The first time a repo is scored with this method, the sync also rebuilds one
snapshot per month for the past 12 months from GitHub's weekly commit data,
so trends and `sp_declining_repos` work immediately. Each snapshot records its
`scoring_version`; snapshots from different versions are never compared.

---|---|
| 🔴 Critical | Bus factor = 1, or the repo is archived |
| 🟠 High | Bus factor = 2 |
| 🟡 Medium | Bus factor 3–4 |
| 🟢 Healthy | Bus factor 5+ |

Each burnout warning sign then raises it one level (capped at Critical):

| Signal | Threshold |
|---|---|
| Slow issue responses | median first reply > 30 days |
| Commit activity decline | last 12 weeks ≥ 50% below the 40 weeks before |
| Top contributor gone quiet | no commit in > 180 days, if they wrote ≥ 25% of commits |

Days since the last release is shown but doesn't change the level. The
repo page lists the exact reasons behind each score; the thresholds live in
`assess_risk()` in `scripts/sync_mysql.py`.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/repos` | Risk-ranked repo list |
| `GET` | `/api/repos/{owner}/{name}` | Repo detail + contributor breakdown |
| `GET` | `/api/repos/{owner}/{name}/trend` | Bus factor history |
| `GET` | `/api/stats/summary` | Dashboard aggregate counts |
| `GET` | `/api/stats/declining?days=180` | Repos whose bus factor or risk worsened (`sp_declining_repos`) |
| `GET` | `/api/alerts` | Recent risk increases (written by `trg_snapshot_risk_alert`) |
| `GET` | `/api/github/search?q=...` | Search GitHub repos |
| `POST` | `/api/repos` | Add a repo to track |
| `DELETE` | `/api/repos/{owner}/{name}` | Remove a repo |

---

## License

MIT
