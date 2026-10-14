'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, CalendarDays } from 'lucide-react'
import Link from 'next/link'
import { use, useId, useState } from 'react'

import { Avatar, StatusBadge } from '@/components/ui/ai'
import { Card, CardHeader, EmptyState, ErrorState, LoadingRows, Select, Stat, Tabs } from '@/components/ui/primitives'
import { CommitmentDrawer, CommitmentSummary } from '@/components/work/commitments'
import { DecisionsList, DocumentsList, EmailsList, FactsHistory, MeetingsList, NotesList, ProjectTimeline } from '@/components/work/project-sections'
import { HEALTH_EXPLAINER, HealthSignals, relShort, useNow, useWorkMutation } from '@/components/work/shared'
import { NewTaskButton, TaskInlineEdit, TaskLine } from '@/components/work/tasks'
import { get, patch } from '@/lib/api'
import type { ProjectSummary } from '@/lib/types'
import type { ProjectDetail } from '@/lib/types-work'
import { fmtDateTime } from '@/lib/utils'

type Tab = 'overview' | 'tasks' | 'commitments' | 'decisions' | 'meetings' | 'emails' | 'documents' | 'notes'

const STATUS_OPTIONS = [
  { value: 'auto', label: 'Automatic (heuristic)' },
  { value: 'on_track', label: 'On track' },
  { value: 'attention', label: 'Attention needed' },
  { value: 'at_risk', label: 'At risk' },
  { value: 'paused', label: 'Paused' },
  { value: 'done', label: 'Done' },
]

