'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Mail, Pencil, Scissors, Workflow } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { EmploymentTimeline } from '@/components/memory/employment-timeline'
import { kindMeta } from '@/components/memory/kinds'
import { CommitmentRow, DecisionRow, TaskRow } from '@/components/memory/records'
import { RefLink } from '@/components/memory/ref-link'
import { useWorkspaceNow } from '@/components/memory/use-now'
import { useToast } from '@/components/toast'
import { Avatar, EvidenceChip, ProjectChip } from '@/components/ui/ai'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Input, Label, LoadingRows, Tabs, Textarea } from '@/components/ui/primitives'
import { errorMessage, get, patch, post } from '@/lib/api'
import type { PersonDetail, PersonResponse } from '@/lib/types-memory'
import { fmtDate, fmtDateTime, relDays } from '@/lib/utils'

type Tab = 'commitments' | 'emails' | 'meetings' | 'decisions' | 'tasks' | 'timeline'

export default function PersonPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const q = useQuery({ queryKey: ['person', id], queryFn: () => get<PersonResponse>(`/api/people/${id}`) })
  const redirect = q.data && 'redirect' in q.data ? q.data.redirect : null
  useEffect(() => {
    if (redirect) router.replace(`/people/${redirect}`)
  }, [redirect, router])

  if (q.isLoading || redirect) {
    return (
      <div>
        {redirect && <p className="mb-2 text-xs text-ink-3">This person was merged into another profile. Redirecting…</p>}
        <LoadingRows rows={8} />
      </div>
    )
  }
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  return <Profile p={q.data as PersonDetail} />
}

