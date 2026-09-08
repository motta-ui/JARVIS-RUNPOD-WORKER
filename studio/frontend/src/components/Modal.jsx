export default function Modal({ open, onClose, title, children, width = 480 }) {
  if (!open) return null
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="panel"
        style={{ width, maxWidth: '90vw', maxHeight: '85vh', overflowY: 'auto', padding: 22, boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontWeight: 600, fontSize: 15 }}>{title}</div>
          <button className="btn" style={{ padding: '4px 10px' }} onClick={onClose}>✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
