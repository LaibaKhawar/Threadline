'use client'

import { type QueryClient, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ReactNode, useSyncExternalStore } from 'react'

import { useToast } from '@/components/toast'
import { Badge } from '@/components/ui/primitives'
import { errorMessage, get } from '@/lib/api'
import type { ProjectBrief, ProjectSummary } from '@/lib/types'
import type { PersonListItem } from '@/lib/types-work'
import { cn, findSpan, fmtDate, relDays } from '@/lib/utils'

/** Every query key family that a Work-area correction can affect. Corrections are cheap to refetch locally. */
const WORK_KEYS = ['threads', 'thread', 'events', 'event', 'brief', 'projects', 'project', 'tasks', 'commitments', 'commitment', 'decisions', 'dashboard', 'source']

export function invalidateWork(qc: QueryClient) {
  return Promise.all(WORK_KEYS.map((k) => qc.invalidateQueries({ queryKey: [k] })))
}

/** Mutation wrapper: toasts success/failure and refreshes everything in the Work area. */
export function useWorkMutation<V, R = unknown>(fn: (v: V) => Promise<R>, success?: string | ((r: R, v: V) => string)) {
  const qc = useQueryClient()
  const toast = useToast()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, v) => {
      if (success) toast(typeof success === 'function' ? success(r, v) : success)
      return invalidateWork(qc)
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
}

/** The workspace clock (may be pinned in the demo). `status=none` keeps the response empty: we only need `now`. */
export function useNow(): string | undefined {
  const q = useQuery({ queryKey: ['tasks', 'clock'], queryFn: () => get<{ now: string }>('/api/tasks?status=none'), staleTime: 60_000 })
  return q.data?.now
}

export function useProjects() {
  return useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })
}

export function usePeople() {
  return useQuery({ queryKey: ['people'], queryFn: () => get<{ items: PersonListItem[] }>('/api/people'), staleTime: 60_000 })
}

/** Non-link project tag, safe to use inside other links/buttons (ProjectChip is itself a link). */
export function ProjectTag({ project, className }: { project: ProjectBrief | null | undefined; className?: string }) {
  if (!project) return null
  return (
    <span className={cn('inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] leading-4 text-ink-2', className)}>
      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: project.color ?? 'var(--ink-3)' }} aria-hidden />
      {project.name}
    </span>
  )
}

export function AwaitingBadge({ awaiting }: { awaiting: string | null | undefined }) {
  if (awaiting === 'me') return <Badge tone="warning" title="The last message was to you and asks for something">Awaiting your reply</Badge>
  if (awaiting === 'them') return <Badge tone="info" title="You sent the last message; no reply yet">Awaiting them</Badge>
  return null
}

/** Relative phrase ("yesterday", "3 days ago") or '' when relDays would fall back to an absolute date. */
export function relShort(iso: string | null | undefined, now: string | undefined) {
  const r = relDays(iso, now)
  return r.includes(',') ? '' : r
}

/** Due date with a relative phrase against the workspace clock, red when past. */
export function DueText({ due, now, done, className }: { due: string | null | undefined; now: string | undefined; done?: boolean; className?: string }) {
  if (!due) return <span className={cn('text-ink-3', className)}>No due date</span>
  const past = !done && now ? new Date(due).getTime() < new Date(now).getTime() : false
  const rel = relDays(due, now)
  const abs = fmtDate(due, { month: 'short', day: 'numeric' })
  return (
    <span className={cn('tabular-nums', past ? 'text-danger' : 'text-ink-3', className)} title={fmtDate(due)}>
      {rel.includes(',') || rel === fmtDate(due) ? `Due ${abs}` : `Due ${abs} · ${rel}`}
    </span>
  )
}

