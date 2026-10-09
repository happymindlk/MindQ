import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { ThemeProvider } from './context/ThemeProvider.jsx'

// Safety net: if anything throws during render, show a message instead of a
// blank white screen.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('App crashed during render:', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: '#020617', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif', padding: '2rem',
        }}>
          <div style={{ maxWidth: 520 }}>
            <h1 style={{ fontSize: '1.25rem', marginBottom: '0.5rem' }}>Something went wrong</h1>
            <p style={{ color: '#94a3b8', marginBottom: '1rem' }}>
              The app failed to load. This is often a missing configuration value.
            </p>
            <pre style={{
              whiteSpace: 'pre-wrap', background: '#0f172a', border: '1px solid #1e293b',
              borderRadius: 8, padding: '0.75rem', fontSize: '0.8rem', color: '#fca5a5',
            }}>{String(this.state.error?.message || this.state.error)}</pre>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <ThemeProvider>
        <App />
      </ThemeProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
