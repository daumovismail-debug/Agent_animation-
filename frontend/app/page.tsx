'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'

interface Session {
  id: string
  name: string
  stage: string
  updated_at: string
}

const API = process.env.NEXT_PUBLIC_API_URL || ''

const STAGE_LABELS: Record<string, string> = {
  naming: 'Начало', char_count: 'Персонажи', char_build: 'Персонажи',
  chars_confirm: 'Персонажи', idea: 'Идея', scene_count: 'Сцены',
  total_duration: 'Длительность', duration_split: 'Разбивка',
  keyframes: 'Кадры', aspect: 'Формат', generating_script: 'Генерация',
  script_review: 'Сценарий', summary_review: 'Сводка',
  generating_prompts: 'Промты', prompt_review: 'Промты ✅', done: 'Готово ✅',
}

export default function Home() {
  const router = useRouter()
  const [sessions, setSessions] = useState<Session[]>([])
  const [search, setSearch] = useState('')
  const [newName, setNewName] = useState('')
  const [creating, setCreating] = useState(false)
  const [showInput, setShowInput] = useState(false)

  useEffect(() => { loadSessions() }, [])

  async function loadSessions() {
    try {
      const res = await fetch(`${API}/api/sessions`)
      if (res.ok) setSessions(await res.json())
    } catch {}
  }

  async function createSession() {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const res = await fetch(`${API}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newName.trim() })
      })
      const data = await res.json()
      router.push(`/chat/${data.id}`)
    } finally {
      setCreating(false)
    }
  }

  async function deleteSession(id: string, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm('Удалить сессию?')) return
    await fetch(`${API}/api/sessions/${id}`, { method: 'DELETE' })
    loadSessions()
  }

  const filtered = sessions.filter(s =>
    s.name.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg)' }}>
      {/* Шапка */}
      <div style={{
        background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        padding: '16px 24px', display: 'flex', alignItems: 'center', gap: '12px'
      }}>
        <span style={{ fontSize: '24px' }}>🎬</span>
        <span style={{ fontSize: '20px', fontWeight: 700 }}>PixarGen</span>
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowInput(v => !v)} style={{
          background: 'var(--accent)', color: '#fff', border: 'none',
          borderRadius: '8px', padding: '8px 18px', fontWeight: 600,
          cursor: 'pointer', fontSize: '14px'
        }}>+ Новый мультфильм</button>
      </div>

      <div style={{ maxWidth: '700px', margin: '0 auto', padding: '24px 16px' }}>

        {/* Поле создания */}
        {showInput && (
          <div style={{
            background: 'var(--surface)', border: '1px solid var(--border)',
            borderRadius: '12px', padding: '18px', marginBottom: '18px'
          }}>
            <p style={{ margin: '0 0 10px', fontWeight: 600, fontSize: '14px' }}>
              Название мультфильма:
            </p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                autoFocus
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && createSession()}
                placeholder="Приключения Арсена..."
                style={{
                  flex: 1, padding: '10px 14px', background: 'var(--bg)',
                  border: '1px solid var(--border)', borderRadius: '8px',
                  color: 'var(--text)', fontSize: '15px', outline: 'none'
                }}
              />
              <button onClick={createSession} disabled={creating || !newName.trim()} style={{
                background: 'var(--accent)', color: '#fff', border: 'none',
                borderRadius: '8px', padding: '10px 18px', fontWeight: 600,
                cursor: creating ? 'wait' : 'pointer'
              }}>{creating ? '...' : 'Создать'}</button>
              <button onClick={() => { setShowInput(false); setNewName('') }} style={{
                background: 'var(--surface2, #16213e)', border: '1px solid var(--border)',
                borderRadius: '8px', padding: '10px 12px', cursor: 'pointer', color: 'var(--text-muted)'
              }}>✕</button>
            </div>
          </div>
        )}

        {/* Поиск */}
        <div style={{ position: 'relative', marginBottom: '18px' }}>
          <span style={{
            position: 'absolute', left: '13px', top: '50%',
            transform: 'translateY(-50%)', fontSize: '15px'
          }}>🔍</span>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Поиск по названию..."
            style={{
              width: '100%', padding: '11px 12px 11px 38px',
              background: 'var(--surface)', border: '1px solid var(--border)',
              borderRadius: '10px', color: 'var(--text)', fontSize: '14px',
              outline: 'none', boxSizing: 'border-box'
            }}
          />
        </div>

        {/* Список */}
        {filtered.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
            <div style={{ fontSize: '48px', marginBottom: '12px' }}>🎬</div>
            <p>{sessions.length === 0 ? 'Нет мультфильмов. Создай первый!' : 'Ничего не найдено'}</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {filtered.map(s => (
              <div key={s.id} onClick={() => router.push(`/chat/${s.id}`)}
                style={{
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  borderRadius: '12px', padding: '14px 16px', cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: '12px',
                  transition: 'all 0.15s'
                }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent)'; e.currentTarget.style.transform = 'translateX(2px)' }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.transform = 'translateX(0)' }}
              >
                <span style={{ fontSize: '26px' }}>📁</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: '15px', marginBottom: '3px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {s.name}
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                    {STAGE_LABELS[s.stage] || s.stage}
                    &nbsp;·&nbsp;
                    {new Date(s.updated_at).toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' })}
                  </div>
                </div>
                <span style={{ color: 'var(--text-muted)', fontSize: '18px' }}>›</span>
                <button onClick={e => deleteSession(s.id, e)} style={{
                  background: 'transparent', border: 'none', color: 'var(--text-muted)',
                  cursor: 'pointer', fontSize: '15px', padding: '4px 6px', borderRadius: '6px'
                }} title="Удалить">🗑</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
