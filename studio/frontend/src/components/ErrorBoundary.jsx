import { Component } from 'react'

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error('JARVIS UI error:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            height: '100vh', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: 14,
            background: 'var(--bg-0)', color: 'var(--text-0)', padding: 40, textAlign: 'center',
          }}
        >
          <div style={{ fontFamily: 'var(--font-display)', fontSize: 20, fontWeight: 600 }}>
            Algo correu mal na interface
          </div>
          <div style={{ color: 'var(--text-1)', fontSize: 13, maxWidth: 480 }}>
            {String(this.state.error?.message || this.state.error)}
          </div>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>
            Recarregar JARVIS
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
