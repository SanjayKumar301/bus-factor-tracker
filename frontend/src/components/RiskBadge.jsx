const RISK_CONFIG = {
  Critical: { color: 'var(--risk-critical)' },
  High: { color: 'var(--risk-high)' },
  Medium: { color: 'var(--risk-medium)' },
  Healthy: { color: 'var(--risk-healthy)' },
}

export default function RiskBadge({ level }) {
  const config = RISK_CONFIG[level] || { color: 'var(--text-tertiary)' }
  return (
    <span
      className="risk-badge"
      style={{ color: config.color, background: `color-mix(in srgb, ${config.color} 15%, transparent)` }}
    >
      <span className="dot" style={{ background: config.color }} />
      {level || 'Unknown'}
    </span>
  )
}
