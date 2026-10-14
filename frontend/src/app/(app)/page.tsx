'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CalendarDays, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import Link from 'next/link'

import { Confidence, EvidenceChip, StatusBadge } from '@/components/ui/ai'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingRows } from '@/components/ui/primitives'
import { get, post } from '@/lib/api'
import type { Evidence } from '@/lib/types'
import { cn, fmtDate, fmtTime, relDays } from '@/lib/utils'

type BriefItem = {
  ref: { type: string | null; id: string | null }
  title: string
  status?: string
  due_at?: string | null
  reason?: string | null
  confidence?: number
  actor?: string | null
  evidence?: { source_type: string; source_id: string; span?: string; label?: string | null }[]
}
type InsightItem = {
  insight_id: string
  kind: string
  title: string
  explanation: string
  evidence: Evidence[]
  score: number
  confidence: number
}
type Dashboard = {
  now: string
  clock_pinned: boolean
  user_first_name: string | null
  counts: Record<string, number>
  recent_activity: { id: string; kind: string; title: string; occurred_at: string; ref: { type: string; id: string } }[]
  briefing: {
    sections: {
      today: { meetings_today: number; deadlines_soon: number; overdue_commitments: number; people_awaiting: number; projects_attention: string[] }
      meetings: { ref: { id: string }; title: string; start_at: string; end_at: string; attendees: string[]; is_today: boolean }[]
      deadlines: BriefItem[]
      tasks: { ref: { id: string }; title: string; due_at: string | null; status: string; priority: string; overdue: boolean }[]
      suggested_tasks: number
      overdue: BriefItem[]
      awaiting: InsightItem[]
      followups: InsightItem[]
      projects: { ref: { id: string }; title: string; status: string; label: string; signals: { signal: string; weight: number }[]; score: number }[]
      changes: { ref: { type: string; id: string }; title: string; occurred_at: string; kind: string }[]
    }
  }
}

function greeting(now: string) {
  const h = new Date(now).getUTCHours()
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'
}

