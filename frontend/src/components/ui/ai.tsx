'use client'

import { Bot, Check, FileText, Mail, MessageSquareText, NotebookPen, Pencil, X, CalendarDays, Sparkles } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'

import { useSource } from '@/components/source-drawer'
import { Badge, Button } from '@/components/ui/primitives'
import type { CommitmentStatus, PersonBrief, ProjectBrief } from '@/lib/types'
import { cn, initials, pct } from '@/lib/utils'

const STATUS_TONE: Record<string, 'danger' | 'warning' | 'success' | 'info' | 'uncertain' | 'neutral'> = {
  OPEN: 'info',
  OVERDUE: 'danger',
  FULFILLED: 'success',
  CANCELLED: 'neutral',
  UNCERTAIN: 'uncertain',
  REJECTED: 'neutral',
  active: 'info',
  blocked: 'danger',
  done: 'success',
  suggested: 'uncertain',
  dismissed: 'neutral',
  superseded: 'neutral',
  rejected: 'neutral',
  at_risk: 'danger',
  attention: 'warning',
  on_track: 'success',
  paused: 'neutral',
}

const STATUS_LABEL: Record<string, string> = {
  OPEN: 'Open',
  OVERDUE: 'Overdue',
  FULFILLED: 'Fulfilled',
  CANCELLED: 'Cancelled',
  UNCERTAIN: 'Uncertain',
  REJECTED: 'Not a commitment',
  suggested: 'AI suggestion',
  at_risk: 'At risk',
  attention: 'Attention needed',
  on_track: 'On track',
}

export function StatusBadge({ status, className }: { status: CommitmentStatus | string; className?: string }) {
  return (
    <Badge tone={STATUS_TONE[status] ?? 'neutral'} className={className}>
      {STATUS_LABEL[status] ?? status.charAt(0).toUpperCase() + status.slice(1)}
    </Badge>
  )
}

/** Confidence as a small meter + percentage. Always shown next to AI inferences. */
export function Confidence({ value, label = 'confidence', className }: { value: number | null | undefined; label?: string; className?: string }) {
  if (value === null || value === undefined) return null
  const v = Math.max(0, Math.min(1, value))
  const tone = v >= 0.8 ? 'bg-success' : v >= 0.55 ? 'bg-warning' : 'bg-danger'
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-[11px] text-ink-3', className)} title={`${label}: ${pct(v)}`}>
      <span className="relative h-1 w-10 overflow-hidden rounded-full bg-sunken" aria-hidden>
        <span className={cn('absolute inset-y-0 left-0 rounded-full', tone)} style={{ width: `${v * 100}%` }} />
      </span>
      <span className="tabular-nums">{pct(v)}</span>
      <span className="sr-only">{label}</span>
    </span>
  )
}

export function Avatar({ name, className }: { name: string | null | undefined; className?: string }) {
  return (
    <span className={cn('inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-sunken text-[10px] font-semibold text-ink-2', className)} aria-hidden>
      {initials(name)}
    </span>
  )
}

export function PersonChip({ person, fallback }: { person: PersonBrief | null | undefined; fallback?: string | null }) {
  if (!person) return <span className="text-ink-3">{fallback ?? 'Unknown'}</span>
  if (person.is_self) return <span className="font-medium text-ink">You</span>
  return (
    <Link href={`/people/${person.id}`} className="inline-flex items-center gap-1.5 font-medium text-ink hover:text-accent">
      <Avatar name={person.name} className="h-5 w-5 text-[9px]" />
      {person.name}
    </Link>
  )
}

export function ProjectChip({ project }: { project: ProjectBrief | null | undefined }) {
  if (!project) return null
  return (
    <Link href={`/projects/${project.id}`} className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[11px] text-ink-2 hover:border-accent hover:text-accent">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: project.color ?? 'var(--ink-3)' }} aria-hidden />
      {project.name}
    </Link>
  )
}

export const SOURCE_ICON: Record<string, ReactNode> = {
  email: <Mail className="h-3 w-3" />,
  event: <CalendarDays className="h-3 w-3" />,
  document: <FileText className="h-3 w-3" />,
  note: <NotebookPen className="h-3 w-3" />,
}

/** Opens the source drawer with the exact span highlighted: the "why" behind every AI statement. */
export function EvidenceChip({ type, id, span, label, className }: { type: string | null | undefined; id: string | null | undefined; span?: string | null; label?: ReactNode; className?: string }) {
  const { open } = useSource()
  if (!type || !id) return null
  return (
    <button
      onClick={() => open({ type, id, span: span ?? undefined })}
      className={cn('inline-flex max-w-full items-center gap-1 rounded border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-2 hover:border-accent hover:text-accent', className)}
      title="Open source"
    >
      {SOURCE_ICON[type] ?? <MessageSquareText className="h-3 w-3" />}
      <span className="truncate">{label ?? 'Source'}</span>
    </button>
  )
}

export function Quote({ children, className }: { children: ReactNode; className?: string }) {
  return <blockquote className={cn('border-l-2 border-line-strong pl-2.5 text-xs italic text-ink-2', className)}>{children}</blockquote>
}

export function AiLabel({ children = 'AI inferred' }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-uncertain">
      <Sparkles className="h-3 w-3" aria-hidden />
      {children}
    </span>
  )
}

/** "AI inferred: Project Atlas (82%) — because … — Confirm / Change / Ignore" */
export function InferenceCard({
  label,
  value,
  confidence,
  reasons,
  onConfirm,
  onChange,
  onIgnore,
  busy,
}: {
  label: string
  value: ReactNode
  confidence: number
  reasons: string[]
  onConfirm?: () => void
  onChange?: () => void
  onIgnore?: () => void
  busy?: boolean
}) {
  return (
    <div className="rounded-md border border-uncertain/25 bg-uncertain-wash/60 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm">
          <AiLabel>{label}</AiLabel>
          <span className="font-medium text-ink">{value}</span>
          <Confidence value={confidence} />
        </div>
        <div className="flex gap-1">
          {onConfirm && (
            <Button size="sm" variant="secondary" onClick={onConfirm} disabled={busy}>
              <Check className="h-3 w-3" /> Confirm
            </Button>
          )}
          {onChange && (
            <Button size="sm" variant="ghost" onClick={onChange} disabled={busy}>
              <Pencil className="h-3 w-3" /> Change
            </Button>
          )}
          {onIgnore && (
            <Button size="sm" variant="ghost" onClick={onIgnore} disabled={busy}>
              <X className="h-3 w-3" /> Ignore
            </Button>
          )}
        </div>
      </div>
      {reasons.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-ink-2">
          {reasons.map((r) => (
            <li key={r} className="flex gap-1.5">
              <span className="text-ink-3">·</span>
              {r}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const CHANNEL_LABEL: Record<string, string> = { vector: 'semantic', keyword: 'keyword', graph: 'graph', structured: 'structured', entity: 'entity' }

export function ChannelBadges({ channels }: { channels: Record<string, number> }) {
  return (
    <span className="inline-flex flex-wrap gap-1">
      {Object.entries(channels).map(([ch, rank]) => (
        <span key={ch} className="rounded bg-sunken px-1 py-px text-[10px] text-ink-3" title={`${CHANNEL_LABEL[ch] ?? ch} rank ${rank}`}>
          {CHANNEL_LABEL[ch] ?? ch} #{rank}
        </span>
      ))}
    </span>
  )
}

export function AgentIcon() {
  return (
    <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-accent-wash text-accent" aria-hidden>
      <Bot className="h-3.5 w-3.5" />
    </span>
  )
}
