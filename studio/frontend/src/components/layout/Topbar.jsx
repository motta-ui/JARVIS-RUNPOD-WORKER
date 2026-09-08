import { useEffect, useState } from 'react'
import { useStudio } from '../../store/useStore.jsx'
import { api } from '../../api/client.js'

export default function Topbar() {
  const { online, currentEngine } = useStudio()
  const [engineHealth, setEngineHealth] = useState(null)

  useEffect(() => {
    api.engines.list()
      .then((list) => setEngineHealth(list.find((e) => e.id === currentEngine)))
      .catch(() => setEngineHealth(null))
  }, [currentEngine])

  return (
    <header
      style={{
        height: 'var(--topbar-h)',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        background: 'var(--bg-0)',
      }}
    >
      <div style={{ fontFamily: 'var(--font-display)', fontSize: 14, fontWeight: 600 }}>
        JARVIS AI STUDIO
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span className="chip active">
          <span className="dot" style={{ background: online ? 'var(--success)' : 'var(--danger)' }} />
          {online ? 'Ligado' : 'Sem ligação ao backend'}
        </span>
        <span className="chip">
          Engine: {currentEngine} {engineHealth?.health?.online ? '· pronto' : ''}
        </span>
        <span className="chip">Créditos: —</span>
        <button className="btn" title="Definições">⚙</button>
      </div>
    </header>
  )
}
