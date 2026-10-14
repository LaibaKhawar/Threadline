'use client'

import { useQuery } from '@tanstack/react-query'
import { Handshake } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect } from 'react'

import { EvidenceChip } from '@/components/ui/ai'
import { Card, EmptyState, ErrorState, LoadingRows, PageHeader, Select } from '@/components/ui/primitives'
import { CommitmentDetailView, CommitmentDrawer, CommitmentSummary } from '@/components/work/commitments'
import { useMediaQuery, useProjects } from '@/components/work/shared'
import { get } from '@/lib/api'
import type { CommitmentList } from '@/lib/types-work'
import { cn } from '@/lib/utils'

export default function CommitmentsPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <CommitmentsView />
    </Suspense>
  )
}

const STATUSES = [
  { value: '', label: 'All' },
  { value: 'OPEN', label: 'Open' },
  { value: 'OVERDUE', label: 'Overdue' },
  { value: 'UNCERTAIN', label: 'Uncertain' },
  { value: 'FULFILLED', label: 'Fulfilled' },
  { value: 'CANCELLED', label: 'Cancelled' },
  { value: 'REJECTED', label: 'Not a commitment' },
]

const STATUS_ACTIVE: Record<string, string> = {
  OVERDUE: 'border-danger/40 bg-danger-wash text-danger',
  OPEN: 'border-info/40 bg-info-wash text-info',
  UNCERTAIN: 'border-uncertain/40 bg-uncertain-wash text-uncertain',
  FULFILLED: 'border-success/40 bg-success-wash text-success',
}

function CommitmentsView() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const status = sp.get('status') ?? ''
  const direction = sp.get('direction') ?? ''
  const kind = sp.get('kind') ?? ''
  const project = sp.get('project') ?? ''
  const selected = sp.get('id')
  const projects = useProjects()
  const isLg = useMediaQuery('(min-width: 1024px)')

  const setParams = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp.toString())
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    router.replace(`${pathname}${next.toString() ? `?${next}` : ''}`, { scroll: false })
  }

  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (direction) params.set('direction', direction)
  if (kind) params.set('kind', kind)
  if (project) params.set('project_id', project)
  const q = useQuery({ queryKey: ['commitments', params.toString()], queryFn: () => get<CommitmentList>(`/api/commitments?${params}`) })
  const counts = q.data?.counts ?? {}
  const total = Object.values(counts).reduce((a, b) => a + b, 0)
  const now = q.data?.now

  // close the mobile overlay with Escape
  useEffect(() => {
    if (!selected || !isLg) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !document.querySelector('[aria-label="Source"]') && setParams({ id: null })
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, isLg])

  return (
    <div>
      <PageHeader
        title="Commitments"
        description="Promises, requests and intentions found in your email, meetings and documents. Each one shows the exact sentence it came from and why it has its status."
      />

      <div className="mb-3 flex flex-wrap gap-1.5" role="group" aria-label="Status">
        {STATUSES.map((s) => {
          const n = s.value ? (counts[s.value] ?? 0) : total
          const on = status === s.value
          return (
            <button
              key={s.value}
              type="button"
              aria-pressed={on}
              onClick={() => setParams({ status: s.value })}
              className={cn(
                'inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs',
                on ? (STATUS_ACTIVE[s.value] ?? 'border-line-strong bg-sunken font-medium text-ink') : 'border-line bg-surface text-ink-2 hover:border-line-strong',
              )}
            >
              {s.label}
              <span className="tabular-nums opacity-70">{q.data ? n : '–'}</span>
            </button>
          )
        })}
      </div>
      <div className="mb-4 flex flex-wrap gap-2">
        <label htmlFor="c-dir" className="sr-only">
          Direction
        </label>
        <Select id="c-dir" value={direction} onChange={(e) => setParams({ direction: e.target.value })}>
          <option value="">Everyone</option>
          <option value="mine">I owe</option>
          <option value="owed_to_me">Owed to me / by others</option>
        </Select>
        <label htmlFor="c-kind" className="sr-only">
          Kind
        </label>
        <Select id="c-kind" value={kind} onChange={(e) => setParams({ kind: e.target.value })}>
          <option value="">All kinds</option>
          <option value="commitment">Commitments (promises)</option>
          <option value="request">Requests</option>
          <option value="intention">Intentions</option>
        </Select>
        <label htmlFor="c-project" className="sr-only">
          Project
        </label>
        <Select id="c-project" value={project} onChange={(e) => setParams({ project: e.target.value })}>
          <option value="">All projects</option>
          {projects.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>

      <div className={cn('grid gap-5', selected && isLg && 'lg:grid-cols-[minmax(0,1fr)_minmax(0,460px)]')}>
        <Card className="min-w-0 self-start">
          {q.isLoading ? (
            <LoadingRows rows={8} />
          ) : q.error || !q.data ? (
            <ErrorState error={q.error} retry={() => q.refetch()} />
          ) : q.data.items.length === 0 ? (
            <EmptyState icon={<Handshake className="h-4 w-4" />} title={status || direction || kind || project ? 'Nothing matches these filters' : 'No commitments found yet'} description={status === 'OVERDUE' ? 'Nothing is past due.' : 'Commitments appear as Threadline reads your email and meeting notes.'} />
          ) : (
            <ul className="divide-y divide-line">
              {q.data.items.map((c) => (
                <li key={c.id} className={cn('relative', selected === c.id && 'bg-accent-wash')}>
                  <button
                    type="button"
                    onClick={() => setParams({ id: selected === c.id ? null : c.id })}
                    aria-expanded={selected === c.id}
                    className="block w-full px-4 pb-1 pt-3 text-left hover:bg-surface-2/60"
                  >
                    <CommitmentSummary c={c} now={now} />
                  </button>
                  <div className="flex flex-wrap items-center gap-2 px-4 pb-3 pt-1">
                    <EvidenceChip type={c.source.type} id={c.source.id} span={c.source.span} label={`“${c.source.span.length > 70 ? `${c.source.span.slice(0, 70)}…` : c.source.span}”`} />
                    {c.status === 'OVERDUE' && c.resolution?.reason && (
                      <span className="line-clamp-2 min-w-0 flex-1 basis-60 text-[11px] text-ink-3" title={c.resolution.reason}>
                        Why overdue: {c.resolution.reason}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        {selected && isLg && (
          <div className="self-start rounded-lg border border-line bg-surface p-5 shadow-card">
            <CommitmentDetailView id={selected} now={now} onOpen={(id) => setParams({ id })} onClose={() => setParams({ id: null })} />
          </div>
        )}
      </div>
      {selected && !isLg && <CommitmentDrawer id={selected} now={now} onOpen={(id) => setParams({ id })} onClose={() => setParams({ id: null })} />}
    </div>
  )
}
