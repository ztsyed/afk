import { useState, useEffect, useRef, useCallback } from 'react'

const WS_URL = import.meta.env.PROD
  ? `wss://${window.location.host}/ws/ui`
  : `ws://${window.location.host}/ws/ui`

const CONNECTION_STATES = {
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  RECONNECTING: 'reconnecting'
}

const SETUP_INSTRUCTIONS = `# AFK Setup for Claude Code

## 1. Download the hook script
curl -o ~/.claude/hooks/afk.py https://afk.ziasyed.com/hook/afk.py
chmod +x ~/.claude/hooks/afk.py

## 2. Add to ~/.claude/settings.json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "~/.claude/hooks/afk.py",
            "timeout": 3600
          }
        ]
      }
    ]
  }
}

## 3. Run Claude Code inside tmux
tmux new -s claude
claude

## Requirements
- Python 3.8+
- tmux (for response injection)
- websockets package (auto-installed)`

const DEBUG_INSTRUCTIONS = `# Debugging AFK

## Check Local Hook Debug Log
tail -f /tmp/afk-hook-debug.log

## Check Server Logs (k3s)
kubectl logs -n default -l app.kubernetes.io/name=afk -f

## Check Server Status
curl -s https://afk.ziasyed.com/api/health | jq
curl -s https://afk.ziasyed.com/api/logs | jq

## Common Issues

### SSL Certificate Error
If you see "CERTIFICATE_VERIFY_FAILED":
pip install certifi
# Then re-download the hook script

### Hook Not Triggering
1. Check ~/.claude/settings.json has the hook configured
2. Verify the hook script is executable: chmod +x ~/.claude/hooks/afk.py
3. Check /tmp/afk-hook-debug.log for errors

### TMUX Not Detected
The hook searches for Claude Code panes by:
1. TMUX/TMUX_PANE environment variables
2. Panes running processes with version patterns (e.g., 2.1.4)
3. Panes with Claude Code UI content

Ensure Claude Code is running inside tmux:
tmux new -s claude
claude

### Response Not Injecting
Check the debug log for "send_to_tmux" messages.
The response should show "send-keys succeeded".

### WebSocket Connection Issues
- Check browser console for errors
- Verify wss://afk.ziasyed.com/ws/hook is accessible
- Check /api/logs for active connections`

