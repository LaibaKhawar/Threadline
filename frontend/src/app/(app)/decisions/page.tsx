'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowDown, Check, GitBranch, Pencil, Search } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useId, useState } from 'react'

import { Avatar, Confidence, EvidenceChip, ProjectChip, Quote, StatusBadge } from '@/components/ui/ai'
import { Badge, Button, Card, EmptyState, ErrorState, Input, Label, LoadingRows, PageHeader, Select } from '@/components/ui/primitives'
import { sourceLabel } from '@/components/work/commitments'
import { useProjects, useWorkMutation } from '@/components/work/shared'
import { get, patch } from '@/lib/api'
import type { Decision } from '@/lib/types'
import { cn, fmtDate } from '@/lib/utils'

export default function DecisionsPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <DecisionsView />
    </Suspense>
  )
}

function DecisionsView() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const project = sp.get('project') ?? ''
  const status = sp.get('status') ?? ''
  const topicParam = sp.get('topic') ?? ''
  const [topic, setTopic] = useState(topicParam)
  const projects = useProjects()
  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp.toString())
    if (v) next.set(k, v)
    else next.delete(k)
    router.replace(`${pathname}${next.toString() ? `?${next}` : ''}`, { scroll: false })
  }
  useEffect(() => {
    if (topic === topicParam) return
    const t = setTimeout(() => setParam('topic', topic.trim()), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topic])

  const params = new URLSearchParams()
  if (project) params.set('project_id', project)
  if (status) params.set('status', status)
  if (topicParam) params.set('topic', topicParam)
  const q = useQuery({ queryKey: ['decisions', params.toString()], queryFn: () => get<{ items: Decision[] }>(`/api/decisions?${params}`) })

  const groups = new Map<string, Decision[]>()
  for (const d of q.data?.items ?? []) groups.set(d.topic, [...(groups.get(d.topic) ?? []), d])
  const ordered = [...groups.entries()]
    .map(([t, list]) => [t, [...list].sort((a, b) => a.decided_at.localeCompare(b.decided_at))] as const)
    .sort((a, b) => b[1][b[1].length - 1].decided_at.localeCompare(a[1][a[1].length - 1].decided_at))

  return (
    <div>
      <PageHeader title="Decisions" description="What was decided, when, by whom, and what it replaced. Grouped by topic so you can see how a choice changed over time." />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
          <label htmlFor="d-topic" className="sr-only">
            Filter by topic
          </label>
          <Input id="d-topic" className="pl-8" placeholder="Filter by topic" value={topic} onChange={(e) => setTopic(e.target.value)} />
        </div>
        <label htmlFor="d-project" className="sr-only">
          Project
        </label>
        <Select id="d-project" value={project} onChange={(e) => setParam('project', e.target.value)}>
          <option value="">All projects</option>
          {projects.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
        <label htmlFor="d-status" className="sr-only">
          Status
        </label>
        <Select id="d-status" value={status} onChange={(e) => setParam('status', e.target.value)}>
          <option value="">Any status</option>
          <option value="active">Active</option>
          <option value="superseded">Superseded</option>
          <option value="rejected">Rejected</option>
        </Select>
      </div>

      {q.isLoading ? (
        <Card>
          <LoadingRows rows={8} />
        </Card>
      ) : q.error || !q.data ? (
        <Card>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Card>
      ) : ordered.length === 0 ? (
        <Card>
          <EmptyState icon={<GitBranch className="h-4 w-4" />} title={project || status || topicParam ? 'No decisions match these filters' : 'No decisions recorded yet'} description="Decisions are picked up from phrases like “we’ve decided to…” in email and meeting notes." />
        </Card>
      ) : (
        <div className="space-y-5">
          {ordered.map(([t, list]) => {
            const current = [...list].reverse().find((d) => d.status === 'active')
            return (
              <Card key={t}>
                <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line px-4 py-3">
                  <h2 className="text-sm font-semibold capitalize text-ink">{t}</h2>
                  <span className="text-xs text-ink-3">
                    {current ? (
                      <>
                        Current: <span className="font-medium text-ink">{current.chosen}</span>
                      </>
                    ) : (
                      'No active decision'
                    )}
                    {list.length > 1 && <> · {list.length} decisions</>}
                  </span>
                </header>
                <ol className="px-4 py-3">
                  {list.map((d, i) => (
                    <li key={d.id}>
                      {i > 0 && (
                        <div className="my-1 flex items-center gap-2 pl-3 text-[11px] text-ink-3">
                          <ArrowDown className="h-3 w-3" aria-hidden />
                          {list[i - 1].superseded_by_id === d.id ? 'superseded by' : 'later'}
                        </div>
                      )}
                      <DecisionNode d={d} supersededBy={list.find((x) => x.id === d.superseded_by_id)} />
                    </li>
                  ))}
                </ol>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}

function DecisionNode({ d, supersededBy }: { d: Decision; supersededBy?: Decision }) {
  const [editing, setEditing] = useState(false)
  const superseded = d.status !== 'active'
  // the extractor sometimes records the decision's own source sentence as a reaffirmation; hide that duplicate
  const reaffirmed = (d.reaffirmed ?? []).filter((r) => !(r.source_id === d.source.id && r.span === d.source.span))
  const confirm = useWorkMutation(() => patch<Decision>(`/api/decisions/${d.id}`, { status: d.status }), 'Decision confirmed')
  return (
    <article className={cn('rounded-md border p-3', superseded ? 'border-line bg-surface-2' : 'border-line-strong')}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={d.status} />
            <span className={cn('text-base font-semibold', superseded ? 'text-ink-3 line-through' : 'text-ink')}>{d.chosen}</span>
            {d.rejected.length > 0 && <span className="text-xs text-ink-3">over {d.rejected.join(', ')}</span>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
            <time dateTime={d.decided_at}>{fmtDate(d.decided_at)}</time>
            <ProjectChip project={d.project} />
            <Confidence value={d.confidence} label="extraction confidence" />
            {d.user_confirmed && <Badge tone="accent">Confirmed by you</Badge>}
            {supersededBy && (
              <span>
                Replaced by <span className="font-medium text-ink-2">{supersededBy.chosen}</span> on {fmtDate(supersededBy.decided_at)}
              </span>
            )}
          </div>
        </div>
        <div className="flex gap-1">
          {!d.user_confirmed && (
            <Button size="sm" variant="ghost" loading={confirm.isPending} onClick={() => confirm.mutate(undefined)} aria-label={`Confirm decision ${d.chosen}`}>
              <Check className="h-3 w-3" /> Confirm
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setEditing((v) => !v)} aria-expanded={editing} aria-label={`Correct decision ${d.chosen}`}>
            <Pencil className="h-3 w-3" /> Correct
          </Button>
        </div>
      </div>

      <div className="mt-2.5">
        <Quote className="not-italic text-sm text-ink-2">{d.statement}</Quote>
        <div className="mt-1.5">
          <EvidenceChip type={d.source.type} id={d.source.id} span={d.source.span} label={sourceLabel(d.source.type, d.decided_at)} />
        </div>
      </div>

      {reaffirmed.length > 0 && (
        <div className="mt-3">
          <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-ink-3">Reaffirmed {reaffirmed.length}×</p>
          <ul className="space-y-1.5">
            {reaffirmed.map((r, i) => (
              <li key={`${r.source_id}-${i}`} className="text-xs">
                <Quote>{r.span}</Quote>
                <div className="mt-1">
                  <EvidenceChip type={r.source_type} id={r.source_id} span={r.span} label={sourceLabel(r.source_type, r.observed_at)} />
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {d.participants.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-2">
          <span className="text-ink-3">Participants</span>
          {d.participants.map((p) => (
            <span key={p.id} className="inline-flex items-center gap-1">
              <Avatar name={p.name} className="h-5 w-5 text-[9px]" />
              {p.is_self ? 'You' : p.name}
            </span>
          ))}
        </div>
      )}

      {editing && <CorrectDecision d={d} onDone={() => setEditing(false)} />}
    </article>
  )
}

function CorrectDecision({ d, onDone }: { d: Decision; onDone: () => void }) {
  const id = useId()
  const [topic, setTopic] = useState(d.topic)
  const [chosen, setChosen] = useState(d.chosen)
  const [status, setStatus] = useState(d.status)
  const m = useWorkMutation(
    () => {
      const body: Partial<Pick<Decision, 'topic' | 'chosen' | 'status'>> = {}
      if (topic.trim() !== d.topic) body.topic = topic.trim()
      if (chosen.trim() !== d.chosen) body.chosen = chosen.trim()
      if (status !== d.status) body.status = status
      return patch<Decision>(`/api/decisions/${d.id}`, body)
    },
    'Decision corrected',
  )
  const changed = topic.trim() !== d.topic || chosen.trim() !== d.chosen || status !== d.status
  return (
    <form
      className="mt-3 rounded-md border border-line bg-surface p-3"
      onSubmit={(e) => {
        e.preventDefault()
        if (changed && topic.trim() && chosen.trim()) m.mutate(undefined, { onSuccess: onDone })
      }}
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <Label htmlFor={`${id}-t`}>Topic</Label>
          <Input id={`${id}-t`} value={topic} onChange={(e) => setTopic(e.target.value)} required />
        </div>
        <div>
          <Label htmlFor={`${id}-c`}>What was chosen</Label>
          <Input id={`${id}-c`} value={chosen} onChange={(e) => setChosen(e.target.value)} required />
        </div>
        <div>
          <Label htmlFor={`${id}-s`}>Status</Label>
          <Select id={`${id}-s`} className="w-full" value={status} onChange={(e) => setStatus(e.target.value as Decision['status'])}>
            <option value="active">Active</option>
            <option value="superseded">Superseded</option>
            <option value="rejected">Rejected (not a decision)</option>
          </Select>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2">
        <p className="text-[11px] text-ink-3">Your correction is recorded and outranks the extractor.</p>
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" type="button" onClick={onDone}>
            Cancel
          </Button>
          <Button size="sm" variant="primary" type="submit" disabled={!changed} loading={m.isPending}>
            Save
          </Button>
        </div>
      </div>
    </form>
  )
}
