import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

const DAY = 86_400_000

export function fmtDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', year: 'numeric' }) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', { timeZone: 'UTC', ...opts })
}

export function fmtTime(iso: string | null | undefined) {
  if (!iso) return ''
  return new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' })
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return '—'
  return `${fmtDate(iso, { month: 'short', day: 'numeric' })}, ${fmtTime(iso)}`
}

/** Relative day phrase against a reference "now" (the workspace clock, which may be pinned in the demo). */
export function relDays(iso: string | null | undefined, now: string | Date | null | undefined): string {
  if (!iso) return ''
  const ref = now ? new Date(now) : new Date()
  const d = new Date(iso)
  const days = Math.round((startOfDayUTC(d) - startOfDayUTC(ref)) / DAY)
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  if (days === -1) return 'yesterday'
  if (days > 1 && days < 7) return `in ${days} days`
  if (days < -1 && days > -30) return `${-days} days ago`
  return fmtDate(iso)
}

function startOfDayUTC(d: Date) {
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
}

export function pct(x: number | null | undefined, digits = 0) {
  if (x === null || x === undefined || Number.isNaN(x)) return '—'
  return `${(x * 100).toFixed(digits)}%`
}

export function bytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function initials(name: string | null | undefined) {
  if (!name) return '?'
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? '')
    .join('')
}

/** Find the evidence span inside a longer text (case-insensitive, whitespace-tolerant). */
export function findSpan(text: string, span: string | null | undefined): [number, number] | null {
  if (!span) return null
  const norm = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
  const target = norm(span).slice(0, 120)
  if (!target) return null
  const idx = text.toLowerCase().indexOf(target)
  if (idx >= 0) return [idx, idx + span.length]
  // whitespace-insensitive fallback
  const flat = text.replace(/\s+/g, ' ')
  const j = flat.toLowerCase().indexOf(target)
  if (j < 0) return null
  let count = 0
  let start = -1
  for (let i = 0; i < text.length; i++) {
    if (count === j && start < 0) start = i
    if (!(/\s/.test(text[i]) && /\s/.test(text[i - 1] ?? ''))) count++
  }
  return start >= 0 ? [start, Math.min(text.length, start + span.length)] : null
}

export const SOURCE_LABEL: Record<string, string> = {
  email: 'Email',
  event: 'Meeting',
  document: 'Document',
  note: 'Note',
  commitment: 'Commitment',
  decision: 'Decision',
  task: 'Task',
  person: 'Person',
  project: 'Project',
  organization: 'Organization',
  topic: 'Topic',
  thread: 'Thread',
}
