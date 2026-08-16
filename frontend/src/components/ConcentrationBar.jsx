// The signature element: a literal, segmented visualization of who owns the
// commits to a repo. One huge segment means one person could take the whole
// project down with them if they left — that's bus factor made visible,
// not just a number in a table cell.

const SEGMENT_COLORS = [
  'var(--risk-critical)',
  'var(--risk-high)',
  'var(--risk-medium)',
  'var(--risk-healthy)',
  'var(--text-tertiary)',
  'var(--border)',
]

export default function ConcentrationBar({ contributors, compact = false }) {
  if (!contributors || contributors.length === 0) {
    return <div className="concentration-bar" style={{ background: 'var(--border)' }} />
  }

  const total = contributors.reduce((sum, c) => sum + c.total_commits, 0)
  // Show up to 5 named segments, then lump the rest into "others" so the
  // bar stays legible even for a repo with 200 contributors.
  const top = contributors.slice(0, 5)
  const restCommits = contributors.slice(5).reduce((sum, c) => sum + c.total_commits, 0)

  return (
    <div>
      <div className="concentration-bar">
        {top.map((c, i) => (
          <div
            key={c.github_username}
            className="concentration-segment"
            style={{
              width: `${(c.total_commits / total) * 100}%`,
              background: SEGMENT_COLORS[i],
            }}
            title={`${c.github_username}: ${c.total_commits} commits (${((c.total_commits / total) * 100).toFixed(1)}%)`}
          />
        ))}
        {restCommits > 0 && (
          <div
            className="concentration-segment"
            style={{ width: `${(restCommits / total) * 100}%`, background: 'var(--border)' }}
            title={`others: ${restCommits} commits`}
          />
        )}
      </div>
      {!compact && (
        <div className="concentration-caption">
          {contributors[0].github_username} holds {((contributors[0].total_commits / total) * 100).toFixed(0)}%
        </div>
      )}
    </div>
  )
}

// Table rows only have the aggregate top_contributor_pct from the list
// endpoint (fetching full contributor lists for every row would be wasteful),
// so this renders a simplified two-segment version: top contributor vs.
// everyone else. Same visual language, less data required.
export function MiniConcentrationBar({ topContributorPct, riskLevel }) {
  if (topContributorPct == null) {
    return <div className="concentration-bar" style={{ background: 'var(--border)' }} />
  }
  const color = RISK_COLOR[riskLevel] || 'var(--text-tertiary)'
  return (
    <div className="concentration-bar">
      <div className="concentration-segment" style={{ width: `${topContributorPct}%`, background: color }} />
      <div
        className="concentration-segment"
        style={{ width: `${100 - topContributorPct}%`, background: 'var(--border)' }}
      />
    </div>
  )
}

const RISK_COLOR = {
  Critical: 'var(--risk-critical)',
  High: 'var(--risk-high)',
  Medium: 'var(--risk-medium)',
  Healthy: 'var(--risk-healthy)',
}