function CollapsibleSection({ title, content, isOpen, onToggle }) {
  return (
    <div className="border-b border-terminal-border">
      <button
        onClick={onToggle}
        className="w-full p-3 flex items-center justify-between text-left hover:bg-terminal-border/20 transition-colors"
      >
        <span className="text-sm text-terminal-muted">
          {isOpen ? '[-]' : '[+]'} {title}
        </span>
        <svg
          className={`w-4 h-4 text-terminal-muted transition-transform ${isOpen ? 'rotate-180' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {isOpen && (
        <div className="p-4 bg-terminal-bg border-t border-terminal-border">
          <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono overflow-x-auto">
            {content}
          </pre>
        </div>
      )}
    </div>
  )
}

function SetupInstructions({ isOpen, onToggle }) {
  return <CollapsibleSection title="Setup Instructions" content={SETUP_INSTRUCTIONS} isOpen={isOpen} onToggle={onToggle} />
}

function DebugInstructions({ isOpen, onToggle }) {
  return <CollapsibleSection title="Debugging" content={DEBUG_INSTRUCTIONS} isOpen={isOpen} onToggle={onToggle} />
}

function timeAgo(dateString) {
  const date = new Date(dateString)
  const now = new Date()
  const seconds = Math.floor((now - date) / 1000)

  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

function StatusIndicator({ status }) {
  const config = {
    [CONNECTION_STATES.CONNECTED]: { label: 'LIVE', class: 'text-terminal-green' },
    [CONNECTION_STATES.CONNECTING]: { label: 'CONNECTING', class: 'text-terminal-amber' },
    [CONNECTION_STATES.RECONNECTING]: { label: 'RECONNECTING', class: 'text-terminal-amber' },
    [CONNECTION_STATES.DISCONNECTED]: { label: 'OFFLINE', class: 'text-terminal-red' }
  }
  const { label, class: className } = config[status] || config[CONNECTION_STATES.DISCONNECTED]

  return (
    <div className={`flex items-center gap-2 text-xs ${className}`}>
      <span className={`status-dot ${status === CONNECTION_STATES.CONNECTED ? 'status-connected' : status === CONNECTION_STATES.DISCONNECTED ? 'status-disconnected' : 'status-pending'}`} />
      {label}
    </div>
  )
}

function SessionCard({ session, onClick, onDismiss }) {
  const isDisconnected = session.status === 'disconnected'

  const handleDismiss = (e) => {
    e.stopPropagation()
    onDismiss(session.id)
  }

  return (
    <div
      className={`card-terminal w-full text-left transition-colors relative ${
        isDisconnected
          ? 'opacity-50'
          : 'hover:border-terminal-green cursor-pointer'
      }`}
    >
      <button
        onClick={handleDismiss}
        className="absolute top-2 right-2 p-1 text-terminal-muted hover:text-terminal-red transition-colors z-10"
        title="Dismiss"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      <button
        onClick={onClick}
        disabled={isDisconnected}
        className="w-full text-left"
      >
        <div className="flex items-start justify-between gap-3 pr-6">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`status-dot flex-shrink-0 ${isDisconnected ? 'status-disconnected' : 'status-pending'}`} />
            <span className="text-terminal-green font-medium truncate">
              {session.machine_name}/{session.project_name}
            </span>
          </div>
          <span className="text-terminal-muted text-xs flex-shrink-0">
            {timeAgo(session.created_at)}
          </span>
        </div>

        <div className="mt-2 flex items-start gap-2">
          <span className="text-xs flex-shrink-0">
            {session.notification_type === 'permission_prompt' ? '🔐' : '💬'}
          </span>
          <p className="text-sm text-gray-300 line-clamp-2">
            {session.notification}
          </p>
        </div>

        {session.context_tail && (
          <div className="mt-2 p-2 bg-terminal-bg text-xs text-terminal-muted font-mono overflow-hidden">
            <pre className="whitespace-pre-wrap line-clamp-3">{session.context_tail}</pre>
          </div>
        )}

        {isDisconnected && (
          <div className="mt-2 text-xs text-terminal-red">
            Connection lost
          </div>
        )}
      </button>
    </div>
  )
}

function SessionDetail({ session, onBack, onRespond, sending }) {
  const [customResponse, setCustomResponse] = useState('')
  const textareaRef = useRef(null)
  const isDisconnected = session.status === 'disconnected'
  const isPermissionPrompt = session.notification_type === 'permission_prompt'

  // Different quick responses based on prompt type
  const quickResponses = isPermissionPrompt
    ? [
        { label: 'Yes', value: 'yes' },
        { label: 'No', value: 'no' },
        { label: 'Continue', value: 'continue' },
        { label: 'Stop', value: 'stop' }
      ]
    : [] // No quick responses for text input prompts

  const handleQuickResponse = (value) => {
    if (!isDisconnected && !sending) {
      onRespond(value)
    }
  }

  const handleCustomSubmit = (e) => {
    e.preventDefault()
    if (customResponse.trim() && !isDisconnected && !sending) {
      onRespond(customResponse.trim())
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 p-4 border-b border-terminal-border">
        <button
          onClick={onBack}
          className="text-terminal-muted hover:text-terminal-green transition-colors"
        >
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className={`status-dot ${isDisconnected ? 'status-disconnected' : 'status-pending'}`} />
            <span className="text-terminal-green font-medium truncate">
              {session.machine_name}/{session.project_name}
            </span>
          </div>
          <div className="text-xs text-terminal-muted truncate">
            {session.working_dir}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {isDisconnected && (
          <div className="bg-terminal-red/10 border border-terminal-red p-3 text-sm text-terminal-red">
            Connection lost. Cannot respond to this session.
          </div>
        )}

        <div>
          <div className="text-xs text-terminal-muted uppercase tracking-wider mb-2">
            Notification
          </div>
          <div className="text-gray-100">
            {session.notification}
          </div>
        </div>

        {session.context_tail && (
          <div>
            <div className="text-xs text-terminal-muted uppercase tracking-wider mb-2">
              Context
            </div>
            <div className="bg-terminal-bg border border-terminal-border p-3 overflow-x-auto">
              <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono">
                {session.context_tail}
              </pre>
            </div>
          </div>
        )}
      </div>

      {/* Response section */}
      <div className="border-t border-terminal-border p-4 space-y-4">
        {/* Prompt type indicator */}
        <div className="text-xs text-terminal-muted">
          {isPermissionPrompt ? '🔐 Permission Request' : '💬 Text Input'}
        </div>

        {/* Quick responses - only for permission prompts */}
        {quickResponses.length > 0 && (
          <div className="grid grid-cols-4 gap-2">
            {quickResponses.map(({ label, value }) => (
              <button
                key={value}
                onClick={() => handleQuickResponse(value)}
                disabled={isDisconnected || sending}
                className="btn-terminal text-xs py-2"
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {/* Custom response */}
        <form onSubmit={handleCustomSubmit} className="space-y-2">
          <textarea
            ref={textareaRef}
            value={customResponse}
            onChange={(e) => setCustomResponse(e.target.value)}
            placeholder={isPermissionPrompt ? "Type custom response..." : "Type your response..."}
            disabled={isDisconnected || sending}
            rows={isPermissionPrompt ? 2 : 3}
            className="input-terminal"
            autoFocus={!isPermissionPrompt}
          />
          <button
            type="submit"
            disabled={!customResponse.trim() || isDisconnected || sending}
            className="btn-terminal w-full"
          >
            {sending ? 'SENDING...' : 'SEND'}
          </button>
        </form>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 text-center">
      <div className="text-6xl mb-4">
        <span className="text-terminal-green">_</span>
      </div>
      <div className="text-terminal-muted mb-2">No pending sessions</div>
      <div className="text-xs text-terminal-muted">
        Claude Code instances will appear here when they need input
      </div>
    </div>
  )
}

export default function App() {
  const [sessions, setSessions] = useState([])
  const [selectedSession, setSelectedSession] = useState(null)
  const [connectionStatus, setConnectionStatus] = useState(CONNECTION_STATES.DISCONNECTED)
  const [sending, setSending] = useState(false)
  const [showSetup, setShowSetup] = useState(false)
  const [showDebug, setShowDebug] = useState(false)
  const wsRef = useRef(null)
  const reconnectTimeoutRef = useRef(null)
  const pingIntervalRef = useRef(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    // Already connected or connecting
    if (wsRef.current?.readyState === WebSocket.OPEN) return
    if (wsRef.current?.readyState === WebSocket.CONNECTING) return

    setConnectionStatus(CONNECTION_STATES.CONNECTING)

    try {
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        // Check if this socket is still the current one and component is mounted
        if (!mountedRef.current || wsRef.current !== ws) {
          ws.close()
          return
        }
        setConnectionStatus(CONNECTION_STATES.CONNECTED)
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 25000)
      }

      ws.onmessage = (event) => {
        if (!mountedRef.current) return
        const data = JSON.parse(event.data)

        switch (data.type) {
          case 'init':
            setSessions(data.sessions || [])
            break
          case 'new_session':
            setSessions(prev => [data.session, ...prev])
            break
          case 'session_responded':
            setSessions(prev => prev.filter(s => s.id !== data.session_id))
            if (selectedSession?.id === data.session_id) {
              setSelectedSession(null)
            }
            break
          case 'session_disconnected':
            setSessions(prev => prev.map(s =>
              s.id === data.session_id ? { ...s, status: 'disconnected' } : s
            ))
            if (selectedSession?.id === data.session_id) {
              setSelectedSession(prev => prev ? { ...prev, status: 'disconnected' } : null)
            }
            break
          case 'session_dismissed':
            setSessions(prev => prev.filter(s => s.id !== data.session_id))
            if (selectedSession?.id === data.session_id) {
              setSelectedSession(null)
            }
            break
          case 'ping':
            ws.send(JSON.stringify({ type: 'pong' }))
            break
          case 'pong':
            break
          case 'error':
            console.error('Server error:', data.message)
            break
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setConnectionStatus(CONNECTION_STATES.DISCONNECTED)
        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
        }
        reconnectTimeoutRef.current = setTimeout(() => {
          if (!mountedRef.current) return
          setConnectionStatus(CONNECTION_STATES.RECONNECTING)
          connect()
        }, 3000)
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
      }
    } catch (error) {
      console.error('Failed to connect:', error)
      setConnectionStatus(CONNECTION_STATES.DISCONNECTED)
    }
  }, [selectedSession])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      // Only close if actually connected (not during StrictMode's first unmount)
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.close()
      }
    }
  }, [connect])

  const handleRespond = useCallback((response) => {
    if (!selectedSession || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    setSending(true)
    wsRef.current.send(JSON.stringify({
      type: 'respond',
      session_id: selectedSession.id,
      response
    }))

    setTimeout(() => {
      setSending(false)
      setSelectedSession(null)
    }, 500)
  }, [selectedSession])

  const handleDismiss = useCallback((sessionId) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return

    wsRef.current.send(JSON.stringify({
      type: 'dismiss',
      session_id: sessionId
    }))

    // Optimistically remove from UI
    setSessions(prev => prev.filter(s => s.id !== sessionId))
    if (selectedSession?.id === sessionId) {
      setSelectedSession(null)
    }
  }, [selectedSession])

  const pendingCount = sessions.filter(s => s.status === 'pending').length

  return (
    <div className="h-screen h-[100dvh] flex flex-col bg-terminal-bg scanline">
      {/* Header */}
      {!selectedSession && (
        <header className="flex items-center justify-between p-4 border-b border-terminal-border">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold text-terminal-green tracking-wider">
              AFK<span className="cursor-blink"></span>
            </h1>
            {pendingCount > 0 && (
              <span className="bg-terminal-amber text-terminal-bg text-xs font-bold px-2 py-0.5">
                {pendingCount}
              </span>
            )}
          </div>
          <StatusIndicator status={connectionStatus} />
        </header>
      )}

      {/* Setup & Debug Instructions */}
      {!selectedSession && (
        <>
          <SetupInstructions isOpen={showSetup} onToggle={() => setShowSetup(!showSetup)} />
          <DebugInstructions isOpen={showDebug} onToggle={() => setShowDebug(!showDebug)} />
        </>
      )}

      {/* Main content */}
      <main className="flex-1 overflow-hidden">
        {selectedSession ? (
          <SessionDetail
            session={selectedSession}
            onBack={() => setSelectedSession(null)}
            onRespond={handleRespond}
            sending={sending}
          />
        ) : sessions.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="h-full overflow-y-auto p-4 space-y-3">
            {sessions.map(session => (
              <SessionCard
                key={session.id}
                session={session}
                onClick={() => setSelectedSession(session)}
                onDismiss={handleDismiss}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
