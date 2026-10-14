'use client'

import { CalendarDays, FolderKanban, Plus } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useId, useState } from 'react'

import { Avatar, StatusBadge } from '@/components/ui/ai'
import { Button, Card, Dialog, EmptyState, ErrorState, Input, Label, LoadingRows, PageHeader, Textarea } from '@/components/ui/primitives'
import { HEALTH_EXPLAINER, HealthSignals, relShort, useNow, useProjects, useWorkMutation } from '@/components/work/shared'
import { post } from '@/lib/api'
import type { ProjectSummary } from '@/lib/types'
import { cn, fmtDateTime } from '@/lib/utils'

export default function ProjectsPage() {
  const q = useProjects()
  const now = useNow()
  const [creating, setCreating] = useState(false)
  const items = q.data?.items ?? []
  const active = items.filter((p) => !p.archived)
  const archived = items.filter((p) => p.archived)
  return (
    <div>
      <PageHeader
        title="Projects"
        description={HEALTH_EXPLAINER.replace('Heuristic: ', 'Health is a heuristic, shown with the signals behind it: ')}
        actions={
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus className="h-3.5 w-3.5" /> New project
          </Button>
        }
      />
      {q.isLoading ? (
        <Card>
          <LoadingRows rows={6} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FolderKanban className="h-4 w-4" />}
            title="No projects yet"
            description="Create a project with a few keywords. Threadline will suggest which emails, meetings and documents belong to it."
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                <Plus className="h-3.5 w-3.5" /> New project
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {active.map((p) => (
              <ProjectCard key={p.id} p={p} now={now} />
            ))}
          </ul>
          {archived.length > 0 && (
            <>
              <h2 className="mb-2 mt-8 text-xs font-semibold uppercase tracking-wide text-ink-3">Archived</h2>
              <ul className="grid gap-4 opacity-75 md:grid-cols-2 xl:grid-cols-3">
                {archived.map((p) => (
                  <ProjectCard key={p.id} p={p} now={now} />
                ))}
              </ul>
            </>
          )}
        </>
      )}
      {creating && <NewProjectDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

function ProjectCard({ p, now }: { p: ProjectSummary; now: string | undefined }) {
  return (
    <li>
      <Card className="flex h-full flex-col">
        <div className="border-b border-line px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <Link href={`/projects/${p.id}`} className="inline-flex min-w-0 items-center gap-2 text-base font-semibold text-ink hover:text-accent">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: p.color ?? 'var(--ink-3)' }} aria-hidden />
              <span className="truncate">{p.name}</span>
            </Link>
            <StatusBadge status={p.health.status} />
          </div>
          {p.description && <p className="mt-1 line-clamp-2 text-xs text-ink-2">{p.description}</p>}
        </div>
        <div className="flex-1 px-4 py-3">
          <div className="mb-1.5 flex items-baseline justify-between text-[11px] text-ink-3">
            <span>{p.status_manual ? 'Set manually' : 'Why this status'}</span>
            <span className="tabular-nums" title="Risk score: the sum of signal weights, capped at 1">
              risk {p.health.score.toFixed(2)}
            </span>
          </div>
          <HealthSignals signals={p.health.signals} compact />
        </div>
        <dl className="grid grid-cols-3 border-t border-line text-center">
          <Metric label="Open tasks" value={p.open_tasks} />
          <Metric label="Overdue" value={p.overdue_commitments} tone={p.overdue_commitments > 0 ? 'text-danger' : undefined} />
          <Metric label="Decisions" value={p.decisions} />
        </dl>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5 text-xs">
          {p.upcoming_meeting ? (
            <Link href={`/calendar?event=${p.upcoming_meeting.id}&brief=1`} className="inline-flex min-w-0 items-center gap-1.5 text-ink-2 hover:text-accent" title="Open the meeting brief">
              <CalendarDays className="h-3.5 w-3.5 shrink-0 text-ink-3" aria-hidden />
              <span className="truncate">
                {p.upcoming_meeting.title} · {relShort(p.upcoming_meeting.start_at, now) || fmtDateTime(p.upcoming_meeting.start_at)}
              </span>
            </Link>
          ) : (
            <span className="text-ink-3">No upcoming meeting</span>
          )}
          <span className="flex -space-x-1" aria-label={`${p.members.length} members: ${p.members.map((m) => m.name).join(', ')}`}>
            {p.members.slice(0, 5).map((m) => (
              <span key={m.id} title={m.name}>
                <Avatar name={m.name} className="h-6 w-6 ring-2 ring-surface" />
              </span>
            ))}
            {p.members.length > 5 && <span className="flex h-6 w-6 items-center justify-center rounded-full bg-sunken text-[10px] text-ink-3 ring-2 ring-surface">+{p.members.length - 5}</span>}
          </span>
        </div>
      </Card>
    </li>
  )
}

function Metric({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="border-r border-line px-2 py-2 last:border-r-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className={cn('text-lg font-semibold tabular-nums', tone ?? 'text-ink')}>{value}</dd>
    </div>
  )
}

const PALETTE = ['#4f6bed', '#d9822b', '#2f9e72', '#b5478b', '#7a5af5', '#2a8fbd', '#c2513b', '#6b7a3a']

function NewProjectDialog({ onClose }: { onClose: () => void }) {
  const id = useId()
  const router = useRouter()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [keywords, setKeywords] = useState('')
  const [color, setColor] = useState(PALETTE[0])
  const m = useWorkMutation(
    () =>
      post<ProjectSummary>('/api/projects', {
        name: name.trim(),
        description: description.trim() || null,
        keywords: keywords
          .split(',')
          .map((k) => k.trim())
          .filter(Boolean),
        color,
      }),
    (p) => `Created ${p.name}`,
  )
  const submit = () => name.trim() && m.mutate(undefined, { onSuccess: (p) => router.push(`/projects/${p.id}`) })
  return (
    <Dialog
      open
      onClose={onClose}
      title="New project"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!name.trim()} loading={m.isPending} onClick={submit}>
            Create project
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <div>
          <Label htmlFor={`${id}-n`}>Name</Label>
          <Input id={`${id}-n`} value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus placeholder="e.g. Atlas" />
        </div>
        <div>
          <Label htmlFor={`${id}-d`} hint="optional">
            Description
          </Label>
          <Textarea id={`${id}-d`} rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div>
          <Label htmlFor={`${id}-k`} hint="comma-separated">
            Keywords
          </Label>
          <Input id={`${id}-k`} value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="migration, cutover, backfill" />
          <p className="mt-1 text-[11px] text-ink-3">Used, with participants, to suggest which items belong here. Suggestions always ask before filing.</p>
        </div>
        <fieldset>
          <legend className="mb-1 block text-xs font-medium text-ink-2">Colour</legend>
          <div className="flex flex-wrap gap-1.5">
            {PALETTE.map((c) => (
              <button
                key={c}
                type="button"
                aria-label={`Colour ${c}`}
                aria-pressed={color === c}
                onClick={() => setColor(c)}
                className={cn('h-6 w-6 rounded-full ring-offset-2 ring-offset-surface', color === c && 'ring-2 ring-ink')}
                style={{ background: c }}
              />
            ))}
          </div>
        </fieldset>
        <button type="submit" className="hidden" aria-hidden tabIndex={-1} />
      </form>
    </Dialog>
  )
}
