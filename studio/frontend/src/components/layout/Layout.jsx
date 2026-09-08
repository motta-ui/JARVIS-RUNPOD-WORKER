import Sidebar from './Sidebar.jsx'
import Topbar from './Topbar.jsx'

export default function Layout({ children }) {
  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%' }}>
      <Sidebar />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <Topbar />
        <main style={{ flex: 1, overflowY: 'auto', padding: 24 }}>{children}</main>
      </div>
    </div>
  )
}
