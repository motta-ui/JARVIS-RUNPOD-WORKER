import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../store/useToast.jsx'
import ConfirmModal from '../components/ConfirmModal.jsx'

const EMPTY_FORM = { name: '', description: '', tags: '', compatible_model: '', file: null, preview: null }

export default function LoraManager() {
  const toast = useToast()
  const [loras, setLoras] = useState([])
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [toDelete, setToDelete] = useState(null)

  const load = () => api.loras.list().then(setLoras).catch(() => toast.error('Não foi possível carregar os LoRAs.'))

  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const create = async () => {
    if (!form.name.trim()) {
      toast.error('Dá um nome ao LoRA.')
      return
    }
    setSaving(true)
    try {
      const fd = new FormData()
      fd.append('name', form.name)
      fd.append('description', form.description)
      fd.append('compatible_model', form.compatible_model)
      fd.append('tags', JSON.stringify(form.tags.split(',').map((t) => t.trim()).filter(Boolean)))
      fd.append('engine', 'mock')
      fd.append('strength', '1.0')
      if (form.file) fd.append('file', form.file)
      if (form.preview) fd.append('preview', form.preview)
      await api.loras.create(fd)
      setForm(EMPTY_FORM)
      toast.success('LoRA adicionado.')
      load()
    } catch (e) {
      toast.error(`Falha ao adicionar LoRA: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (l) => {
    await api.loras.update(l.id, { active: !l.active })
    load()
  }

  const updateStrength = async (l, strength) => {
    setLoras((prev) => prev.map((x) => (x.id === l.id ? { ...x, strength } : x)))
  }
  const commitStrength = async (l, strength) => {
    await api.loras.update(l.id, { strength })
  }

  const confirmDelete = async () => {
    if (!toDelete) return
    await api.loras.delete(toDelete.id)
    toast.success('LoRA eliminado.')
    setToDelete(null)
    load()
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>LoRA Manager</h2>

      <div className="panel" style={{ padding: 18, marginBottom: 22, maxWidth: 560 }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 12 }}>Adicionar LoRA</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
          <div>
            <label className="label">Nome</label>
            <input className="input" value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="label">Modelo compatível</label>
            <input className="input" value={form.compatible_model} onChange={(e) => setForm((f) => ({ ...f, compatible_model: e.target.value }))} />
          </div>
        </div>
        <label className="label">Descrição</label>
        <textarea className="input" rows={2} value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} style={{ marginBottom: 12 }} />
        <label className="label">Tags (separadas por vírgula)</label>
        <input className="input" value={form.tags} onChange={(e) => setForm((f) => ({ ...f, tags: e.target.value }))} style={{ marginBottom: 12 }} />

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
          <div>
            <label className="label">Ficheiro LoRA</label>
            <input type="file" onChange={(e) => setForm((f) => ({ ...f, file: e.target.files?.[0] || null }))} />
          </div>
          <div>
            <label className="label">Preview (imagem)</label>
            <input type="file" accept="image/*" onChange={(e) => setForm((f) => ({ ...f, preview: e.target.files?.[0] || null }))} />
          </div>
        </div>

        <button className="btn btn-primary" disabled={saving} onClick={create}>
          {saving ? 'A guardar…' : 'Adicionar'}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
        {loras.map((l) => (
          <div key={l.id} className="panel" style={{ padding: 16, opacity: l.active ? 1 : 0.55 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <div>
                <div style={{ fontWeight: 600 }}>{l.name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-2)' }}>{l.compatible_model || 'qualquer modelo'}</div>
              </div>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-1)' }}>
                <input type="checkbox" checked={!!l.active} onChange={() => toggleActive(l)} />
                Ativo
              </label>
            </div>

            {l.description && <div style={{ fontSize: 12, color: 'var(--text-1)', marginBottom: 10 }}>{l.description}</div>}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
              {(l.tags || []).map((t) => <span key={t} className="chip">{t}</span>)}
            </div>

            <label className="label">Strength — {Number(l.strength).toFixed(2)}</label>
            <input
              type="range" min="0" max="1" step="0.01" value={l.strength}
              onChange={(e) => updateStrength(l, parseFloat(e.target.value))}
              onMouseUp={(e) => commitStrength(l, parseFloat(e.target.value))}
              style={{ width: '100%', marginBottom: 10 }}
            />

            <button className="btn" style={{ width: '100%', justifyContent: 'center' }} onClick={() => setToDelete(l)}>
              Eliminar
            </button>
          </div>
        ))}
      </div>

      {loras.length === 0 && (
        <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--text-1)' }}>
          Sem LoRAs ainda. Adiciona o primeiro acima.
        </div>
      )}

      <ConfirmModal
        open={!!toDelete}
        title="Eliminar LoRA"
        message={`Tens a certeza que queres eliminar "${toDelete?.name}"? Esta ação não pode ser desfeita.`}
        onCancel={() => setToDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  )
}
