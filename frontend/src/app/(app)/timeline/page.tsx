'use client'

import { useQuery } from '@tanstack/react-query'
import { History } from 'lucide-react'
import { useMemo, useState } from 'react'

import { TIMELINE_KINDS, kindMeta } from '@/components/memory/kinds'
import { RefLink } from '@/components/memory/ref-link'
import { ProjectChip } from '@/components/ui/ai'
import { Badge, Button, Card, EmptyState, ErrorState, Input, Label, LoadingRows, PageHeader, Select, Tabs } from '@/components/ui/primitives'
import { get } from '@/lib/api'
import type { ProjectSummary } from '@/lib/types'
import type { TimelineEvent } from '@/lib/types-memory'
import { cn, fmtDate, fmtTime } from '@/lib/utils'

type Group = 'day' | 'month'

const DOT: Record<string, string> = {
  accent: 'bg-accent',
  warning: 'bg-warning',
  info: 'bg-info',
  success: 'bg-success',
  uncertain: 'bg-uncertain',
  danger: 'bg-danger',
  neutral: 'bg-line-strong',
}

export default function TimelinePage() {
  const [kinds, setKinds] = useState<string[]>([])
  const [projectId, setProjectId] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [group, setGroup] = useState<Group>('day')
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })

  const qs = useMemo(() => {
    const p = new URLSearchParams({ limit: '500' })
    if (kinds.length) p.set('kinds', kinds.join(','))
    if (projectId) p.set('project_id', projectId)
    if (from) p.set('start', `${from}T00:00:00Z`)
    if (to) p.set('end', `${to}T23:59:59Z`)
    return p.toString()
  }, [kinds, projectId, from, to])
  const q = useQuery({ queryKey: ['timeline', qs], queryFn: () => get<{ events: TimelineEvent[] }>(`/api/timeline?${qs}`), placeholderData: (prev) => prev })

  const groups = useMemo(() => {
    const out: { key: string; label: string; future: boolean; items: TimelineEvent[] }[] = []
    for (const e of q.data?.events ?? []) {
      const key = group === 'day' ? e.occurred_at.slice(0, 10) : e.occurred_at.slice(0, 7)
      let g = out[out.length - 1]
      if (!g || g.key !== key) {
        const label = group === 'day' ? fmtDate(e.occurred_at, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' }) : fmtDate(e.occurred_at, { month: 'long', year: 'numeric' })
        g = { key, label, future: e.future, items: [] }
        out.push(g)
      }
      g.items.push(e)
      if (!e.future) g.future = false
    }
    return out
  }, [q.data, group])

  const toggleKind = (k: string) => setKinds((ks) => (ks.includes(k) ? ks.filter((x) => x !== k) : [...ks, k]))
  const filtered = kinds.length > 0 || projectId || from || to

  return (
    <div className="animate-fade-in">
      <PageHeader title="Timeline" description="Your memory in order: decisions, moved deadlines, commitments made and kept, job changes, meetings and documents. Each entry links back to where it came from." />

      <Card className="mb-5 p-3">
        <div className="flex flex-wrap items-end gap-3">
          <fieldset className="min-w-0 flex-1">
            <legend className="mb-1 text-xs font-medium text-ink-2">Kinds</legend>
            <div className="flex flex-wrap gap-1.5">
              {TIMELINE_KINDS.map((k) => {
                const on = kinds.includes(k.value)
                return (
                  <button
                    key={k.value}
                    aria-pressed={on}
                    onClick={() => toggleKind(k.value)}
                    className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors', on ? 'border-accent bg-accent-wash text-accent' : 'border-line text-ink-2 hover:bg-sunken')}
                  >
                    <span className={cn('h-1.5 w-1.5 rounded-full', DOT[k.tone])} aria-hidden />
                    {k.label}
                  </button>
                )
              })}
            </div>
          </fieldset>
          <div>
            <Label htmlFor="tl-project">Project</Label>
            <Select id="tl-project" className="h-8 w-40 text-xs" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
              <option value="">All projects</option>
              {projects.data?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="tl-from">From</Label>
            <Input id="tl-from" type="date" className="h-8 w-36 text-xs" value={from} onChange={(e) => setFrom(e.target.value)} />
          </div>
          <div>
            <Label htmlFor="tl-to">To</Label>
            <Input id="tl-to" type="date" className="h-8 w-36 text-xs" value={to} onChange={(e) => setTo(e.target.value)} />
          </div>
          {filtered && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setKinds([])
                setProjectId('')
                setFrom('')
                setTo('')
              }}
            >
              Clear filters
            </Button>
          )}
        </div>
      </Card>

      <div className="mb-3 flex items-center justify-between gap-3">
        <Tabs<Group>
          value={group}
          onChange={setGroup}
          tabs={[
            { value: 'day', label: 'By day' },
            { value: 'month', label: 'By month' },
          ]}
        />
        {q.data && <span className="text-xs tabular-nums text-ink-3">{q.data.events.length} events</span>}
      </div>

      {q.isLoading ? (
        <Card>
          <LoadingRows rows={8} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Card>
      ) : groups.length === 0 ? (
        <Card>
          <EmptyState icon={<History className="h-4 w-4" />} title={filtered ? 'Nothing in this slice of time' : 'Your timeline is empty'} description={filtered ? 'Try other kinds, another project or a wider date range.' : 'Connect a source or open the demo workspace to build memory.'} />
        </Card>
      ) : (
        <div className={cn('space-y-5 transition-opacity', q.isFetching && 'opacity-70')}>
          {groups.map((g) => (
            <section key={g.key} aria-labelledby={`tl-${g.key}`}>
              <h2 id={`tl-${g.key}`} className="sticky top-12 z-10 mb-2 flex items-center gap-2 bg-bg py-1 text-xs font-semibold uppercase tracking-wide text-ink-2">
                {g.label}
                {g.future && <Badge tone="info">Upcoming</Badge>}
                <span className="font-normal normal-case tracking-normal text-ink-3">· {g.items.length}</span>
              </h2>
              <Card>
                <ol className="divide-y divide-line">
                  {g.items.map((e) => {
                    const k = kindMeta(e.kind)
                    return (
                      <li key={e.id} className={cn('flex gap-3 px-4 py-3', e.future && 'bg-surface-2')}>
                        <div className="w-16 shrink-0 pt-0.5 text-[11px] tabular-nums text-ink-3">
                          {group === 'month' && <div>{fmtDate(e.occurred_at, { month: 'short', day: 'numeric' })}</div>}
                          <div>{fmtTime(e.occurred_at)}</div>
                        </div>
                        <span className={cn('mt-1.5 h-2 w-2 shrink-0 rounded-full', DOT[k.tone])} aria-hidden />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge tone={k.tone}>{k.label}</Badge>
                            <RefLink type={e.ref.type} id={e.ref.id} label={e.title} span={e.detail} className="min-w-0 text-sm font-medium" />
                            <ProjectChip project={e.project} />
                            {e.future && <span className="text-[11px] text-info">scheduled</span>}
                          </div>
                          {e.detail && <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{e.detail}</p>}
                        </div>
                      </li>
                    )
                  })}
                </ol>
              </Card>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
