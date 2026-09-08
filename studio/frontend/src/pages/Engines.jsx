import { useEffect, useState } from 'react'
import { api } from '../api/client.js'

export default function Engines() {
  const [engines, setEngines] = useState([])

  useEffect(() => {
    api.engines.list().then(setEngines)
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Engines</h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
        {engines.map((e) => (
          <div key={e.id} className="panel" style={{ padding: 18 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ fontWeight: 600 }}>{e.name}</div>
              <span className="dot" style={{ background: e.health?.online ? 'var(--success)' : 'var(--danger)', boxShadow: 'none' }} />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-1)', marginBottom: 10 }}>{e.health?.detail}</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {Object.entries(e.capabilities || {})
                .filter(([, v]) => v === true)
                .map(([k]) => (
                  <span key={k} className="chip">{k}</span>
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