export default function DashboardPage() {
  const q = useQuery({ queryKey: ['dashboard'], queryFn: () => get<Dashboard>('/api/dashboard') })
  if (q.isLoading) return <LoadingRows rows={8} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const d = q.data
  const s = d.briefing.sections
  const t = s.today
  const parts = [
    `${t.meetings_today} meeting${t.meetings_today === 1 ? '' : 's'} today`,
    `${t.deadlines_soon} deadline${t.deadlines_soon === 1 ? '' : 's'} approaching`,
    `${t.overdue_commitments} commitment${t.overdue_commitments === 1 ? '' : 's'} overdue`,
    `${t.people_awaiting} ${t.people_awaiting === 1 ? 'person' : 'people'} may need a reply`,
  ]
  return (
    <div className="animate-fade-in">
      <header className="mb-6">
        <p className="text-xs font-medium uppercase tracking-wide text-ink-3">
          {fmtDate(d.now, { weekday: 'long', month: 'long', day: 'numeric' })}
          {d.clock_pinned && <span className="ml-2 normal-case tracking-normal text-uncertain">· demo clock pinned</span>}
        </p>
        <h1 className="mt-1 font-serif text-[28px] font-medium tracking-tight">
          {greeting(d.now)}
          {d.user_first_name ? `, ${d.user_first_name}` : ''}.
        </h1>
        <p className="mt-1 text-sm text-ink-2">
          {parts.join(' · ')}
          {t.projects_attention.length > 0 && (
            <>
              {' · '}
              <span className="text-warning">{t.projects_attention.join(', ')} need attention</span>
            </>
          )}
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <CardHeader title="Overdue commitments" description="Promises whose due date passed with no matching delivery found. Each shows why." action={<Link href="/commitments?status=OVERDUE" className="text-xs text-accent hover:underline">All commitments</Link>} />
            {s.overdue.length === 0 ? (
              <EmptyState title="Nothing overdue" description="No promises are past their due date." />
            ) : (
              <ul className="divide-y divide-line">
                {s.overdue.slice(0, 6).map((c) => (
                  <li key={c.ref.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={c.status ?? 'OVERDUE'} />
                      <span className="text-sm font-medium text-ink">{c.title}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
                      <span>Due {fmtDate(c.due_at)}{relDays(c.due_at, d.now).includes(',') ? '' : ` (${relDays(c.due_at, d.now)})`}</span>
                      <Confidence value={c.confidence} label="extraction confidence" />
                      {c.evidence?.map((e) => <EvidenceChip key={e.source_id} type={e.source_type} id={e.source_id} span={e.span} label={e.label} />)}
                    </div>
                    {c.reason && <p className="mt-1.5 text-xs text-ink-2">{c.reason}</p>}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <FollowUps items={[...s.awaiting, ...s.followups]} />

          <Card>
            <CardHeader title="Recent memory activity" description="What Threadline learned most recently." action={<Link href="/timeline" className="text-xs text-accent hover:underline">Timeline</Link>} />
            <ul className="divide-y divide-line">
              {d.recent_activity.slice(0, 8).map((a) => (
                <li key={a.id} className="flex items-start gap-3 px-4 py-2.5">
                  <span className="mt-0.5 w-20 shrink-0 text-[11px] text-ink-3">{relDays(a.occurred_at, d.now)}</span>
                  <Badge tone="neutral">{a.kind.replace(/_/g, ' ')}</Badge>
                  <span className="min-w-0 truncate text-sm text-ink-2">{a.title}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader title="Upcoming meetings" action={<Link href="/calendar" className="text-xs text-accent hover:underline">Calendar</Link>} />
            {s.meetings.length === 0 ? (
              <EmptyState title="No meetings today or tomorrow" icon={<CalendarDays className="h-4 w-4" />} />
            ) : (
              <ul className="divide-y divide-line">
                {s.meetings.map((m) => (
                  <li key={m.ref.id} className="px-4 py-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{m.title}</span>
                      <span className="shrink-0 text-xs tabular-nums text-ink-3">
                        {m.is_today ? '' : 'Tomorrow '}
                        {fmtTime(m.start_at)}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-ink-3">{m.attendees.join(', ')}</span>
                      <Link href={`/calendar?event=${m.ref.id}&brief=1`} className="shrink-0 text-xs text-accent hover:underline">
                        Prepare brief
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Projects" description="Health is a heuristic; the signals behind it are listed." />
            <ul className="divide-y divide-line">
              {s.projects.map((p) => (
                <li key={p.ref.id} className="px-4 py-2.5">
                  <div className="flex items-center justify-between">
                    <Link href={`/projects/${p.ref.id}`} className="text-sm font-medium hover:text-accent">
                      {p.title}
                    </Link>
                    <StatusBadge status={p.status} />
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {p.signals.filter((x) => x.weight > 0).slice(0, 3).map((x) => (
                      <li key={x.signal} className="text-xs text-ink-3">
                        · {x.signal}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader
              title="Tasks"
              action={
                s.suggested_tasks > 0 ? (
                  <Link href="/tasks?view=suggested" className="text-xs text-uncertain hover:underline">
                    {s.suggested_tasks} AI suggestions to review
                  </Link>
                ) : undefined
              }
            />
            <ul className="divide-y divide-line">
              {s.tasks.length === 0 && <EmptyState title="No open tasks" />}
              {s.tasks.map((t2) => (
                <li key={t2.ref.id} className="flex items-center justify-between gap-2 px-4 py-2">
                  <span className="truncate text-sm">{t2.title}</span>
                  <span className={cn('shrink-0 text-xs tabular-nums', t2.overdue ? 'text-danger' : 'text-ink-3')}>{t2.status === 'blocked' ? 'Blocked' : t2.due_at ? relDays(t2.due_at, d.now) : ''}</span>
                </li>
              ))}
            </ul>
          </Card>

          {s.deadlines.length > 0 && (
            <Card>
              <CardHeader title="Deadlines in the next 3 days" />
              <ul className="divide-y divide-line">
                {s.deadlines.map((x) => (
                  <li key={x.ref.id} className="px-4 py-2">
                    <div className="text-sm">{x.title}</div>
                    <div className="text-xs text-ink-3">{relDays(x.due_at, d.now)}</div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function FollowUps({ items }: { items: InsightItem[] }) {
  const qc = useQueryClient()
  const act = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, string> }) => post(`/api/insights/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['dashboard'] }),
  })
  return (
    <Card>
      <CardHeader title="Potential follow-ups" description="Ranked by importance, urgency, confidence and your feedback." action={<Link href="/commitments" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">Review <ArrowRight className="h-3 w-3" /></Link>} />
      {items.length === 0 ? (
        <EmptyState title="No follow-ups needed" description="Nobody seems to be waiting on you, and no requests look stalled." />
      ) : (
        <ul className="divide-y divide-line">
          {items.slice(0, 6).map((i) => (
            <li key={i.insight_id} className="group px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-ink">{i.title}</p>
                  <p className="mt-0.5 text-xs text-ink-2">{i.explanation}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    {i.evidence.map((e) => (
                      <EvidenceChip key={e.source_id} type={e.source_type} id={e.source_id} span={e.span} label={e.label} />
                    ))}
                    <Confidence value={i.confidence} />
                  </div>
                </div>
                <div className="flex shrink-0 gap-0.5 opacity-60 group-hover:opacity-100">
                  <Button size="icon" variant="ghost" aria-label="Useful" title="Useful" onClick={() => act.mutate({ id: i.insight_id, body: { feedback: 'useful' } })}>
                    <ThumbsUp className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="icon" variant="ghost" aria-label="Not useful" title="Not useful (ranks this kind lower)" onClick={() => act.mutate({ id: i.insight_id, body: { feedback: 'not_useful' } })}>
                    <ThumbsDown className="h-3.5 w-3.5" />
                  </Button>
                  <Button size="icon" variant="ghost" aria-label="Dismiss" title="Dismiss" onClick={() => act.mutate({ id: i.insight_id, body: { status: 'dismissed' } })}>
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

