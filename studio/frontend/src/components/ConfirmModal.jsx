export default function ConfirmModal({ open, title, message, confirmLabel = 'Eliminar', onConfirm, onCancel }) {
  if (!open) return null
  return (
    <div
      onClick={onCancel}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="panel"
        style={{ width: 360, padding: 22, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
      >
        <div style={{ fontWeight: 600, fontSize: 15, marginBottom: 8 }}>{title}</div>
        <div style={{ fontSize: 13, color: 'var(--text-1)', marginBottom: 20, lineHeight: 1.5 }}>{message}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn" onClick={onCancel}>Cancelar</button>
          <button
            className="btn"
            style={{ background: 'var(--danger)', borderColor: 'var(--danger)', color: '#fff', fontWeight: 600 }}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