function Profile({ p }: { p: PersonDetail }) {
  const now = useWorkspaceNow()
  const [tab, setTab] = useState<Tab>('commitments')
  const [editing, setEditing] = useState(false)

  return (
    <div className="animate-fade-in">
      <Link href="/people" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-accent">
        <ArrowLeft className="h-3 w-3" /> People
      </Link>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={p.name} className="h-11 w-11 text-sm" />
          <div className="min-w-0">
            <h1 className="font-serif text-[26px] font-medium leading-tight tracking-tight text-ink">
              {p.name}
              {p.is_self && <span className="ml-2 align-middle text-sm font-normal text-ink-3">(you)</span>}
            </h1>
            <p className="mt-0.5 text-sm text-ink-2">
              {[p.title, p.organization].filter(Boolean).join(' · ') || 'No title or organization yet'}
            </p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-ink-3">
              {p.email && (
                <span className="inline-flex items-center gap-1">
                  <Mail className="h-3 w-3" aria-hidden /> {p.email}
                </span>
              )}
              {p.last_interaction_at && <span>Last interaction {relDays(p.last_interaction_at, now)}</span>}
              {p.created_by && <span>Added from {p.created_by}</span>}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={`/graph?focus=person:${p.id}`} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken">
            <Workflow className="h-3.5 w-3.5" /> View in graph
          </Link>
          <Button onClick={() => setEditing(true)}>
            <Pencil className="h-3.5 w-3.5" /> Edit
          </Button>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          <div className="grid gap-5 md:grid-cols-2">
            <Card>
              <CardHeader title="Waiting on them" description="Open promises they made to you or others." action={<Badge tone={p.waiting_on_them.length ? 'info' : 'neutral'}>{p.waiting_on_them.length}</Badge>} />
              {p.waiting_on_them.length === 0 ? (
                <EmptyState title="Nothing outstanding" description="They have no open commitments." />
              ) : (
                <ul className="divide-y divide-line">
                  {p.waiting_on_them.map((c) => (
                    <CommitmentRow key={c.id} c={c} now={now} showPeople={false} />
                  ))}
                </ul>
              )}
            </Card>
            <Card>
              <CardHeader title="You owe them" description="Open promises you made to them." action={<Badge tone={p.you_owe_them.length ? 'warning' : 'neutral'}>{p.you_owe_them.length}</Badge>} />
              {p.you_owe_them.length === 0 ? (
                <EmptyState title="You’re all square" description="No open commitments from you to them." />
              ) : (
                <ul className="divide-y divide-line">
                  {p.you_owe_them.map((c) => (
                    <CommitmentRow key={c.id} c={c} now={now} showPeople={false} />
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card>
            <Tabs<Tab>
              className="overflow-x-auto px-2"
              value={tab}
              onChange={setTab}
              tabs={[
                { value: 'commitments', label: 'Commitments', count: p.commitments.length },
                { value: 'emails', label: 'Emails', count: p.emails.length },
                { value: 'meetings', label: 'Meetings', count: p.meetings.length },
                { value: 'decisions', label: 'Decisions', count: p.decisions.length },
                { value: 'tasks', label: 'Tasks', count: p.tasks.length },
                { value: 'timeline', label: 'Timeline', count: p.timeline.length },
              ]}
            />
            <div role="tabpanel">
              {tab === 'commitments' &&
                (p.commitments.length === 0 ? (
                  <EmptyState title="No commitments involving them" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.commitments.map((c) => (
                      <CommitmentRow key={c.id} c={c} now={now} />
                    ))}
                  </ul>
                ))}
              {tab === 'emails' &&
                (p.emails.length === 0 ? (
                  <EmptyState title="No emails with them yet" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.emails.map((e) => (
                      <li key={e.id} className="px-4 py-2.5">
                        <div className="flex items-center justify-between gap-2">
                          <EvidenceChip type="email" id={e.id} label={e.subject || '(no subject)'} className="border-transparent bg-transparent px-0 text-sm text-ink" />
                          <span className="shrink-0 text-xs tabular-nums text-ink-3">{fmtDate(e.sent_at, { month: 'short', day: 'numeric' })}</span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-2">
                          <Badge tone="neutral">{e.direction === 'inbound' ? `From ${e.from_name ?? e.from_addr}` : 'You sent'}</Badge>
                          <ProjectChip project={e.project} />
                          <span className="truncate text-xs text-ink-3">{e.snippet}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                ))}
              {tab === 'meetings' &&
                (p.meetings.length === 0 ? (
                  <EmptyState title="No shared meetings" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.meetings.map((m) => (
                      <li key={m.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                        <div className="min-w-0">
                          <Link href={`/calendar?event=${m.id}`} className="block truncate text-sm text-ink hover:text-accent">
                            {m.title}
                          </Link>
                          <span className="block truncate text-xs text-ink-3">{m.attendees.map((a) => a.name || a.email).join(', ')}</span>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <ProjectChip project={m.project} />
                          <span className="text-xs tabular-nums text-ink-3">{fmtDateTime(m.start_at)}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                ))}
              {tab === 'decisions' &&
                (p.decisions.length === 0 ? (
                  <EmptyState title="No decisions they took part in" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.decisions.map((d) => (
                      <DecisionRow key={d.id} d={d} />
                    ))}
                  </ul>
                ))}
              {tab === 'tasks' &&
                (p.tasks.length === 0 ? (
                  <EmptyState title="No tasks owned by or blocked on them" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.tasks.map((t) => (
                      <TaskRow key={t.id} t={t} now={now} />
                    ))}
                  </ul>
                ))}
              {tab === 'timeline' &&
                (p.timeline.length === 0 ? (
                  <EmptyState title="No timeline events yet" />
                ) : (
                  <ul className="divide-y divide-line">
                    {p.timeline.map((t, i) => {
                      const k = kindMeta(t.kind)
                      return (
                        <li key={`${t.ref.id}-${i}`} className="flex items-start gap-3 px-4 py-2.5">
                          <span className="mt-0.5 w-20 shrink-0 text-[11px] tabular-nums text-ink-3">{fmtDate(t.occurred_at, { month: 'short', day: 'numeric' })}</span>
                          <Badge tone={k.tone}>{k.label}</Badge>
                          <RefLink type={t.ref.type} id={t.ref.id} label={t.title} className="min-w-0 text-sm" />
                        </li>
                      )
                    })}
                  </ul>
                ))}
            </div>
          </Card>
        </div>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="Employment history" description="Each period is a time-bounded fact; a job change closes the previous one rather than overwriting it." />
            <EmploymentTimeline rows={p.employment} />
          </Card>

          <Card>
            <CardHeader title="Projects" />
            {p.projects.length === 0 ? (
              <p className="px-4 py-4 text-xs text-ink-3">Not linked to any project yet.</p>
            ) : (
              <div className="flex flex-wrap gap-1.5 px-4 py-3">
                {p.projects.map((pr) => (
                  <ProjectChip key={pr.id} project={pr} />
                ))}
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Your notes" action={<Button size="sm" variant="ghost" onClick={() => setEditing(true)} aria-label="Edit notes"><Pencil className="h-3 w-3" /></Button>} />
            <p className="whitespace-pre-wrap px-4 py-3 text-sm text-ink-2">{p.notes || <span className="text-ink-3">No notes. Add context only you know.</span>}</p>
          </Card>

          <AliasesCard p={p} />
        </div>
      </div>

      <EditDialog p={p} open={editing} onClose={() => setEditing(false)} />
    </div>
  )
}

function AliasesCard({ p }: { p: PersonDetail }) {
  const [selected, setSelected] = useState<string[]>([])
  const [confirm, setConfirm] = useState(false)
  const [newName, setNewName] = useState('')
  const qc = useQueryClient()
  const toast = useToast()
  const router = useRouter()
  const split = useMutation({
    mutationFn: () => post<{ ok: boolean; id: string }>(`/api/people/${p.id}/split`, { alias_ids: selected, new_name: newName.trim() || null }),
    onSuccess: (r) => {
      toast('Split into a new person.')
      setConfirm(false)
      setSelected([])
      qc.invalidateQueries({ queryKey: ['people'] })
      qc.invalidateQueries({ queryKey: ['person'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
      router.push(`/people/${r.id}`)
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]))
  const canSplit = selected.length > 0 && selected.length < p.aliases.length
  return (
    <Card>
      <CardHeader title="Names & addresses" description="Every alias Threadline resolved to this person. If some belong to someone else, split them off." />
      {p.aliases.length === 0 ? (
        <p className="px-4 py-4 text-xs text-ink-3">No aliases recorded.</p>
      ) : (
        <fieldset className="px-4 py-3">
          <legend className="sr-only">Select aliases to split</legend>
          <ul className="space-y-1.5">
            {p.aliases.map((a) => (
              <li key={a.id}>
                <label className="flex cursor-pointer items-center gap-2 text-sm text-ink">
                  <input type="checkbox" className="h-3.5 w-3.5 accent-[var(--accent)]" checked={selected.includes(a.id)} onChange={() => toggle(a.id)} />
                  <span className="min-w-0 truncate">{a.alias}</span>
                  <Badge tone="neutral">{a.kind}</Badge>
                </label>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button size="sm" disabled={!canSplit} onClick={() => setConfirm(true)}>
              <Scissors className="h-3 w-3" /> Split selected aliases into a new person
            </Button>
            {selected.length > 0 && selected.length === p.aliases.length && <span className="text-[11px] text-warning">Leave at least one alias on this person.</span>}
          </div>
        </fieldset>
      )}
      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Split into a new person"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button variant="primary" loading={split.isPending} onClick={() => split.mutate()}>
              Split
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">
          These aliases will move to a new person. Emails sent from a moved address are reassigned to the new person too:
        </p>
        <ul className="my-2 flex flex-wrap gap-1">
          {p.aliases.filter((a) => selected.includes(a.id)).map((a) => (
            <Badge key={a.id} tone="accent">
              {a.alias}
            </Badge>
          ))}
        </ul>
        <Label htmlFor="split-name" hint="(optional)">
          Name for the new person
        </Label>
        <Input id="split-name" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Ahmed Khan (personal)" />
        <p className="mt-2 text-[11px] text-ink-3">This is recorded as a correction, so future processing won’t merge them again.</p>
      </Dialog>
    </Card>
  )
}

function EditDialog({ p, open, onClose }: { p: PersonDetail; open: boolean; onClose: () => void }) {
  const [name, setName] = useState(p.name)
  const [title, setTitle] = useState(p.title ?? '')
  const [notes, setNotes] = useState(p.notes ?? '')
  useEffect(() => {
    if (open) {
      setName(p.name)
      setTitle(p.title ?? '')
      setNotes(p.notes ?? '')
    }
  }, [open, p])
  const qc = useQueryClient()
  const toast = useToast()
  const save = useMutation({
    mutationFn: () => patch(`/api/people/${p.id}`, { display_name: name.trim() || p.name, title: title.trim() || null, notes: notes.trim() || null }),
    onSuccess: () => {
      toast('Profile saved.')
      qc.invalidateQueries({ queryKey: ['person', p.id] })
      qc.invalidateQueries({ queryKey: ['people'] })
      onClose()
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Edit ${p.name}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div>
          <Label htmlFor="pe-name">Display name</Label>
          <Input id="pe-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
        </div>
        <div>
          <Label htmlFor="pe-title">Title</Label>
          <Input id="pe-title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} placeholder="e.g. VP Engineering" />
        </div>
        <div>
          <Label htmlFor="pe-notes" hint="private to you">
            Notes
          </Label>
          <Textarea id="pe-notes" rows={5} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      </form>
    </Dialog>
  )
}
