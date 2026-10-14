'use client'

import Link from 'next/link'

import { Confidence, EvidenceChip, PersonChip, ProjectChip, StatusBadge } from '@/components/ui/ai'
import { Badge } from '@/components/ui/primitives'
import type { Commitment, Decision, Task } from '@/lib/types'
import { cn, fmtDate, relDays } from '@/lib/utils'

/** One extracted commitment with its source passage, confidence and status reason. */
export function CommitmentRow({ c, now, showPeople = true }: { c: Commitment; now?: string; showPeople?: boolean }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={c.status} />
        <Link href={`/commitments?id=${c.id}`} className="min-w-0 text-sm font-medium text-ink hover:text-accent">
          {c.description}
        </Link>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
        {showPeople && (
          <span className="inline-flex items-center gap-1">
            <PersonChip person={c.actor} fallback={c.actor_text} />
            {c.recipient && (
              <>
                <span>→</span>
                <PersonChip person={c.recipient} />
              </>
            )}
          </span>
        )}
        {c.due_at && (
          <span className={cn(c.status === 'OVERDUE' && 'text-danger')}>
            Due {fmtDate(c.due_at)}
            {now ? ` (${relDays(c.due_at, now)})` : ''}
          </span>
        )}
        <Confidence value={c.confidence} label="extraction confidence" />
        <ProjectChip project={c.project} />
        <EvidenceChip type={c.source.type} id={c.source.id} span={c.source.span} label={c.source.span ? `“${c.source.span}”` : 'Source'} className="max-w-[260px]" />
      </div>
      {c.resolution?.reason && <p className="mt-1 text-xs text-ink-2">{c.resolution.reason}</p>}
    </li>
  )
}

export function DecisionRow({ d }: { d: Decision }) {
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={d.status} />
        <span className="text-xs text-ink-3">{d.topic}</span>
        <Link href={`/decisions?id=${d.id}`} className="text-sm font-medium text-ink hover:text-accent">
          {d.chosen}
        </Link>
      </div>
      {d.rejected.length > 0 && <p className="mt-0.5 text-xs text-ink-3">Instead of {d.rejected.join(', ')}</p>}
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
        <span>{fmtDate(d.decided_at)}</span>
        <Confidence value={d.confidence} />
        <ProjectChip project={d.project} />
        <EvidenceChip type={d.source.type} id={d.source.id} span={d.source.span} label={d.source.span ? `“${d.source.span}”` : 'Source'} className="max-w-[260px]" />
      </div>
    </li>
  )
}

export function TaskRow({ t, now }: { t: Task; now?: string }) {
  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={t.status} />
        <Link href={`/tasks?id=${t.id}`} className="text-sm text-ink hover:text-accent">
          {t.title}
        </Link>
        {t.priority === 'high' || t.priority === 'urgent' ? <Badge tone="warning">{t.priority}</Badge> : null}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
        {t.due_at && <span>Due {now ? relDays(t.due_at, now) : fmtDate(t.due_at)}</span>}
        {t.blocked_by && (
          <span className="inline-flex items-center gap-1">
            Blocked by <PersonChip person={t.blocked_by} />
          </span>
        )}
        <ProjectChip project={t.project} />
        {t.source && <EvidenceChip type={t.source.type} id={t.source.id} span={t.source.span} />}
      </div>
    </li>
  )
}
