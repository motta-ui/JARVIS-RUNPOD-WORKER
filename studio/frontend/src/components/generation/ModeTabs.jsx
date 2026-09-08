export default function ModeTabs({ modes, activeMode, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 18 }}>
      {modes.map((m) => (
        <button
          key={m.id}
          onClick={() => onChange(m.id)}
          className={`chip ${activeMode === m.id ? 'active' : ''}`}
          style={{ fontSize: 13, padding: '7px 14px' }}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}
