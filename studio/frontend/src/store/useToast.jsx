import { createContext, useCallback, useContext, useState } from 'react'

const ToastContext = createContext(null)

let idCounter = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const remove = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback((message, type = 'info', timeout = 4000) => {
    const id = ++idCounter
    setToasts((prev) => [...prev, { id, message, type }])
    if (timeout) setTimeout(() => remove(id), timeout)
    return id
  }, [remove])

  const toast = {
    info: (msg) => push(msg, 'info'),
    success: (msg) => push(msg, 'success'),
    error: (msg) => push(msg, 'error', 6000),
  }

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div
        style={{
          position: 'fixed', bottom: 20, right: 20, display: 'flex',
          flexDirection: 'column', gap: 8, zIndex: 1000, maxWidth: 340,
        }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="panel"
            style={{
              padding: '10px 14px',
              fontSize: 13,
              borderLeft: `3px solid ${
                t.type === 'error' ? 'var(--danger)' : t.type === 'success' ? 'var(--success)' : 'var(--accent-cool)'
              }`,
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
            }}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast deve ser usado dentro de ToastProvider')
  return ctx
}
