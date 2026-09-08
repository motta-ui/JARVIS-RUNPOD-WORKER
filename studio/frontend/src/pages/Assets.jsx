import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../store/useToast.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'

const CATEGORIES = ['images', 'videos', 'audio', 'loras', 'references']

function AssetThumb({ asset }) {
  const style = { width: '100%', aspectRatio: '1/1', borderRadius: 6, marginBottom: 8, objectFit: 'cover', background: 'var(--bg-2)' }
  if (!asset.url) return <div style={style} />
  if (asset.category === 'videos') return <video src={asset.url} style={style} muted />
  if (asset.category === 'audio') {
    return (
      <div style={{ ...style, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 26 }}>🎵</div>
    )
  }
  return <img src={asset.url} alt={asset.filename} style={style} />
}

export default function Assets() {
  const toast = useToast()
  const [category, setCategory] = useState('images')
  const [search, setSearch] = useState('')
  const [items, setItems] = useState([])
  const [dragOver, setDragOver] = useState(false)
  const [toDelete, setToDelete] = useState(null)

  const load = () => api.assets.list(category, search || undefined).then(setItems)

  useEffect(() => { load() }, [category]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleFiles = async (files) => {
    try {
      for (const file of files) {
        await api.assets.upload(file, category)
      }
      toast.success(`${files.length} ficheiro(s) enviados.`)
      load()
    } catch (e) {
      toast.error(`Falha no upload: ${e.message}`)
    }
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    await api.assets.delete(toDelete.id)
    toast.success('Asset eliminado.')
    setToDelete(null)
    load()
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Assets</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        {CATEGORIES.map((c) => (
          <button key={c} className={`chip ${category === c ? 'active' : ''}`} onClick={() => setCategory(c)}>
            {c[0].toUpperCase() + c.slice(1)}
          </button>
        ))}
        <input
          className="input"
          placeholder="Pesquisar por nome…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          style={{ maxWidth: 220, marginLeft: 'auto' }}
        />
      </div>

      <div
        className="panel"
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragOver(false)
          handleFiles(Array.from(e.dataTransfer.files))
        }}
        style={{
          padding: 32,
          textAlign: 'center',
          borderStyle: 'dashed',
          borderColor: dragOver ? 'var(--accent-cool)' : 'var(--border)',
          color: 'var(--text-1)',
          marginBottom: 20,
        }}
      >
        Arrasta ficheiros para aqui, ou
        <label className="btn" style={{ display: 'inline-flex', marginLeft: 10 }}>
          Escolher ficheiros
          <input type="file" multiple hidden onChange={(e) => handleFiles(Array.from(e.target.files))} />
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
        {items.map((a) => (
          <div key={a.id} className="panel" style={{ padding: 10 }}>
            <AssetThumb asset={a} />
            <div style={{ fontSize: 12, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {a.filename}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 8 }}>{(a.size_bytes / 1024).toFixed(1)} KB</div>
            <button className="btn" style={{ width: '100%', justifyContent: 'center', fontSize: 11, padding: '5px 0' }} onClick={() => setToDelete(a)}>
              Eliminar
            </button>
          </div>
        ))}
      </div>

      {items.length === 0 && (
        <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--text-1)' }}>
          Nenhum asset em {category}{search ? ` para "${search}"` : ''}.
        </div>
      )}

      <ConfirmModal
        open={!!toDelete}
        title="Eliminar asset"
        message={`Eliminar "${toDelete?.filename}"? Esta ação não pode ser desfeita.`}
        onCancel={() => setToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  )
}
