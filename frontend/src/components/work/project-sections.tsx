'use client'

import { ArrowRight, FileText, NotebookPen, Paperclip } from 'lucide-react'
import Link from 'next/link'

import { Confidence, EvidenceChip, StatusBadge } from '@/components/ui/ai'
import { Badge, EmptyState } from '@/components/ui/primitives'
import type { ProjectFact, ProjectDetail, ProjectTimelineItem } from '@/lib/types-work'
import { SOURCE_LABEL, bytes, cn, fmtDate, fmtTime } from '@/lib/utils'

import { relShort } from './shared'

function attrLabel(attr: string) {
  const [kind, name] = attr.split(':')
  const k = kind === 'deadline' ? 'Deadline' : kind === 'decision' ? 'Decision' : kind.charAt(0).toUpperCase() + kind.slice(1)
  return name ? `${k}: ${name.replace(/_/g, ' ')}` : k
}

function factValue(f: ProjectFact) {
  return /^\d{4}-\d{2}-\d{2}$/.test(f.value) ? fmtDate(`${f.value}T12:00:00Z`) : f.value
}

/** Temporal facts grouped by attribute: superseded values struck through, with their validity windows. */
export function FactsHistory({ facts }: { facts: ProjectFact[] }) {
  if (facts.length === 0) return <EmptyState title="No tracked facts yet" description="Deadlines and decisions mentioned about this project appear here, with their history." />
  const groups = new Map<string, ProjectFact[]>()
  for (const f of facts) groups.set(f.attribute, [...(groups.get(f.attribute) ?? []), f])
  return (
    <ul className="divide-y divide-line">
      {[...groups.entries()].map(([attr, list]) => {
        const sorted = [...list].sort((a, b) => (a.valid_from ?? '').localeCompare(b.valid_from ?? ''))
        return (
          <li key={attr} className="px-4 py-3">
            <h3 className="text-xs font-semibold text-ink-2">{attrLabel(attr)}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm">
              {sorted.map((f, i) => (
                <span key={`${f.value}-${f.valid_from}`} className="inline-flex items-center gap-1.5">
                  {i > 0 && <ArrowRight className="h-3 w-3 text-ink-3" aria-label="changed to" />}
                  <span className={cn(f.status === 'superseded' ? 'text-ink-3 line-through' : 'font-medium text-ink')}>{factValue(f)}</span>
                </span>
              ))}
            </div>
            <ol className="mt-2 space-y-1.5">
              {sorted.map((f) => (
                <li key={`${f.value}-${f.valid_from}-row`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                  <Badge tone={f.status === 'active' ? 'success' : 'neutral'}>{f.status === 'active' ? 'Current' : 'Superseded'}</Badge>
                  <span className={cn('tabular-nums', f.status === 'superseded' ? 'text-ink-3' : 'text-ink-2')}>
                    {fmtDate(f.valid_from)} – {f.valid_to ? fmtDate(f.valid_to) : 'now'}
                  </span>
                  <span className="min-w-0 text-ink-3">{f.content}</span>
                  {f.source.id && <EvidenceChip type={f.source.type} id={f.source.id} span={f.source.span} label={SOURCE_LABEL[f.source.type ?? ''] ?? 'Source'} />}
                </li>
              ))}
            </ol>
          </li>
        )
      })}
    </ul>
  )
}

const TL_TONE: Record<string, 'danger' | 'success' | 'warning' | 'info' | 'neutral' | 'accent'> = {
  decision: 'accent',
  deadline_change: 'warning',
  commitment_fulfilled: 'success',
  commitment_cancelled: 'neutral',
  commitment: 'info',
}

function tlHref(t: ProjectTimelineItem): string | null {
  const { type, id } = t.ref
  if (!type || !id) return null
  if (type === 'commitment') return `/commitments?id=${id}`
  if (type === 'decision') return '/decisions'
  if (type === 'event') return `/calendar?event=${id}`
  if (type === 'task') return '/tasks'
  return null
}

export function ProjectTimeline({ items, now }: { items: ProjectTimelineItem[]; now: string | undefined }) {
  if (items.length === 0) return <EmptyState title="No activity yet" />
  return (
    <ol className="relative ml-4 border-l border-line py-2">
      {items.map((t, i) => {
        const href = tlHref(t)
        const isSource = t.ref.type && ['email', 'event', 'document', 'note'].includes(t.ref.type)
        return (
          <li key={`${t.ref.id}-${i}`} className="relative py-2 pl-5 pr-4">
            <span className="absolute -left-[4.5px] top-[14px] h-2 w-2 rounded-full border border-line-strong bg-surface" aria-hidden />
            <div className="flex items-start gap-3 text-xs">
              <time className="w-20 shrink-0 pt-0.5 tabular-nums text-ink-3" dateTime={t.occurred_at} title={fmtDate(t.occurred_at)}>
                {relShort(t.occurred_at, now) || fmtDate(t.occurred_at, { month: 'short', day: 'numeric' })}
              </time>
              <div className="min-w-0 flex-1 leading-6">
                <Badge tone={TL_TONE[t.kind] ?? 'neutral'} className="mr-2 align-[1px]">
                  {t.kind.replace(/_/g, ' ')}
                </Badge>
                {href ? (
                  <Link href={href} className="text-sm text-ink hover:text-accent">
                    {t.title}
                  </Link>
                ) : (
                  <span className="text-sm text-ink">{t.title}</span>
                )}
                {isSource && <EvidenceChip type={t.ref.type} id={t.ref.id} label="Source" className="ml-2 align-[1px]" />}
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export function MeetingsList({ items, now }: { items: ProjectDetail['meetings']; now: string | undefined }) {
  if (items.length === 0) return <EmptyState title="No meetings linked" />
  const nowMs = now ? new Date(now).getTime() : Date.now()
  return (
    <ul className="divide-y divide-line">
      {items.map((e) => {
        const upcoming = new Date(e.start_at).getTime() >= nowMs
        return (
          <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
            <div className="min-w-0">
              <Link href={`/calendar?event=${e.id}`} className="text-sm text-ink hover:text-accent">
                {e.title}
              </Link>
              <div className="text-xs text-ink-3">
                {fmtDate(e.start_at, { weekday: 'short', month: 'short', day: 'numeric' })} · {fmtTime(e.start_at)} · {e.attendees.length} attendees
                {e.notes && ' · has notes'}
              </div>
            </div>
            <div className="flex items-center gap-2">
              {upcoming && <Badge tone="info">Upcoming</Badge>}
              <Link href={`/calendar?event=${e.id}&brief=1`} className="text-xs text-accent hover:underline">
                {upcoming ? 'Prepare brief' : 'Brief'}
              </Link>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function EmailsList({ items, now }: { items: ProjectDetail['emails']; now: string | undefined }) {
  if (items.length === 0) return <EmptyState title="No emails linked" />
  return (
    <ul className="divide-y divide-line">
      {items.map((e) => (
        <li key={e.id}>
          <Link href={e.thread_id ? `/inbox/${e.thread_id}` : '/inbox'} className="block px-4 py-2.5 hover:bg-surface-2">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-sm text-ink">{e.subject}</span>
              <span className="shrink-0 text-xs tabular-nums text-ink-3">{relShort(e.sent_at, now) || fmtDate(e.sent_at, { month: 'short', day: 'numeric' })}</span>
            </div>
            <div className="flex items-center gap-2 text-xs text-ink-3">
              <span className="truncate">{e.direction === 'outbound' ? 'You' : (e.from_name ?? e.from_addr)}</span>
              {e.attachments.length > 0 && (
                <span className="inline-flex items-center gap-0.5">
                  <Paperclip className="h-3 w-3" aria-hidden />
                  {e.attachments.length}
                </span>
              )}
            </div>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export function DocumentsList({ items }: { items: ProjectDetail['documents'] }) {
  if (items.length === 0) return <EmptyState title="No documents linked" />
  return (
    <ul className="divide-y divide-line">
      {items.map((d) => (
        <li key={d.id} className="flex items-center justify-between gap-2 px-4 py-2.5">
          <Link href={`/documents/${d.id}`} className="inline-flex min-w-0 items-center gap-2 text-sm text-ink hover:text-accent">
            <FileText className="h-3.5 w-3.5 shrink-0 text-ink-3" aria-hidden />
            <span className="truncate">{d.title}</span>
          </Link>
          <span className="shrink-0 text-xs text-ink-3">
            {d.filename} · {bytes(d.size_bytes)}
            {d.authored_at && ` · ${fmtDate(d.authored_at, { month: 'short', day: 'numeric' })}`}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function NotesList({ items }: { items: ProjectDetail['notes'] }) {
  if (items.length === 0) return <EmptyState title="No notes linked" />
  return (
    <ul className="divide-y divide-line">
      {items.map((n) => (
        <li key={n.id} className="px-4 py-2.5">
          <Link href={`/notes?id=${n.id}`} className="inline-flex items-center gap-2 text-sm text-ink hover:text-accent">
            <NotebookPen className="h-3.5 w-3.5 text-ink-3" aria-hidden />
            {n.title}
          </Link>
          <p className="mt-0.5 line-clamp-2 text-xs text-ink-3">{n.body}</p>
        </li>
      ))}
    </ul>
  )
}

export function DecisionsList({ items }: { items: ProjectDetail['decisions'] }) {
  if (items.length === 0) return <EmptyState title="No decisions recorded" />
  return (
    <ul className="divide-y divide-line">
      {items.map((d) => (
        <li key={d.id} className="px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={d.status} />
            <span className={cn('text-sm font-medium', d.status === 'superseded' ? 'text-ink-3 line-through' : 'text-ink')}>{d.chosen}</span>
            {d.rejected.length > 0 && <span className="text-xs text-ink-3">over {d.rejected.join(', ')}</span>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">
            <span>
              {d.topic} · {fmtDate(d.decided_at)}
            </span>
            <Confidence value={d.confidence} />
            <EvidenceChip type={d.source.type} id={d.source.id} span={d.source.span} label="Source" />
          </div>
        </li>
      ))}
    </ul>
  )
}
