export default function HistoryPanel({ jobs, onSelect, onSeeAll }) {
  return (
    <div className="panel" style={{ padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Recentes</div>
        {onSeeAll && (
          <button className="btn" style={{ padding: '3px 10px', fontSize: 11 }} onClick={onSeeAll}>
            Ver todas
          </button>
        )}
      </div>
      {jobs.length === 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Sem gerações recentes.</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {jobs.slice(0, 6).map((j) => (
          <button
            key={j.id}
            onClick={() => onSelect?.(j)}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, textAlign: 'left',
              background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 8, padding: 8,
            }}
          >
            <div style={{ width: 34, height: 34, borderRadius: 6, background: 'var(--bg-2)', flexShrink: 0 }} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {j.prompt || j.mode}
              </div>
              <div style={{ fontSize: 10.5, color: 'var(--text-2)' }}>{j.status}</div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