/** The health heuristic's signals with their weights: the "why" behind a project status. */
export function HealthSignals({ signals, compact }: { signals: { signal: string; weight: number }[]; compact?: boolean }) {
  const sorted = [...signals].sort((a, b) => b.weight - a.weight)
  return (
    <ul className={cn('space-y-1', compact && 'space-y-0.5')}>
      {sorted.map((s) => (
        <li key={s.signal} className="flex items-center gap-2 text-xs">
          <span className="relative h-1 w-8 shrink-0 overflow-hidden rounded-full bg-sunken" aria-hidden>
            <span className={cn('absolute inset-y-0 left-0 rounded-full', s.weight >= 0.5 ? 'bg-danger' : s.weight > 0 ? 'bg-warning' : 'bg-line-strong')} style={{ width: `${Math.min(1, s.weight) * 100}%` }} />
          </span>
          <span className={cn('min-w-0', s.weight > 0 ? 'text-ink-2' : 'text-ink-3')}>{s.signal}</span>
          {!compact && <span className="ml-auto shrink-0 tabular-nums text-ink-3">{s.weight > 0 ? `+${s.weight.toFixed(2)}` : '0'}</span>}
        </li>
      ))}
    </ul>
  )
}

export const HEALTH_EXPLAINER = 'Heuristic: overdue commitments, overdue or blocked tasks, inactivity and near deadlines add risk. 0.25 or more needs attention; 0.60 or more is at risk.'

/**
 * Renders text with several evidence spans marked. The `active` span gets the strong highlight
 * and is scrolled into view; the others get a subtle underline so you can see everything extracted.
 */
export function MarkedText({ text, spans, activeKey }: { text: string; spans: { key: string; span: string | null | undefined; title?: string }[]; activeKey?: string | null }) {
  const ranges = spans
    .map((s) => ({ ...s, r: findSpan(text, s.span) }))
    .filter((s): s is typeof s & { r: [number, number] } => !!s.r)
    .sort((a, b) => a.r[0] - b.r[0])
  const parts: ReactNode[] = []
  let pos = 0
  for (const s of ranges) {
    const [a, b] = s.r
    if (a < pos) continue
    if (a > pos) parts.push(text.slice(pos, a))
    const active = s.key === activeKey
    parts.push(
      <mark
        key={s.key}
        id={active ? `mark-${s.key}` : undefined}
        title={s.title}
        className={cn('rounded-sm text-inherit', active ? 'evidence' : 'bg-transparent underline decoration-uncertain/60 decoration-dotted underline-offset-4')}
      >
        {text.slice(a, b)}
      </mark>,
    )
    pos = b
  }
  parts.push(text.slice(pos))
  return <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-ink">{parts}</p>
}

export function SectionLabel({ children, count, action }: { children: ReactNode; count?: number; action?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">
        {children}
        {count !== undefined && <span className="ml-1.5 font-normal tabular-nums">{count}</span>}
      </h3>
      {action}
    </div>
  )
}

/** Small segmented toggle (a group of pressed/unpressed buttons). */
export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[]; label: string }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap rounded-md border border-line bg-surface p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn('inline-flex items-center gap-1 rounded px-2.5 py-1 text-xs', value === o.value ? 'bg-sunken font-medium text-ink' : 'text-ink-3 hover:text-ink')}
        >
          {o.label}
          {o.count !== undefined && <span className="tabular-nums text-ink-3">{o.count}</span>}
        </button>
      ))}
    </div>
  )
}

/** Date input value (YYYY-MM-DD, UTC) <-> API ISO timestamp (end of that day, UTC). */
export function toDateInput(iso: string | null | undefined) {
  return iso ? iso.slice(0, 10) : ''
}
export function fromDateInput(v: string) {
  return `${v}T23:59:59Z`
}

export function personName(p: { name: string; is_self: boolean } | null | undefined, fallback?: string | null) {
  if (!p) return fallback ?? 'Unknown'
  return p.is_self ? 'You' : p.name
}

/** True when the viewport matches the query (false during SSR). */
export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => window.matchMedia(query).matches,
    () => false,
  )
}
