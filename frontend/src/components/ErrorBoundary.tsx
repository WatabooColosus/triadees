import { Component, ErrorInfo, ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ color: '#ef4444', fontSize: 16, marginBottom: 12 }}>Error en Cabina Viva</div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16, fontFamily: 'monospace' }}>
            {this.state.error.message}
          </div>
          <button onClick={() => this.setState({ error: null })} style={{
            background: 'var(--accent)', color: '#fff', border: 'none',
            borderRadius: 8, padding: '8px 20px', cursor: 'pointer', fontWeight: 600,
          }}>
            Reintentar
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
