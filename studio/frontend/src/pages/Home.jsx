import { useNavigate } from 'react-router-dom'

const SHORTCUTS = [
  { to: '/create/image', title: 'Image', desc: 'Gere imagens a partir de texto ou referências.' },
  { to: '/create/video', title: 'Video', desc: 'Texto, imagem, end-frame e controlo de vídeo.' },
  { to: '/library/projects', title: 'Projects', desc: 'Organize os teus trabalhos por projeto.' },
]

export default function Home() {
  const navigate = useNavigate()

  return (
    <div style={{ maxWidth: 920, margin: '40px auto' }}>
      <div className="panel" style={{ padding: '48px 40px', marginBottom: 28 }}>
        <div style={{ color: 'var(--accent-warm)', fontSize: 12, fontWeight: 600, letterSpacing: '0.06em', marginBottom: 10 }}>
          JARVIS AI STUDIO
        </div>
        <h1 style={{ fontSize: 32, marginBottom: 12 }}>Bem-vindo ao JARVIS AI STUDIO</h1>
        <p style={{ color: 'var(--text-1)', fontSize: 15, maxWidth: 520, lineHeight: 1.6 }}>
          Crie imagens, vídeos e áudio com inteligência artificial.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {SHORTCUTS.map((s) => (
          <button
            key={s.to}
            className="panel"
            onClick={() => navigate(s.to)}
            style={{
              textAlign: 'left',
              padding: 22,
              border: '1px solid var(--border)',
              color: 'var(--text-0)',
            }}
          >
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600, marginBottom: 6 }}>
              {s.title}
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-1)', lineHeight: 1.5 }}>{s.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
