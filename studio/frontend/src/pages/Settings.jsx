import { useEffect, useState } from 'react'
import { api } from '../api/client.js'

export default function Settings() {
  const [settings, setSettings] = useState({})

  useEffect(() => {
    fetch('/api/settings').then((r) => r.json()).then(setSettings)
  }, [])

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Settings</h2>
      <div className="panel" style={{ padding: 20, maxWidth: 480 }}>
        {Object.entries(settings).map(([k, v]) => (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <span style={{ color: 'var(--text-1)' }}>{k}</span>
            <span>{String(v)}</span>
          </div>
        ))}
        {Object.keys(settings).length === 0 && (
          <div style={{ color: 'var(--text-1)' }}>A carregar definições…</div>
        )}
      </div>
    </div>
  )
}
