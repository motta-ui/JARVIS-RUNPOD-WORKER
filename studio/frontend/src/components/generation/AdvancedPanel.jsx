export default function AdvancedPanel({ fields, values, onChange }) {
  return (
    <div className="panel" style={{ padding: 16 }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 12 }}>Advanced</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {fields.map((f) => (
          <div key={f.id} style={{ gridColumn: f.type === 'textarea' ? '1 / -1' : 'auto' }} title={f.tooltip}>
            <label className="label">{f.label}</label>
            {f.type === 'boolean' && (
              <input
                type="checkbox"
                checked={!!values[f.id]}
                onChange={(e) => onChange(f.id, e.target.checked)}
              />
            )}
            {f.type === 'number' && (
              <input
                type="number"
                className="input"
                min={f.min}
                max={f.max}
                step={f.step}
                value={values[f.id] ?? f.default}
                onChange={(e) => onChange(f.id, parseFloat(e.target.value))}
              />
            )}
            {f.type === 'textarea' && (
              <textarea
                className="input"
                rows={2}
                value={values[f.id] ?? f.default}
                onChange={(e) => onChange(f.id, e.target.value)}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
