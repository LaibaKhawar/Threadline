'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Ban, Check, CircleSlash, Link2, RotateCcw, X } from 'lucide-react'
import { type ReactNode, useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'

import { Confidence, EvidenceChip, Quote, StatusBadge } from '@/components/ui/ai'
import { Badge, Button, ErrorState, LoadingRows, Select } from '@/components/ui/primitives'
import { get, patch, post } from '@/lib/api'
import type { Commitment, CommitmentStatus } from '@/lib/types'
import type { CommitmentDetail, CommitmentList, FulfillmentCandidate } from '@/lib/types-work'
import { SOURCE_LABEL, cn, fmtDate, pct } from '@/lib/utils'

import { DueText, ProjectTag, SectionLabel, fromDateInput, personName, toDateInput, usePeople, useWorkMutation } from './shared'

export const KIND_LABEL: Record<string, string> = { commitment: 'Commitment', request: 'Request', intention: 'Intention' }
const KIND_HINT: Record<string, string> = {
  commitment: 'Someone promised to do something',
  request: 'Someone asked someone else to do something',
  intention: 'A softer “I plan to / might” statement',
}

export function sourceLabel(type: string | null | undefined, at?: string | null) {
  return `${SOURCE_LABEL[type ?? ''] ?? type ?? 'Source'}${at ? ` · ${fmtDate(at, { month: 'short', day: 'numeric' })}` : ''}`
}

/** "Ahmed Khan → You" */
export function ActorRecipient({ c }: { c: Commitment }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1 text-ink-2">
      <span className="truncate">{personName(c.actor, c.actor_text)}</span>
      {c.recipient && (
        <>
          <ArrowRight className="h-3 w-3 shrink-0 text-ink-3" aria-label="to" />
          <span className="truncate">{personName(c.recipient)}</span>
        </>
      )}
    </span>
  )
}

/** One-line commitment summary used in lists (thread side panel, project tab, commitments page). */
export function CommitmentSummary({ c, now, showProject = true }: { c: Commitment; now: string | undefined; showProject?: boolean }) {
  const closed = ['FULFILLED', 'CANCELLED', 'REJECTED'].includes(c.status)
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={c.status} />
        <span className={cn('text-sm font-medium', closed ? 'text-ink-2' : 'text-ink')}>{c.description}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <ActorRecipient c={c} />
        <span className="text-ink-3" title={KIND_HINT[c.kind]}>
          {KIND_LABEL[c.kind] ?? c.kind}
        </span>
        <DueText due={c.due_at} now={now} done={closed} />
        <Confidence value={c.confidence} label="extraction confidence" />
        {showProject && <ProjectTag project={c.project} />}
        {c.user_modified && <Badge tone="accent">Corrected by you</Badge>}
      </div>
    </div>
  )
}

const ROLE_LABEL: Record<string, { label: string; tone: 'neutral' | 'info' | 'success' | 'warning' | 'accent' }> = {
  source: { label: 'Original statement', tone: 'neutral' },
  reaffirmed: { label: 'Reaffirmed', tone: 'info' },
  fulfillment: { label: 'Fulfilment', tone: 'success' },
  change: { label: 'Change', tone: 'warning' },
}

function whyTitle(status: CommitmentStatus) {
  if (status === 'OVERDUE') return 'Why this is marked overdue'
  if (status === 'FULFILLED') return 'Why this is marked fulfilled'
  if (status === 'CANCELLED') return 'Why this is marked cancelled'
  if (status === 'UNCERTAIN') return 'Why this is uncertain'
  return 'Current assessment'
}

function fallbackReason(c: Commitment) {
  if (c.status === 'OVERDUE' && c.due_at) return `It was due ${fmtDate(c.due_at)} and no later email, meeting note or document was found that delivers it.`
  if (c.status === 'OPEN') return c.due_at ? `Due ${fmtDate(c.due_at)}. Nothing that fulfils it has been found yet.` : 'No due date was stated. Nothing that fulfils it has been found yet.'
  if (c.user_modified) return 'Status set by your correction.'
  return null
}

