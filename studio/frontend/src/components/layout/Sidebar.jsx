import { NavLink } from 'react-router-dom'
import { useStudio } from '../../store/useStore.jsx'

const NAV = [
  {
    section: 'CRIAR',
    items: [
      { to: '/create/image', label: 'Image' },
      { to: '/create/video', label: 'Video' },
      { to: '/create/audio', label: 'Audio' },
      { to: '/create/motion', label: 'Motion' },
    ],
  },
  {
    section: 'BIBLIOTECA',
    items: [
      { to: '/library/assets', label: 'Assets' },
      { to: '/library/gallery', label: 'Gallery' },
      { to: '/library/projects', label: 'Projects' },
      { to: '/library/loras', label: 'LoRAs' },
    ],
  },
  {
    section: 'SISTEMA',
    items: [
      { to: '/system/settings', label: 'Settings' },
      { to: '/system/engines', label: 'Engines' },
      { to: '/system/cloud', label: 'Cloud' },
      { to: '/system/updates', label: 'Updates' },
    ],
  },
]

export default function Sidebar() {
  const { online } = useStudio()

  return (
    <aside
      style={{
        width: 'var(--sidebar-w)',
        minWidth: 'var(--sidebar-w)',
        height: '100vh',
        background: 'var(--bg-1)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 14px',
      }}
    >
      <div style={{ padding: '0 8px 24px 8px' }}>
        <div style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 700, color: 'var(--text-0)' }}>
          JARVIS
        </div>
        <div style={{ fontSize: 11, letterSpacing: '0.08em', color: 'var(--accent-cool)', fontWeight: 600 }}>
          AI STUDIO
        </div>
      </div>

      <nav style={{ flex: 1, overflowY: 'auto' }}>
        {NAV.map((group) => (
          <div key={group.section} style={{ marginBottom: 22 }}>
            <div
              style={{
                fontSize: 11,
                color: 'var(--text-2)',
                fontWeight: 600,
                letterSpacing: '0.06em',
                padding: '0 10px 8px 10px',
              }}
            >
              {group.section}
            </div>
            {group.items.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                style={({ isActive }) => ({
                  display: 'block',
                  padding: '8px 10px',
                  borderRadius: 8,
                  fontSize: 13.5,
                  marginBottom: 2,
                  color: isActive ? 'var(--text-0)' : 'var(--text-1)',
                  background: isActive ? 'var(--accent-cool-dim)' : 'transparent',
                  borderLeft: isActive ? '2px solid var(--accent-cool)' : '2px solid transparent',
                })}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div
        style={{
          padding: '10px 10px',
          borderTop: '1px solid var(--border)',
          fontSize: 12,
          color: 'var(--text-1)',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <span className="dot" style={{ background: online ? 'var(--success)' : 'var(--danger)', boxShadow: 'none' }} />
        Sistema {online ? 'Online' : 'Offline'}
      </div>
    </aside>
  )
}
