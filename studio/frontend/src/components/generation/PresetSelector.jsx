const STATUS_LABEL = {
  demo: { label: 'Demo', color: 'var(--accent-cool)' },
  live: { label: 'Live', color: 'var(--success)' },
  planned: { label: 'Planeado', color: 'var(--accent-warm)' },
}

export default function PresetSelector({ presets, selectedId, onSelect }) {
  const selected = presets.find((p) => p.id === selectedId)

  return (
    <div>
      <label className="label">Preset</label>
      <select className="input" value={selectedId || ''} onChange={(e) => onSelect(e.target.value)}>
        {presets.map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>
      {selected && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
          <span
            className="chip"
            style={{ borderColor: STATUS_LABEL[selected.status]?.color, color: STATUS_LABEL[selected.status]?.color }}
          >
            {STATUS_LABEL[selected.status]?.label || selected.status}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-2)' }}>engine: {selected.engine_id}</span>
        </div>
      )}
      {selected?.description && (
        <div style={{ fontSize: 11.5, color: 'var(--text-1)', marginTop: 6, lineHeight: 1.4 }}>
          {selected.description}
        </div>
      )}
    </div>
  )
}
