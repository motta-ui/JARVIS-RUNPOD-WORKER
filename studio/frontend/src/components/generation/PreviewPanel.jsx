const STATE_LABEL = {
  EMPTY: 'Pronto para gerar',
  QUEUED: 'Na fila…',
  RUNNING: 'A iniciar…',
  PROCESSING: 'A processar…',
  DOWNLOADING: 'A transferir…',
  COMPLETED: 'Concluído',
  FAILED: 'Falhou',
  CANCELLED: 'Cancelado',
}

function mediaKind(url) {
  const ext = (url || '').split('.').pop()?.toLowerCase()
  if (['mp4', 'webm', 'mov'].includes(ext)) return 'video'
  if (['mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg'].includes(ext)) return 'audio'
  return 'image'
}

export default function PreviewPanel({ job, onCancel, onExtend }) {
  const status = job?.status || 'EMPTY'
  const progress = job?.progress ? Math.round(job.progress * 100) : 0
  const outputUrl = job?.output_url

  return (
    <div className="panel" style={{ padding: 20, minHeight: 340, display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 14 }}>Preview</div>

      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg-1)',
          borderRadius: 10,
          border: '1px solid var(--border)',
          padding: 24,
          textAlign: 'center',
        }}
      >
        {status === 'EMPTY' && (
          <div style={{ color: 'var(--text-2)', fontSize: 13 }}>
            Configura o modo, o prompt e os parâmetros, depois clica em Gerar.
          </div>
        )}

        {['QUEUED', 'RUNNING', 'PROCESSING', 'DOWNLOADING'].includes(status) && (
          <>
            <div
              style={{
                width: 34, height: 34, borderRadius: '50%',
                border: '3px solid var(--bg-2)', borderTopColor: 'var(--accent-cool)',
                animation: 'spin 0.9s linear infinite', marginBottom: 14,
              }}
            />
            <div style={{ fontSize: 13, marginBottom: 6 }}>{STATE_LABEL[status]}</div>
            <div style={{ width: '70%', height: 6, background: 'var(--bg-2)', borderRadius: 4, overflow: 'hidden', marginBottom: 6 }}>
              <div style={{ width: `${progress}%`, height: '100%', background: 'var(--accent-cool)', transition: 'width 0.2s' }} />
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{progress}%</div>
            {onCancel && (
              <button className="btn" style={{ marginTop: 14 }} onClick={onCancel}>Cancelar</button>
            )}
          </>
        )}

        {status === 'COMPLETED' && (
          <>
            {outputUrl && mediaKind(outputUrl) === 'video' && (
              <video src={outputUrl} controls style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 8, marginBottom: 10 }} />
            )}
            {outputUrl && mediaKind(outputUrl) === 'image' && (
              <img src={outputUrl} alt="output" style={{ maxWidth: '100%', maxHeight: 220, borderRadius: 8, marginBottom: 10 }} />
            )}
            {outputUrl && mediaKind(outputUrl) === 'audio' && (
              <audio src={outputUrl} controls style={{ width: '100%', marginBottom: 10 }} />
            )}
            <div style={{ fontSize: 13, color: 'var(--success)', marginBottom: 10 }}>✓ Geração concluída</div>
            <div style={{ fontSize: 12, color: 'var(--text-1)', marginBottom: 14 }}>
              {job.output_path ? job.output_path.split('/').pop() : 'output'}
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center' }}>
              <a
                className="btn btn-primary"
                href={outputUrl || undefined}
                download
                style={{ pointerEvents: outputUrl ? 'auto' : 'none', opacity: outputUrl ? 1 : 0.5 }}
              >
                Download
              </a>
              <button className="btn" disabled={!outputUrl} onClick={() => outputUrl && window.open(outputUrl, '_blank')}>
                Abrir
              </button>
              <a className="btn" href="/library/gallery">Galeria</a>
              {onExtend && <button className="btn" onClick={onExtend}>Estender</button>}
            </div>
          </>
        )}

        {status === 'FAILED' && (
          <div style={{ color: 'var(--danger)', fontSize: 13 }}>
            Falhou: {job?.error || 'erro desconhecido'}
          </div>
        )}

        {status === 'CANCELLED' && (
          <div style={{ color: 'var(--text-1)', fontSize: 13 }}>Geração cancelada.</div>
        )}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
