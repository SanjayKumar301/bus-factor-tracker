import RiskBadge from './RiskBadge.jsx'

// Recent risk-level increases, written by the trg_snapshot_risk_alert
// trigger during sync. Renders nothing until there's at least one alert.
export default function AlertsPanel({ alerts, onSelectRepo }) {
  if (!alerts || alerts.length === 0) return null

  return (
    <div className="panel">
      <h2 className="section-title">Recent risk increases</h2>
      <ul className="alert-list">
        {alerts.map((a) => (
          <li key={a.alert_id} className="alert-row">
            <button className="alert-repo" onClick={() => onSelectRepo({ owner: a.owner, name: a.name })}>
              {a.owner}/{a.name}
            </button>
            <span className="alert-change">
              <RiskBadge level={a.previous_level} />
              <span className="alert-arrow">→</span>
              <RiskBadge level={a.new_level} />
            </span>
            <span className="alert-time">{new Date(a.created_at).toLocaleDateString()}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