/** Full detail for one commitment: evidence, due history, fulfilment candidates, dependencies and corrections. */
export function CommitmentDetailView({ id, now, onOpen, onClose }: { id: string; now: string | undefined; onOpen?: (id: string) => void; onClose?: () => void }) {
  const q = useQuery({ queryKey: ['commitment', id], queryFn: () => get<CommitmentDetail>(`/api/commitments/${id}`) })
  const all = useQuery({ queryKey: ['commitments', 'all'], queryFn: () => get<CommitmentList>('/api/commitments') })
  if (q.isLoading) return <LoadingRows rows={6} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const c = q.data
  const reason = c.resolution?.reason ?? fallbackReason(c)
  const byId = new Map(all.data?.items.map((x) => [x.id, x]))
  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={c.status} />
            <Badge tone="neutral" title={KIND_HINT[c.kind]}>
              {KIND_LABEL[c.kind] ?? c.kind}
            </Badge>
            {c.user_modified && <Badge tone="accent">Corrected by you</Badge>}
          </div>
          {onClose && (
            <button onClick={onClose} aria-label="Close details" className="rounded p-1 text-ink-3 hover:bg-sunken hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
        <h2 className="mt-2 text-base font-semibold text-ink">{c.description}</h2>
        <dl className="mt-3 grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 text-xs">
          <dt className="text-ink-3">Who</dt>
          <dd>
            <ActorRecipient c={c} />
          </dd>
          <dt className="text-ink-3">Due</dt>
          <dd>
            <DueText due={c.due_at} now={now} done={['FULFILLED', 'CANCELLED', 'REJECTED'].includes(c.status)} />
            {c.due_text && <span className="text-ink-3"> · said “{c.due_text}”</span>}
          </dd>
          <dt className="text-ink-3">Detected</dt>
          <dd className="text-ink-2">
            {fmtDate(c.detected_at)} by the {c.extractor} extractor
          </dd>
          <dt className="text-ink-3">Confidence</dt>
          <dd>
            <Confidence value={c.confidence} label="extraction confidence" />
          </dd>
          {c.project && (
            <>
              <dt className="text-ink-3">Project</dt>
              <dd>
                <ProjectTag project={c.project} />
              </dd>
            </>
          )}
        </dl>
      </div>

      {reason && (
        <div className={cn('rounded-md border p-3 text-xs', c.status === 'OVERDUE' ? 'border-danger/30 bg-danger-wash' : 'border-line bg-sunken')}>
          <p className={cn('font-medium', c.status === 'OVERDUE' ? 'text-danger' : 'text-ink')}>{whyTitle(c.status)}</p>
          <p className="mt-1 leading-relaxed text-ink-2">{reason}</p>
          {c.resolution?.id && (
            <div className="mt-2 flex items-center gap-2">
              <EvidenceChip type={c.resolution.type} id={c.resolution.id} label={`${['FULFILLED', 'CANCELLED'].includes(c.status) ? 'Resolved by' : 'Closest match:'} ${sourceLabel(c.resolution.type, c.resolution.resolved_at)}`} />
              {c.resolution.confidence !== null && <Confidence value={c.resolution.confidence} label="match confidence" />}
            </div>
          )}
        </div>
      )}

      <Corrections c={c} />

      <section>
        <SectionLabel count={c.evidence.length}>Evidence</SectionLabel>
        {c.evidence.length === 0 ? (
          <p className="text-xs text-ink-3">No evidence rows recorded.</p>
        ) : (
          <ol className="space-y-2.5">
            {c.evidence.map((e, i) => {
              const r = ROLE_LABEL[e.role] ?? { label: e.role, tone: 'neutral' as const }
              return (
                <li key={`${e.source_id}-${i}`} className="rounded-md border border-line p-2.5">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <Badge tone={r.tone}>{r.label}</Badge>
                    <span className="text-[11px] text-ink-3">{e.observed_at ? fmtDate(e.observed_at) : ''}</span>
                    {e.confidence !== null && <Confidence value={e.confidence} />}
                  </div>
                  {e.span && <Quote>{e.span}</Quote>}
                  <div className="mt-1.5">
                    <EvidenceChip type={e.source_type} id={e.source_id} span={e.span && e.span !== 'Confirmed by user' ? e.span : undefined} label={sourceLabel(e.source_type, e.observed_at)} />
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </section>

      {c.due_history.length > 0 && (
        <section>
          <SectionLabel count={c.due_history.length}>Due-date history</SectionLabel>
          <ol className="space-y-2">
            {c.due_history.map((h, i) => (
              <li key={i} className="rounded-md border border-line p-2.5 text-xs">
                <div className="flex flex-wrap items-center gap-1.5 tabular-nums">
                  {h.old_due_at && h.old_due_at !== h.new_due_at && <span className="text-ink-3 line-through">{fmtDate(h.old_due_at)}</span>}
                  {h.old_due_at && h.old_due_at !== h.new_due_at && <ArrowRight className="h-3 w-3 text-ink-3" aria-label="moved to" />}
                  <span className="font-medium text-ink">{fmtDate(h.new_due_at)}</span>
                  {h.old_due_at === h.new_due_at && <span className="text-ink-3">(restated)</span>}
                  <span className="text-ink-3">· observed {fmtDate(h.observed_at)}</span>
                </div>
                {h.span && <Quote className="mt-1.5">{h.span}</Quote>}
                <div className="mt-1.5">
                  <EvidenceChip type={h.source_type} id={h.source_id} span={h.span} label={sourceLabel(h.source_type, h.observed_at)} />
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <SectionLabel count={c.candidates.length}>Possible fulfilments</SectionLabel>
        {c.candidates.length === 0 ? (
          <p className="text-xs text-ink-3">No later item looked like it delivers this. Fulfilments are found by matching later emails, notes and documents from the same person.</p>
        ) : (
          <ul className="space-y-2.5">
            {c.candidates.map((f) => (
              <CandidateRow key={f.id} cid={c.id} f={f} />
            ))}
          </ul>
        )}
      </section>

      {c.dependencies.length > 0 && (
        <section>
          <SectionLabel count={c.dependencies.length}>Dependencies</SectionLabel>
          <ul className="space-y-1.5">
            {c.dependencies.map((d) => {
              const [rel, other] = 'depends_on' in d ? ['Depends on', d.depends_on] : ['Required by', d.required_by]
              const o = byId.get(other)
              return (
                <li key={other} className="flex flex-wrap items-center gap-2 text-xs">
                  <Link2 className="h-3 w-3 text-ink-3" aria-hidden />
                  <span className="text-ink-3">{rel}</span>
                  {onOpen ? (
                    <button onClick={() => onOpen(other)} className="text-left text-accent hover:underline">
                      {o?.description ?? 'another commitment'}
                    </button>
                  ) : (
                    <span className="text-ink-2">{o?.description ?? 'another commitment'}</span>
                  )}
                  {o && <StatusBadge status={o.status} />}
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}

const SIGNAL_LABEL: Record<string, string> = {
  completion_statement: 'Completion statement',
  cancellation: 'Cancellation statement',
  object_overlap: 'Mentions',
  matching_attachment: 'Matching attachment',
  semantic_similarity: 'Semantic similarity',
  sent_to_recipient: 'Sent to the person it was promised to',
}

function signalValue(k: string, v: unknown): ReactNode {
  if (k === 'semantic_similarity' && typeof v === 'number') return pct(v)
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (Array.isArray(v)) return v.join(', ')
  if (typeof v === 'string' && (k === 'completion_statement' || k === 'cancellation')) return `“${v}”`
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

const OUTCOME: Record<string, { label: string; tone: 'success' | 'neutral' | 'uncertain' | 'warning' }> = {
  candidate: { label: 'Needs your review', tone: 'uncertain' },
  fulfilled: { label: 'Accepted as fulfilment', tone: 'success' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  cancelled: { label: 'Cancellation', tone: 'warning' },
}

function CandidateRow({ cid, f }: { cid: string; f: FulfillmentCandidate }) {
  const m = useWorkMutation(
    (accept: boolean) => post<Commitment>(`/api/commitments/${cid}/candidates/${f.id}`, { accept }),
    (_r, accept) => (accept ? 'Marked fulfilled by this item' : 'Match rejected'),
  )
  const o = OUTCOME[f.outcome] ?? { label: f.outcome, tone: 'neutral' as const }
  return (
    <li className="rounded-md border border-line p-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <EvidenceChip type={f.source_type} id={f.source_id} span={typeof f.signals.completion_statement === 'string' ? f.signals.completion_statement : typeof f.signals.cancellation === 'string' ? f.signals.cancellation : undefined} label={sourceLabel(f.source_type)} />
          <span className="text-xs tabular-nums text-ink-2">{pct(f.score)} match</span>
          <Badge tone={o.tone}>{o.label}</Badge>
        </div>
        {f.outcome === 'candidate' && (
          <div className="flex gap-1">
            <Button size="sm" variant="secondary" loading={m.isPending && m.variables === true} disabled={m.isPending} onClick={() => m.mutate(true)}>
              <Check className="h-3 w-3" /> Accept
            </Button>
            <Button size="sm" variant="ghost" loading={m.isPending && m.variables === false} disabled={m.isPending} onClick={() => m.mutate(false)}>
              <X className="h-3 w-3" /> Reject
            </Button>
          </div>
        )}
      </div>
      <dl className="mt-2 space-y-0.5 text-xs">
        {Object.entries(f.signals).map(([k, v]) => (
          <div key={k} className="flex gap-2">
            <dt className="w-36 shrink-0 text-ink-3">{SIGNAL_LABEL[k] ?? k.replace(/_/g, ' ')}</dt>
            <dd className="min-w-0 text-ink-2">{signalValue(k, v)}</dd>
          </div>
        ))}
      </dl>
      {f.outcome === 'candidate' && <p className="mt-2 text-[11px] text-ink-3">Below the 70% needed to mark it fulfilled automatically. Accepting marks the commitment fulfilled.</p>}
    </li>
  )
}

function Corrections({ c }: { c: CommitmentDetail }) {
  const people = usePeople()
  const id = useId()
  const [due, setDue] = useState(toDateInput(c.due_at))
  const [actor, setActor] = useState(c.actor?.id ?? '')
  useEffect(() => {
    setDue(toDateInput(c.due_at))
    setActor(c.actor?.id ?? '')
  }, [c.id, c.due_at, c.actor?.id])
  const m = useWorkMutation(
    (body: Partial<{ status: CommitmentStatus; due_at: string; actor_person_id: string }>) => patch<Commitment>(`/api/commitments/${c.id}`, body),
    (_r, v) =>
      v.status === 'REJECTED'
        ? 'Marked as not a commitment. It won’t be re-extracted.'
        : v.status
          ? `Marked ${v.status.toLowerCase()}`
          : v.due_at
            ? `Due date changed to ${fmtDate(v.due_at)}`
            : 'Owner changed',
  )
  const statusBtn = (status: CommitmentStatus, label: string, icon: ReactNode, variant: 'secondary' | 'ghost' | 'danger' = 'secondary') =>
    c.status !== status && (
      <Button size="sm" variant={variant} disabled={m.isPending} loading={m.isPending && m.variables?.status === status} onClick={() => m.mutate({ status })}>
        {icon}
        {label}
      </Button>
    )
  return (
    <section className="rounded-md border border-line bg-surface-2 p-3">
      <SectionLabel>Correct this</SectionLabel>
      <div className="flex flex-wrap gap-1.5">
        {statusBtn('FULFILLED', 'Mark fulfilled', <Check className="h-3 w-3" />)}
        {statusBtn('CANCELLED', 'Cancelled', <Ban className="h-3 w-3" />)}
        {statusBtn('REJECTED', 'Not a commitment', <CircleSlash className="h-3 w-3" />, 'ghost')}
        {statusBtn('OPEN', 'Reopen', <RotateCcw className="h-3 w-3" />, 'ghost')}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (due) m.mutate({ due_at: fromDateInput(due) })
          }}
        >
          <label htmlFor={`${id}-due`} className="mb-1 block text-xs font-medium text-ink-2">
            Due date
          </label>
          <div className="flex gap-1.5">
            <input id={`${id}-due`} type="date" value={due} onChange={(e) => setDue(e.target.value)} className="h-7 min-w-0 flex-1 rounded-md border border-line bg-surface px-1.5 text-xs text-ink focus:border-accent focus:outline-none" />
            <Button size="sm" type="submit" disabled={!due || due === toDateInput(c.due_at) || m.isPending}>
              Save
            </Button>
          </div>
        </form>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (actor) m.mutate({ actor_person_id: actor })
          }}
        >
          <label htmlFor={`${id}-actor`} className="mb-1 block text-xs font-medium text-ink-2">
            Who owes it
          </label>
          <div className="flex gap-1.5">
            <Select id={`${id}-actor`} value={actor} onChange={(e) => setActor(e.target.value)} className="h-7 min-w-0 flex-1 px-1.5 text-xs" disabled={people.isLoading}>
              <option value="">{people.isLoading ? 'Loading…' : 'Choose a person'}</option>
              {people.data?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.is_self ? `You (${p.name})` : p.name}
                  {p.organization ? ` · ${p.organization}` : ''}
                </option>
              ))}
            </Select>
            <Button size="sm" type="submit" disabled={!actor || actor === c.actor?.id || m.isPending}>
              Save
            </Button>
          </div>
        </form>
      </div>
      <p className="mt-2 text-[11px] text-ink-3">Corrections are recorded and outrank the model on later passes.</p>
    </section>
  )
}

/** Right-hand drawer variant, for pages where the commitment list isn't the main content. */
export function CommitmentDrawer({ id, now, onClose, onOpen }: { id: string; now: string | undefined; onClose: () => void; onOpen: (id: string) => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  if (typeof document === 'undefined') return null
  // portal: page wrappers animate (and so create stacking contexts) which would trap the overlay under the top bar
  return createPortal(
    <div className="fixed inset-0 z-[35] bg-black/20" onMouseDown={onClose}>
      <aside role="dialog" aria-label="Commitment details" className="animate-fade-in scrollbar-thin absolute inset-y-0 right-0 w-full max-w-lg overflow-y-auto border-l border-line bg-surface p-5 shadow-pop" onMouseDown={(e) => e.stopPropagation()}>
        <CommitmentDetailView id={id} now={now} onOpen={onOpen} onClose={onClose} />
      </aside>
    </div>,
    document.body,
  )
}
