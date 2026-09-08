export default function PresetStatusBanner({ preset }) {
  if (!preset || !preset.status_detail) return null

  const tone = preset.status === 'planned' ? 'var(--accent-warm)' : 'var(--accent-cool)'

  return (
    <div
      className="panel"
      style={{ padding: '10px 14px', marginBottom: 16, borderLeft: `3px solid ${tone}`, fontSize: 12.5, color: 'var(--text-1)' }}
    >
      {preset.status_detail}
    </div>
  )
}
