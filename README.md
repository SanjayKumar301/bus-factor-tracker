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

### 6. Frontend

```bash
cd frontend
npm install
npm run dev
# App → http://localhost:5173
```

---

## Risk Scoring

| Risk Level | Criteria |
|---|---|
| 🔴 Critical | Bus factor = 1 |
| 🟠 High | Bus factor = 2 |
| 🟡 Medium | Bus factor 3–4 |
| 🟢 Healthy | Bus factor 5+ |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/repos` | Risk-ranked repo list |
| `GET` | `/api/repos/{owner}/{name}` | Repo detail + contributor breakdown |
| `GET` | `/api/repos/{owner}/{name}/trend` | Bus factor history |
| `GET` | `/api/stats/summary` | Dashboard aggregate counts |
| `GET` | `/api/github/search?q=...` | Search GitHub repos |
| `POST` | `/api/repos` | Add a repo to track |
| `DELETE` | `/api/repos/{owner}/{name}` | Remove a repo |

---

## License

MIT
