'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'

interface Button { label: string; value: string }
interface ChatMessage {
  role: 'user' | 'agent'
  text: string
  buttons?: Button[]
}

const API = process.env.NEXT_PUBLIC_API_URL || ''
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || ''

function getWsUrl(sessionId: string) {
  if (WS_URL) return `${WS_URL}/ws/${sessionId}`
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}/ws/${sessionId}`
}

// Простой рендер текста: **bold**, *italic*, ```code```
function renderText(text: string) {
  const lines = text.split('\n')
  return lines.map((line, i) => {
    const isCode = line.startsWith('```') || line.endsWith('```')
    if (isCode) return null
    // Bold
    line = line.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Italic
    line = line.replace(/\*(.*?)\*/g, '<em>$1</em>')
    // Inline code
    line = line.replace(/`(.*?)`/g, '<code style="background:#1a1a2e;padding:2px 6px;border-radius:4px;font-family:monospace">$1</code>')
    return <p key={i} style={{ margin: '2px 0' }} dangerouslySetInnerHTML={{ __html: line || '&nbsp;' }} />
  })
}

function CodeBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const content = text.replace(/^```\w*\n?/, '').replace(/```$/, '').trim()

  function copy() {
    navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div style={{ position: 'relative', margin: '6px 0' }}>
      <pre style={{
        background: '#0f0f1a', border: '1px solid var(--border)',
        borderRadius: '8px', padding: '12px', fontSize: '12px',
        fontFamily: 'monospace', color: '#a8ff78', overflowX: 'auto'
      }}>{content}</pre>
      <button onClick={copy} style={{
        position: 'absolute', top: '8px', right: '8px',
        background: 'var(--surface)', border: '1px solid var(--border)',
        borderRadius: '5px', padding: '3px 8px', cursor: 'pointer',
        fontSize: '11px', color: 'var(--text-muted)'
      }}>{copied ? '✅' : '📋'}</button>
    </div>
  )
}

function MessageBubble({ msg }: { msg: ChatMessage; onButton?: (v: string) => void }) {
  const isAgent = msg.role === 'agent'
  const blocks = msg.text.split(/(```[\s\S]*?```)/g)

  return (
    <div style={{
      display: 'flex', justifyContent: isAgent ? 'flex-start' : 'flex-end',
      marginBottom: '12px', alignItems: 'flex-end', gap: '8px'
    }}>
      {isAgent && <span style={{ fontSize: '24px', flexShrink: 0 }}>🤖</span>}
      <div style={{ maxWidth: '78%' }}>
        <div style={{
          background: isAgent ? 'var(--surface)' : 'var(--accent)',
          border: isAgent ? '1px solid var(--border)' : 'none',
          borderRadius: isAgent ? '4px 14px 14px 14px' : '14px 14px 4px 14px',
          padding: '12px 15px', fontSize: '14px', lineHeight: '1.55',
          color: 'var(--text)'
        }}>
          {blocks.map((block, i) =>
            block.startsWith('```')
              ? <CodeBlock key={i} text={block} />
              : <div key={i}>{renderText(block)}</div>
          )}
        </div>
      </div>
      {!isAgent && <span style={{ fontSize: '20px', flexShrink: 0 }}>👤</span>}
    </div>
  )
}