export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const now = useNow()
  const [tab, setTab] = useState<Tab>('overview')
  const [openC, setOpenC] = useState<string | null>(null)
  const sid = useId()
  const q = useQuery({ queryKey: ['project', id], queryFn: () => get<ProjectDetail>(`/api/projects/${id}`) })
  const status = useWorkMutation(
    (s: string) => patch<ProjectSummary>(`/api/projects/${id}`, { status_manual: s }),
    (p, s) => (s === 'auto' ? `Status back to automatic: ${p.health.label}` : `Status set to ${p.health.label}`),
  )
  if (q.isLoading) return <LoadingRows rows={10} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const p = q.data
  const tasks = p.tasks
  const openCommitments = p.commitments.filter((c) => ['OPEN', 'OVERDUE', 'UNCERTAIN'].includes(c.status))
  const closedCommitments = p.commitments.filter((c) => !['OPEN', 'OVERDUE', 'UNCERTAIN'].includes(c.status))

  return (
    <div>
      <Link href="/projects" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink">
        <ArrowLeft className="h-3 w-3" /> Projects
      </Link>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2.5 font-serif text-[26px] font-medium leading-tight tracking-tight text-ink">
            <span className="h-3 w-3 shrink-0 rounded-full" style={{ background: p.color ?? 'var(--ink-3)' }} aria-hidden />
            {p.name}
          </h1>
          {p.description && <p className="mt-1 max-w-2xl text-sm text-ink-2">{p.description}</p>}
          {p.keywords.length > 0 && <p className="mt-1 text-xs text-ink-3">Keywords: {p.keywords.join(', ')}</p>}
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor={sid} className="text-xs text-ink-3">
            Status
          </label>
          <Select id={sid} value={p.status_manual ?? 'auto'} disabled={status.isPending} onChange={(e) => status.mutate(e.target.value)}>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </div>
      </header>

      <div className="mb-5 grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            title={
              <span className="flex items-center gap-2">
                Health <StatusBadge status={p.health.status} />
              </span>
            }
            description={p.status_manual ? 'Set manually. The heuristic signals are still shown for reference.' : HEALTH_EXPLAINER}
            action={<span className="shrink-0 text-xs tabular-nums text-ink-3">risk {p.health.score.toFixed(2)}</span>}
          />
          <div className="px-4 py-3">
            <HealthSignals signals={p.health.signals} />
          </div>
        </Card>
        <Card>
          <div className="grid grid-cols-3 gap-3 border-b border-line px-4 py-3">
            <Stat label="Open tasks" value={p.open_tasks} />
            <Stat label="Overdue" value={p.overdue_commitments} tone={p.overdue_commitments ? 'danger' : undefined} />
            <Stat label="Decisions" value={p.decisions.filter((d) => d.status === 'active').length} hint="active" />
          </div>
          <div className="space-y-2 px-4 py-3 text-xs">
            {p.upcoming_meeting ? (
              <Link href={`/calendar?event=${p.upcoming_meeting.id}&brief=1`} className="flex items-center gap-1.5 text-ink-2 hover:text-accent">
                <CalendarDays className="h-3.5 w-3.5 text-ink-3" aria-hidden />
                Next: {p.upcoming_meeting.title} · {relShort(p.upcoming_meeting.start_at, now) || fmtDateTime(p.upcoming_meeting.start_at)} — prepare brief
              </Link>
            ) : (
              <p className="text-ink-3">No upcoming meeting.</p>
            )}
            <div className="flex flex-wrap gap-x-3 gap-y-1.5">
              {p.members.map((m) => (
                <Link key={m.id} href={`/people/${m.id}`} className="inline-flex items-center gap-1.5 text-ink-2 hover:text-accent">
                  <Avatar name={m.name} className="h-5 w-5 text-[9px]" />
                  {m.is_self ? 'You' : m.name}
                </Link>
              ))}
            </div>
          </div>
        </Card>
      </div>

      <div className="scrollbar-thin mb-4 overflow-x-auto">
        <Tabs
          value={tab}
          onChange={setTab}
          className="min-w-max"
          tabs={[
            { value: 'overview', label: 'Overview' },
            { value: 'tasks', label: 'Tasks', count: tasks.length },
            { value: 'commitments', label: 'Commitments', count: p.commitments.length },
            { value: 'decisions', label: 'Decisions', count: p.decisions.length },
            { value: 'meetings', label: 'Meetings', count: p.meetings.length },
            { value: 'emails', label: 'Emails', count: p.emails.length },
            { value: 'documents', label: 'Documents', count: p.documents.length },
            { value: 'notes', label: 'Notes', count: p.notes.length },
          ]}
        />
      </div>

      <div role="tabpanel">
        {tab === 'overview' && (
          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="What changed" description="Facts tracked over time. Superseded values stay visible with the dates they were true." />
              <FactsHistory facts={p.facts} />
            </Card>
            <Card>
              <CardHeader title="Timeline" description="Most recent first." />
              <div className="scrollbar-thin max-h-[560px] overflow-y-auto">
                <ProjectTimeline items={p.timeline} now={now} />
              </div>
            </Card>
          </div>
        )}
        {tab === 'tasks' && (
          <Card>
            <CardHeader title="Tasks" action={<NewTaskButton defaultProjectId={p.id} variant="secondary" />} />
            {tasks.length === 0 ? (
              <EmptyState title="No tasks for this project" />
            ) : (
              <ul className="divide-y divide-line px-4">
                {tasks.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <TaskLine task={t} now={now} showProject={false} />
                    </div>
                    {t.status !== 'suggested' && (
                      <div className="py-2.5">
                        <TaskInlineEdit task={t} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
        {tab === 'commitments' && (
          <Card>
            <CardHeader title="Commitments" description="Select one to see the evidence, why it has this status, and to correct it." />
            {p.commitments.length === 0 ? (
              <EmptyState title="No commitments for this project" />
            ) : (
              <ul className="divide-y divide-line">
                {[...openCommitments, ...closedCommitments].map((c) => (
                  <li key={c.id}>
                    <button onClick={() => setOpenC(c.id)} className="block w-full px-4 py-3 text-left hover:bg-surface-2">
                      <CommitmentSummary c={c} now={now} showProject={false} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
        {tab === 'decisions' && (
          <Card>
            <CardHeader title="Decisions" action={<Link href={`/decisions?project=${p.id}`} className="text-xs text-accent hover:underline">History and corrections</Link>} />
            <DecisionsList items={p.decisions} />
          </Card>
        )}
        {tab === 'meetings' && (
          <Card>
            <MeetingsList items={p.meetings} now={now} />
          </Card>
        )}
        {tab === 'emails' && (
          <Card>
            <EmailsList items={p.emails} now={now} />
          </Card>
        )}
        {tab === 'documents' && (
          <Card>
            <DocumentsList items={p.documents} />
          </Card>
        )}
        {tab === 'notes' && (
          <Card>
            <NotesList items={p.notes} />
          </Card>
        )}
      </div>
      {openC && <CommitmentDrawer id={openC} now={now} onClose={() => setOpenC(null)} onOpen={setOpenC} />}
    </div>
  )
}
