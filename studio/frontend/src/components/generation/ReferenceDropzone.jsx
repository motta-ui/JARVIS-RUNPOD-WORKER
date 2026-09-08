import { useRef, useState } from 'react'

export default function ReferenceDropzone({ label, file, onChange, accept }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  const setFile = (f) => f && onChange(f)

  return (
    <div
      className="panel"
      onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragOver(false)
        setFile(e.dataTransfer.files?.[0])
      }}
      onClick={() => !file && inputRef.current?.click()}
      style={{
        padding: 12,
        minHeight: 96,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        textAlign: 'center',
        cursor: file ? 'default' : 'pointer',
        borderStyle: 'dashed',
        borderColor: dragOver ? 'var(--accent-cool)' : 'var(--border)',
        position: 'relative',
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        hidden
        onChange={(e) => setFile(e.target.files?.[0])}
      />
      {!file && (
        <>
          <div style={{ fontSize: 12, color: 'var(--text-1)' }}>{label}</div>
          <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 4 }}>arrastar ou clicar</div>
        </>
      )}
      {file && (
        <>
          <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 2 }}>{label}</div>
          <div
            style={{
              fontSize: 11,
              color: 'var(--text-1)',
              maxWidth: '100%',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {file.name}{typeof file.size === 'number' ? ` · ${(file.size / 1024).toFixed(0)} KB` : ''}
          </div>
          <button
            className="btn"
            style={{ marginTop: 8, padding: '4px 10px', fontSize: 11 }}
            onClick={(e) => { e.stopPropagation(); onChange(null) }}
          >
            Remover
          </button>
        </>
      )}
    </div>
  )
}
