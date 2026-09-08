import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../store/useToast.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'
import Modal from '../components/Modal.jsx'

const FILTERS = ['all', 'image', 'video', 'audio', 'motion']

function Thumb({ item, style }) {
  const url = item.thumbnail_url || item.file_url
  if (!url) return <div style={style} />
  if (item.kind === 'video') {
    return <video src={url} style={style} muted />
  }
  if (item.kind === 'audio') {
    return (
      <div style={{ ...style, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28 }}>
        🎵
      </div>
    )
  }
  return <img src={url} alt={item.prompt || item.kind} style={{ ...style, objectFit: 'cover' }} />
}

export default function Gallery() {
  const toast = useToast()
  const [filter, setFilter] = useState('all')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [toDelete, setToDelete] = useState(null)

  const load = () => {
    setLoading(true)
    api.gallery.list(filter).then(setItems).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [filter]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleFavorite = async (item, e) => {
    e?.stopPropagation()
    await api.gallery.favorite(item.id, !item.favorite)
    setItems((prev) => prev.map((i) => (i.id === item.id ? { ...i, favorite: !i.favorite } : i)))
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    await api.gallery.delete(toDelete.id)
    toast.success('Item eliminado da galeria.')
    setSelected(null)
    setToDelete(null)
    load()
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Gallery</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {FILTERS.map((f) => (
          <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>
            {f === 'all' ? 'All' : f[0].toUpperCase() + f.slice(1) + 's'}
          </button>
        ))}
      </div>

      {loading && <div style={{ color: 'var(--text-1)' }}>A carregar…</div>}
      {!loading && items.length === 0 && (
        <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--text-1)' }}>
          Ainda não há criações aqui. As gerações que completares aparecem nesta galeria.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
        {items.map((item) => (
          <div key={item.id} className="panel" style={{ padding: 12, cursor: 'pointer' }} onClick={() => setSelected(item)}>
            <div style={{ position: 'relative', aspectRatio: '16/9', background: 'var(--bg-2)', borderRadius: 8, marginBottom: 8, overflow: 'hidden' }}>
              <Thumb item={item} style={{ width: '100%', height: '100%', borderRadius: 8 }} />
              <button
                onClick={(e) => toggleFavorite(item, e)}
                style={{
                  position: 'absolute', top: 6, right: 6, border: 'none', background: 'rgba(0,0,0,0.5)',
                  borderRadius: 6, width: 26, height: 26, color: item.favorite ? 'var(--accent-warm)' : '#fff',
                }}
              >
                ★
              </button>
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {item.prompt || item.kind}
            </div>
          </div>
        ))}
      </div>

      <Modal open={!!selected} onClose={() => setSelected(null)} title={selected?.kind?.toUpperCase() || ''} width={520}>
        {selected && (
          <div>
            <div style={{ aspectRatio: '16/9', background: 'var(--bg-2)', borderRadius: 8, marginBottom: 14, overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              {selected.kind === 'video' && selected.file_url && (
                <video src={selected.file_url} controls style={{ maxWidth: '100%', maxHeight: '100%' }} />
              )}
              {selected.kind === 'image' && selected.file_url && (
                <img src={selected.file_url} alt={selected.prompt} style={{ maxWidth: '100%', maxHeight: '100%' }} />
              )}
              {selected.kind === 'audio' && selected.file_url && (
                <audio src={selected.file_url} controls style={{ width: '90%' }} />
              )}
              {!selected.file_url && <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Ficheiro indisponível</div>}
            </div>
            <div style={{ fontSize: 13, marginBottom: 10 }}>{selected.prompt}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 12, color: 'var(--text-1)', marginBottom: 16 }}>
              <div>Engine: {selected.engine}</div>
              <div>Model: {selected.model}</div>
              <div>Seed: {selected.seed ?? '—'}</div>
              <div>Resolução: {selected.resolution || '—'}</div>
              <div>Duração: {selected.duration_seconds ? `${selected.duration_seconds}s` : '—'}</div>
              <div>Data: {new Date(selected.created_at).toLocaleString('pt-PT')}</div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <a
                className="btn btn-primary"
                href={selected.file_url || undefined}
                download
                style={{ pointerEvents: selected.file_url ? 'auto' : 'none', opacity: selected.file_url ? 1 : 0.5 }}
              >
                Download
              </a>
              <button className="btn" onClick={(e) => toggleFavorite(selected, e)}>
                {selected.favorite ? '★ Favorito' : '☆ Favoritar'}
              </button>
              <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => setToDelete(selected)}>Eliminar</button>
            </div>
          </div>
        )}
      </Modal>

      <ConfirmModal
        open={!!toDelete}
        title="Eliminar da galeria"
        message="Esta ação remove o item e o ficheiro associado. Não pode ser desfeita."
        onCancel={() => setToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  )
}
