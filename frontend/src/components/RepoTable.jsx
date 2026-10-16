import RiskBadge from './RiskBadge.jsx'
import { MiniConcentrationBar } from './ConcentrationBar.jsx'

const RISK_FILTERS = ['All', 'Critical', 'High', 'Medium', 'Healthy']

export default function RepoTable({ repos, activeFilter, onFilterChange, onSelectRepo, onRemoveRepo }) {
  function handleRemoveClick(e, repo) {
    e.stopPropagation() // don't also trigger the row's onSelectRepo
    if (window.confirm(`Stop tracking ${repo.owner}/${repo.name}? This deletes its history too.`)) {
      onRemoveRepo(repo)
    }
  }

  return (
    <>
      <div className="filter-bar">
        {RISK_FILTERS.map((f) => (
          <button
            key={f}
            className={`filter-chip ${activeFilter === f ? 'active' : ''}`}
            onClick={() => onFilterChange(f)}
          >
            {f}
          </button>
        ))}
      </div>

      <div className="repo-table">
        <div className="repo-row repo-row-header">
          <span className="col-label">Repository</span>
          <span className="col-label" style={{ textAlign: 'center' }}>
            Bus factor
          </span>
          <span className="col-label concentration-col">Commit concentration</span>
          <span className="col-label" style={{ textAlign: 'right' }}>
            Risk
          </span>
        </div>

        {repos.length === 0 && <div className="state-message">No repos match this filter.</div>}

        {repos.map((repo) => (
          <div key={repo.repo_id} className="repo-row" onClick={() => onSelectRepo(repo)}>
            <div className="repo-name-cell">
              <div className="repo-name">
                <span className="repo-owner">{repo.owner}/</span>
                {repo.name}
              </div>
              <div className="repo-meta">
                {repo.primary_language || 'unknown'} · {repo.stars.toLocaleString()} stars
                {repo.is_archived ? ' · archived' : ''}
              </div>
            </div>
            <div className="bus-factor-cell">{repo.effective_bus_factor ?? '—'}</div>
            <div className="concentration-col">
              <MiniConcentrationBar topContributorPct={repo.effective_top_contributor_pct} riskLevel={repo.risk_level} />
            </div>
            <div className="repo-row-end">
              <RiskBadge level={repo.risk_level} />
              <button
                className="row-remove-btn"
                onClick={(e) => handleRemoveClick(e, repo)}
                aria-label={`Stop tracking ${repo.owner}/${repo.name}`}
                title="Stop tracking"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
