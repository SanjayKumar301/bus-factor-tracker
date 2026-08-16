const GAUGES = [
  { key: 'critical_count', label: 'Critical', color: 'var(--risk-critical)' },
  { key: 'high_count', label: 'High', color: 'var(--risk-high)' },
  { key: 'medium_count', label: 'Medium', color: 'var(--risk-medium)' },
  { key: 'healthy_count', label: 'Healthy', color: 'var(--risk-healthy)' },
]

export default function SummaryBar({ summary }) {
  if (!summary) return null

  return (
    <div className="summary-strip">
      {GAUGES.map((g) => (
        <div key={g.key} className="gauge" style={{ '--gauge-color': g.color }}>
          <div className="gauge-count">{summary[g.key]}</div>
          <div className="gauge-label">{g.label}</div>
        </div>
      ))}
    </div>
  )
}