export default function ChatPage() {
  const router = useRouter()
  const params = useParams()
  const sessionId = params.id as string

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pendingButtons, setPendingButtons] = useState<Button[] | null>(null)
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [typing, setTyping] = useState(false)
  const [sessionName, setSessionName] = useState('')
  const [showDownload, setShowDownload] = useState(false)

  const wsRef = useRef<WebSocket | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API}/api/sessions/${sessionId}`)
      .then(r => r.json())
      .then(d => setSessionName(d.name || ''))
      .catch(() => {})
  }, [sessionId])

  const connect = useCallback(() => {
    const ws = new WebSocket(getWsUrl(sessionId))
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => { setConnected(false); setTimeout(connect, 3000) }

    ws.onmessage = (e) => {
      const data = JSON.parse(e.data)

      if (data.type === 'typing') { setTyping(true); return }

      setTyping(false)

      if (data.type === 'history') {
        setMessages(prev => [...prev, { role: data.role, text: data.text }])
        return
      }

      if (data.type === 'message') {
        if (data.role === 'agent') {
          setMessages(prev => [...prev, {
            role: 'agent', text: data.text,
            buttons: data.buttons || undefined
          }])
          if (data.buttons) {
            setPendingButtons(data.buttons)
            // Показываем кнопку скачивания если агент отдал промты
            if (data.text.includes('Все промты готовы') || data.text.includes('prompt_review')) {
              setShowDownload(true)
            }
          } else {
            setPendingButtons(null)
          }
        }
      }
    }
  }, [sessionId])

  useEffect(() => { connect(); return () => wsRef.current?.close() }, [connect])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, typing])

  function send(text: string, displayText?: string) {
    if (!text.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return
    setMessages(prev => [...prev, { role: 'user', text: displayText || text }])
    setPendingButtons(null)
    wsRef.current.send(JSON.stringify({ text }))
    setInput('')
  }

  function clickButton(btn: Button) {
    send(btn.value, btn.label)
  }

  return (
    <div style={{
      height: '100vh', display: 'flex', flexDirection: 'column',
      background: 'var(--bg)'
    }}>
      {/* Шапка */}
      <div style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '14px 18px', display: 'flex', alignItems: 'center', gap: '12px',
        flexShrink: 0
      }}>
        <button onClick={() => router.push('/')} style={{
          background: 'var(--surface)', border: '1px solid var(--border)',
          borderRadius: '8px', padding: '6px 12px', cursor: 'pointer',
          color: 'var(--text)', fontSize: '18px'
        }}>←</button>
        <span style={{ fontSize: '22px' }}>🎬</span>
        <span style={{ fontWeight: 600, fontSize: '16px', flex: 1 }}>
          {sessionName || 'Мультфильм'}
        </span>
        {showDownload && (
          <div style={{ display: 'flex', gap: '6px' }}>
            <a href={`${API}/api/sessions/${sessionId}/download/md`}
              style={{ background: 'var(--accent)', color: '#fff', borderRadius: '7px', padding: '5px 10px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}>
              📄 MD
            </a>
            <a href={`${API}/api/sessions/${sessionId}/download/json`}
              style={{ background: '#0f3460', color: '#fff', borderRadius: '7px', padding: '5px 10px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}>
              📦 JSON
            </a>
          </div>
        )}
        <span style={{
          width: '8px', height: '8px', borderRadius: '50%',
          background: connected ? '#4ade80' : '#f87171', flexShrink: 0
        }} title={connected ? 'Подключено' : 'Нет соединения'} />
      </div>

      {/* Сообщения */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '20px 16px',
        display: 'flex', flexDirection: 'column'
      }}>
        <div style={{ maxWidth: '720px', width: '100%', margin: '0 auto' }}>
          {messages.map((m, i) => (
            <MessageBubble key={i} msg={m} />
          ))}

          {typing && (
            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', alignItems: 'center' }}>
              <span style={{ fontSize: '24px' }}>🤖</span>
              <div style={{
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: '14px', padding: '12px 16px'
              }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>печатает...</span>
              </div>
            </div>
          )}

          {/* Кнопки */}
          {pendingButtons && pendingButtons.length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: '16px', marginLeft: '36px' }}>
              {pendingButtons.map((btn, i) => (
                <button key={i} onClick={() => clickButton(btn)} style={{
                  background: 'var(--surface)', border: '1px solid var(--accent)',
                  color: 'var(--text)', borderRadius: '20px',
                  padding: '8px 16px', cursor: 'pointer', fontSize: '13px',
                  fontWeight: 500, transition: 'all 0.15s'
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = 'var(--accent)' }}
                  onMouseLeave={e => { e.currentTarget.style.background = 'var(--surface)' }}
                >
                  {btn.label}
                </button>
              ))}
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Поле ввода */}
      <div style={{
        background: 'var(--surface)', borderTop: '1px solid var(--border)',
        padding: '14px 16px', flexShrink: 0
      }}>
        <div style={{ maxWidth: '720px', margin: '0 auto', display: 'flex', gap: '10px' }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
            }}
            placeholder="Напиши сообщение... (Enter — отправить, Shift+Enter — новая строка)"
            rows={1}
            style={{
              flex: 1, padding: '11px 14px', background: 'var(--bg)',
              border: '1px solid var(--border)', borderRadius: '10px',
              color: 'var(--text)', fontSize: '14px', outline: 'none',
              resize: 'none', fontFamily: 'system-ui, sans-serif',
              lineHeight: '1.5'
            }}
          />
          <button onClick={() => send(input)} disabled={!input.trim() || !connected} style={{
            background: input.trim() && connected ? 'var(--accent)' : 'var(--border)',
            border: 'none', borderRadius: '10px', padding: '0 18px',
            cursor: input.trim() && connected ? 'pointer' : 'not-allowed',
            color: '#fff', fontSize: '18px', transition: 'background 0.15s', flexShrink: 0
          }}>➤</button>
        </div>
      </div>
    </div>
  )
}
