import { useEffect, useState } from 'react'
import { api } from '../api/client.js'
import { useToast } from '../store/useToast.jsx'

const STATUS_STYLE = {
  OFFLINE: { color: 'var(--text-2)', label: 'OFFLINE' },
  CONNECTING: { color: 'var(--accent-warm)', label: 'CONNECTING' },
  ONLINE: { color: 'var(--success)', label: 'ONLINE' },
  ERROR: { color: 'var(--danger)', label: 'ERROR' },
}

export default function Cloud() {
  const toast = useToast()
  const [providers, setProviders] = useState([])
  const [provider, setProvider] = useState('runpod')
  const [workerUrl, setWorkerUrl] = useState('')
  const [workerPort, setWorkerPort] = useState(7872)
  const [workerName, setWorkerName] = useState('')
  const [workerToken, setWorkerToken] = useState('')
  const [workerTokenSet, setWorkerTokenSet] = useState(false)

  const [status, setStatus] = useState('OFFLINE')
  const [lastHealthCheck, setLastHealthCheck] = useState(null)
  const [workerInfo, setWorkerInfo] = useState(null)
  const [lastError, setLastError] = useState(null)

  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    Promise.all([api.cloud.providers(), api.cloud.getConnection()])
      .then(([provs, conn]) => {
        setProviders(provs)
        setProvider(conn.provider || 'runpod')
        setWorkerUrl(conn.worker_url || '')
        setWorkerPort(conn.worker_port || 7872)
        setWorkerName(conn.worker_name || '')
        setWorkerTokenSet(!!conn.worker_token_set)
        setStatus(conn.status || 'OFFLINE')
        setLastHealthCheck(conn.last_health_check)
        setWorkerInfo(conn.worker_info)
        setLastError(conn.last_error)
      })
      .catch(() => toast.error('Não foi possível carregar a configuração Cloud.'))
      .finally(() => setLoaded(true))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const testConnection = async () => {
    setTesting(true)
    setStatus('CONNECTING')
    try {
      const result = await api.cloud.test({
        provider, worker_url: workerUrl, worker_port: workerPort,
        worker_token: workerToken || undefined,
      })
      setStatus(result.status)
      setLastHealthCheck(result.last_health_check)
      setWorkerInfo(result.worker_info)
      setLastError(result.error)
      if (result.status === 'ONLINE') toast.success('Worker respondeu — ligação OK.')
      else toast.error(result.error || `Worker devolveu ${result.status}.`)
    } catch (e) {
      setStatus('ERROR')
      setLastError(e.message)
      toast.error(`Falha ao testar a ligação: ${e.message}`)
    } finally {
      setTesting(false)
    }
  }

  const saveConnection = async () => {
    setSaving(true)
    try {
      await api.cloud.saveConnection({
        provider, worker_url: workerUrl || null, worker_port: workerPort || null, worker_name: workerName || null,
        worker_token: workerToken || undefined,
      })
      if (workerToken) setWorkerTokenSet(true)
      setWorkerToken('')
      toast.success('Configuração Cloud guardada.')
    } catch (e) {
      toast.error(`Falha ao guardar: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const s = STATUS_STYLE[status] || STATUS_STYLE.OFFLINE

  return (
    <div>
      <h2 style={{ marginBottom: 6 }}>Cloud</h2>
      <p style={{ fontSize: 13, color: 'var(--text-1)', marginBottom: 20, maxWidth: 600, lineHeight: 1.5 }}>
        Liga o JARVIS a um Worker remoto já criado (ex.: um Pod RunPod). Esta
        ligação é manual e totalmente editável — cria o Pod na consola do
        provider, cola aqui o endereço, testa e guarda. O JARVIS continua a
        funcionar normalmente em modo local/demo mesmo sem nenhum Worker
        ligado.
      </p>

      <div className="panel" style={{ padding: 20, maxWidth: 520, marginBottom: 20 }}>
        <label className="label">Provider</label>
        <select className="input" value={provider} onChange={(e) => setProvider(e.target.value)} style={{ marginBottom: 14 }}>
          {(providers.length ? providers : [{ id: 'runpod', name: 'RunPod' }]).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        <label className="label">Worker URL</label>
        <input
          className="input"
          placeholder="https://abc123-7872.proxy.runpod.net"
          value={workerUrl}
          onChange={(e) => setWorkerUrl(e.target.value)}
          style={{ marginBottom: 14 }}
        />

        <label className="label">Port</label>
        <input
          className="input"
          type="number"
          value={workerPort}
          onChange={(e) => setWorkerPort(parseInt(e.target.value || '0', 10))}
          style={{ marginBottom: 14 }}
        />
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginTop: -8, marginBottom: 14 }}>
          Só é usada quando o Worker URL não tem esquema próprio (ex.: IP direto na tua rede).
          URLs de proxy do provider (https://...) já trazem a porta embutida.
        </div>

        <label className="label">Worker Name (opcional)</label>
        <input
          className="input"
          placeholder="ex.: Pod LTX-2 principal"
          value={workerName}
          onChange={(e) => setWorkerName(e.target.value)}
          style={{ marginBottom: 14 }}
        />

        <label className="label">Worker Token (opcional)</label>
        <input
          className="input"
          type="password"
          placeholder={workerTokenSet ? '•••••••• (já guardado — deixa em branco para manter)' : 'JARVIS_WORKER_TOKEN do Worker, se estiver configurado'}
          value={workerToken}
          onChange={(e) => setWorkerToken(e.target.value)}
          style={{ marginBottom: 6 }}
        />
        <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 14 }}>
          Enviado como header X-Jarvis-Token em cada pedido ao Worker. Só é
          necessário se o Worker foi arrancado com JARVIS_WORKER_TOKEN
          definido. Nunca é reenviado ao browser depois de guardado — o
          campo aparece sempre vazio.
        </div>

        <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
          <button className="btn" onClick={testConnection} disabled={testing || !workerUrl}>
            {testing ? 'A testar…' : 'Testar Conexão'}
          </button>
          <button className="btn btn-primary" onClick={saveConnection} disabled={saving}>
            {saving ? 'A guardar…' : 'Salvar'}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
          <span className="dot" style={{ background: s.color, boxShadow: 'none' }} />
          <span style={{ fontWeight: 600, fontSize: 13, color: s.color }}>{s.label}</span>
          {lastHealthCheck && (
            <span style={{ fontSize: 11, color: 'var(--text-2)' }}>
              · último teste: {new Date(lastHealthCheck).toLocaleString('pt-PT')}
            </span>
          )}
        </div>

        {status === 'ERROR' || status === 'OFFLINE' ? (
          lastError && <div style={{ fontSize: 12, color: 'var(--danger)' }}>{lastError}</div>
        ) : null}

        {workerInfo && status === 'ONLINE' && (
          <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-1)' }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>Informação do Worker</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
              {Object.entries(workerInfo).map(([k, v]) => (
                <div key={k}>{k}: {typeof v === 'object' ? JSON.stringify(v) : String(v)}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="panel" style={{ padding: 16, maxWidth: 520, fontSize: 12, color: 'var(--text-1)', lineHeight: 1.6 }}>
        Assim que este Worker estiver <strong>ONLINE</strong> e guardado, os
        presets de Video/Image/Audio/Motion que apontam para um engine
        Wan2GP (wan, ltx2, hunyuan, flux, ace_step, ...) passam a gerar
        mesmo — o Studio envia o job para este endereço via
        <code style={{ padding: '1px 4px', background: 'var(--bg-2)', borderRadius: 4 }}>/run_task</code>.
        Sem Worker configurado, esses presets falham a validação com uma
        mensagem clara em vez de gerar em silêncio no modo demo.
      </div>
    </div>
  )
}
