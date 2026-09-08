export default function LoraPicker({ loras, selected, onToggle, onStrengthChange }) {
  const active = loras.filter((l) => l.active)

  if (active.length === 0) {
    return <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Sem LoRAs ativos. Adiciona em Sistema → LoRAs.</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {active.map((l) => {
        const isSelected = l.id in selected
        return (
          <div key={l.id} className="panel" style={{ padding: 10 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12.5, marginBottom: isSelected ? 8 : 0 }}>
              <input type="checkbox" checked={isSelected} onChange={() => onToggle(l.id)} />
              {l.name}
              <span style={{ color: 'var(--text-2)', fontSize: 11 }}>{l.compatible_model || ''}</span>
            </label>
            {isSelected && (
              <div>
                <input
                  type="range" min="0" max="1" step="0.01"
                  value={selected[l.id] ?? l.strength ?? 1}
                  onChange={(e) => onStrengthChange(l.id, parseFloat(e.target.value))}
                  style={{ width: '100%' }}
                />
                <div style={{ fontSize: 11, color: 'var(--text-2)', textAlign: 'right' }}>
                  {(selected[l.id] ?? l.strength ?? 1).toFixed(2)}
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
