import { useEffect, useState } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { fetchRepoDetail, fetchRepoTrend } from '../api.js'
import RiskBadge from './RiskBadge.jsx'
import ConcentrationBar from './ConcentrationBar.jsx'

const RISK_COLOR = {
  Critical: '#e5484d',
  High: '#f5a623',
  Medium: '#eab308',
  Healthy: '#2dd4bf',
}

export default function RepoDetail({ repoRef, onBack }) {
  const [detail, setDetail] = useState(null)
  const [trend, setTrend] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    setDetail(null)
    setTrend(null)
    setError(null)

    fetchRepoDetail(repoRef.owner, repoRef.name)
      .then(setDetail)
      .catch((e) => setError(e.message))

    // Trend history only exists once sync has run more than once for this
    // repo — a 404 here is expected on a fresh dataset, not a real error.
    fetchRepoTrend(repoRef.owner, repoRef.name)
      .then(setTrend)
      .catch(() => setTrend([]))
  }, [repoRef])

  if (error) {
    return (
      <div>
        <button className="back-link" onClick={onBack}>
          ← Back
        </button>
        <div className="state-message error">{error}</div>
      </div>
    )
  }

  if (!detail) {
    return (
      <div>
        <button className="back-link" onClick={onBack}>
          ← Back
        </button>
        <div className="state-message">Loading…</div>
      </div>
    )
  }

  const lineColor = RISK_COLOR[detail.risk_level] || '#8b96ad'

  return (
    <div>
      <button className="back-link" onClick={onBack}>
        ← Back to all repos
      </button>

      <div className="detail-header">
        <div>
          <h1 className="detail-title">
            <span className="owner">{detail.owner}/</span>
            {detail.name}
          </h1>
          <div className="detail-meta">
            <span>{detail.primary_language || 'unknown'}</span>
            <span>{detail.stars.toLocaleString()} stars</span>
            <span>{detail.forks.toLocaleString()} forks</span>
            {detail.is_archived && <span>archived</span>}
          </div>
        </div>
        <RiskBadge level={detail.risk_level} />
      </div>

      <div className="detail-grid">
        <div className="stat-card">
          <div className="stat-value">{detail.bus_factor ?? '—'}</div>
          <div className="stat-label">Bus factor</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{detail.top_contributor_pct != null ? `${detail.top_contributor_pct}%` : '—'}</div>
          <div className="stat-label">Top contributor share</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{detail.active_contributor_count ?? '—'}</div>
          <div className="stat-label">Active contributors</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">
            {detail.median_issue_response_hours != null ? `${Math.round(detail.median_issue_response_hours)}h` : 'n/a'}
          </div>
          <div className="stat-label">Median issue response</div>
        </div>
      </div>

      <div className="panel" style={{ '--driver-color': lineColor }}>
        <h2 className="section-title">Why {detail.risk_level || 'this'} risk</h2>
        {detail.risk_drivers.length > 0 ? (
          <ul className="driver-list">
            {detail.risk_drivers.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        ) : (
          <div className="state-message">No snapshot yet — run the sync script for this repo.</div>
        )}
      </div>

      <h2 className="section-title">Burnout signals</h2>
      <div className="detail-grid">
        <div className="stat-card">
          <div className={`stat-value${detail.activity_change_pct != null && detail.activity_change_pct <= -50 ? ' warn' : ''}`}>
            {detail.activity_change_pct != null
              ? `${detail.activity_change_pct > 0 ? '+' : ''}${Math.round(detail.activity_change_pct)}%`
              : 'n/a'}
          </div>
          <div className="stat-label">Commit activity, last 12 wks</div>
        </div>
        <div className="stat-card">
          <div className={`stat-value${detail.top_contributor_days_inactive > 180 ? ' warn' : ''}`}>
            {detail.top_contributor_days_inactive != null ? `${detail.top_contributor_days_inactive}d` : 'n/a'}
          </div>
          <div className="stat-label">Since top contributor's last commit</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">
            {detail.days_since_last_release != null ? `${detail.days_since_last_release}d` : 'n/a'}
          </div>
          <div className="stat-label">Since last release</div>
        </div>
      </div>

      {trend && trend.length > 1 && (
        <div className="panel">
          <h2 className="section-title">Bus factor over time</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={trend}>
              <CartesianGrid stroke="#253049" vertical={false} />
              <XAxis
                dataKey="computed_at"
                tickFormatter={(v) => new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                stroke="#5c6785"
                fontSize={11}
                fontFamily="IBM Plex Mono"
              />
              <YAxis stroke="#5c6785" fontSize={11} fontFamily="IBM Plex Mono" allowDecimals={false} width={28} />
              <Tooltip
                contentStyle={{ background: '#1a2438', border: '1px solid #253049', borderRadius: 6, fontFamily: 'IBM Plex Mono', fontSize: 12 }}
                labelFormatter={(v) => new Date(v).toLocaleString()}
              />
              <Line type="monotone" dataKey="bus_factor" stroke={lineColor} strokeWidth={2} dot={{ r: 3, fill: lineColor }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {trend && trend.length <= 1 && (
        <div className="panel">
          <h2 className="section-title">Bus factor over time</h2>
          <div className="state-message">Not enough history yet — run the sync script again later to build a trend.</div>
        </div>
      )}

      <div className="panel">
        <h2 className="section-title">Commit concentration</h2>
        <ConcentrationBar contributors={detail.contributors} />
      </div>

      <div className="panel">
        <h2 className="section-title">Contributors</h2>
        <div>
          <div className="contributor-row" style={{ borderBottom: '1px solid var(--border)' }}>
            <span className="col-label" style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-tertiary)' }}>
              Username
            </span>
            <span className="col-label" style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-tertiary)', textAlign: 'right' }}>
              Commits
            </span>
            <span className="col-label" style={{ fontSize: 11, textTransform: 'uppercase', color: 'var(--text-tertiary)', textAlign: 'right' }}>
              Share
            </span>
          </div>
          {detail.contributors.map((c) => (
            <div key={c.github_username} className="contributor-row">
              <span className="contributor-name">{c.github_username}</span>
              <span className="contributor-commits">{c.total_commits.toLocaleString()}</span>
              <span className="contributor-pct">{c.commit_share_pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
