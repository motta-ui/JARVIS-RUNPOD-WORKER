import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../store/useToast.jsx'
import Modal from '../components/Modal.jsx'

export default function Projects() {
  const toast = useToast()
  const [projects, setProjects] = useState([])
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [open, setOpen] = useState(null)

  const load = () => api.projects.list().then(setProjects)

  useEffect(() => { load() }, [])

  const create = async () => {
    if (!name.trim()) return
    setCreating(true)
    try {
      await api.projects.create({ name: name.trim(), description: '' })
      setName('')
      toast.success('Projeto criado.')
      load()
    } catch (e) {
      toast.error(`Falha ao criar projeto: ${e.message}`)
    } finally {
      setCreating(false)
    }
  }

  const openProject = async (p) => {
    const full = await api.projects.get(p.id)
    setOpen(full)
  }

  return (
    <div>
      <h2 style={{ marginBottom: 16 }}>Projects</h2>

      <div style={{ display: 'flex', gap: 8, marginBottom: 24, maxWidth: 420 }}>
        <input
          className="input"
          placeholder="Nome do novo projeto"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && create()}
        />
        <button className="btn btn-primary" onClick={create} disabled={creating || !name.trim()}>
          Criar
        </button>
      </div>

      {projects.length === 0 && (
        <div className="panel" style={{ padding: 40, textAlign: 'center', color: 'var(--text-1)' }}>
          Sem projetos ainda. Cria o primeiro acima.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 14 }}>
        {projects.map((p) => (
          <button key={p.id} className="panel" style={{ padding: 16, textAlign: 'left' }} onClick={() => openProject(p)}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>{p.name}</div>
            <div style={{ fontSize: 12, color: 'var(--text-1)' }}>{p.description || 'Sem descrição'}</div>
            <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: 10 }}>
              Atualizado {new Date(p.updated_at).toLocaleString('pt-PT')}
            </div>
          </button>
        ))}
      </div>

      <Modal open={!!open} onClose={() => setOpen(null)} title={open?.name || ''} width={560}>
        {open && (
          <div>
            <div style={{ fontSize: 13, color: 'var(--text-1)', marginBottom: 16 }}>{open.description || 'Sem descrição.'}</div>

            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Assets ({open.assets?.length || 0})</div>
            {(open.assets || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 16 }}>Nenhum asset associado.</div>}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
              {(open.assets || []).map((a) => <span key={a.id} className="chip">{a.filename}</span>)}
            </div>

            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>Jobs ({open.jobs?.length || 0})</div>
            {(open.jobs || []).length === 0 && <div style={{ fontSize: 12, color: 'var(--text-2)' }}>Nenhum job associado a este projeto ainda.</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {(open.jobs || []).map((j) => (
                <div key={j.id} style={{ fontSize: 12, color: 'var(--text-1)', display: 'flex', justifyContent: 'space-between' }}>
                  <span>{j.prompt || j.mode}</span>
                  <span className="chip">{j.status}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}
