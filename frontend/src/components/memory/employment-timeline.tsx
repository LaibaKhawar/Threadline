'use client'

import { Building2 } from 'lucide-react'

import { AiLabel, Confidence, EvidenceChip } from '@/components/ui/ai'
import { Badge } from '@/components/ui/primitives'
import type { Employment, EvidenceRef } from '@/lib/types-memory'
import { cn, fmtDate } from '@/lib/utils'

export type EmploymentPeriod = {
  organization: string
  from: string | null
  to: string | null
  current: boolean
  titles: string[]
  bases: string[]
  confidence: number
  evidence: EvidenceRef[]
  facts: number
}

/**
 * Collapse the raw WORKS_AT facts into periods. Several facts often describe the same job (a signature
 * seen in five emails); consecutive facts about the same organisation become one period.
 */
export function employmentPeriods(rows: Employment[]): EmploymentPeriod[] {
  const sorted = [...rows].sort((a, b) => (a.valid_from ?? '').localeCompare(b.valid_from ?? ''))
  const out: EmploymentPeriod[] = []
  for (const r of sorted) {
    const last = out[out.length - 1]
    const open = !r.valid_to && r.status === 'active'
    if (last && last.organization === r.organization) {
      last.facts += 1
      last.confidence = Math.max(last.confidence, r.confidence)
      if (r.title && !last.titles.includes(r.title)) last.titles.push(r.title)
      if (r.basis && !last.bases.includes(r.basis)) last.bases.push(r.basis)
      if (r.evidence?.source_id && !last.evidence.some((e) => e.source_id === r.evidence?.source_id)) last.evidence.push(r.evidence)
      if (open) {
        last.current = true
        last.to = null
      } else if (!last.current && r.valid_to && (!last.to || r.valid_to > last.to)) last.to = r.valid_to
      continue
    }
    out.push({
      organization: r.organization,
      from: r.valid_from,
      to: open ? null : r.valid_to,
      current: open,
      titles: r.title ? [r.title] : [],
      bases: r.basis ? [r.basis] : [],
      confidence: r.confidence,
      evidence: r.evidence?.source_id ? [r.evidence] : [],
      facts: 1,
    })
  }
  return out
}

function uniqueBySpan(ev: EvidenceRef[]) {
  const seen = new Set<string>()
  return ev.filter((e) => {
    const k = (e.span ?? e.source_id ?? '').toLowerCase()
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

export function fmtRange(from: string | null, to: string | null, current: boolean) {
  const end = current ? 'now' : to ? fmtDate(to) : 'unknown'
  if (!from) return `until ${end}`
  const sameYear = to && !current && new Date(from).getUTCFullYear() === new Date(to).getUTCFullYear()
  const start = sameYear ? fmtDate(from, { month: 'short', day: 'numeric' }) : fmtDate(from)
  return `${start} – ${end}`
}

export function EmploymentTimeline({ rows }: { rows: Employment[] }) {
  const periods = employmentPeriods(rows)
  if (periods.length === 0) return <p className="px-4 py-6 text-center text-xs text-ink-3">No employment facts recorded yet.</p>
  // newest first
  const list = [...periods].reverse()
  return (
    <ol className="relative px-4 py-3" aria-label="Employment history">
      {list.map((p, i) => (
        <li key={`${p.organization}-${p.from}`} className="relative flex gap-3 pb-4 last:pb-0">
          {i < list.length - 1 && <span className="absolute left-[11px] top-6 bottom-0 w-px bg-line" aria-hidden />}
          <span className={cn('relative z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border', p.current ? 'border-accent bg-accent-wash text-accent' : 'border-line bg-sunken text-ink-3')}>
            <Building2 className="h-3 w-3" aria-hidden />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="text-sm font-medium text-ink">{p.organization}</span>
              {p.current ? <Badge tone="accent">Current</Badge> : <Badge tone="neutral">Past</Badge>}
            </div>
            <div className="mt-0.5 text-xs tabular-nums text-ink-2">{fmtRange(p.from, p.to, p.current)}</div>
            {p.titles.length > 0 && <div className="mt-0.5 text-xs text-ink-2">{p.titles.join(' · ')}</div>}
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <AiLabel>Inferred</AiLabel>
              <Confidence value={p.confidence} />
              {p.bases.map((b) => (
                <Badge key={b} tone="neutral" title="Basis for this inference">
                  {b}
                </Badge>
              ))}
              {uniqueBySpan(p.evidence).slice(0, 3).map((e) => (
                <EvidenceChip key={e.source_id} type={e.source_type} id={e.source_id} span={e.span} label={e.span ? `“${e.span}”` : 'Source'} className="max-w-[220px]" />
              ))}
              {p.evidence.length > Math.min(3, uniqueBySpan(p.evidence).length) && (
                <span className="text-[11px] text-ink-3">+{p.evidence.length - Math.min(3, uniqueBySpan(p.evidence).length)} more sources</span>
              )}
            </div>
            {p.facts > 1 && <p className="mt-1 text-[11px] text-ink-3">Combined from {p.facts} observations.</p>}
          </div>
        </li>
      ))}
    </ol>
  )
}
