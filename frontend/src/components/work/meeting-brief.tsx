'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowRight, FileText, Lock, Search } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'

import { Avatar, Confidence, EvidenceChip, Quote, StatusBadge } from '@/components/ui/ai'
import { Card, EmptyState, ErrorState, LoadingRows } from '@/components/ui/primitives'
import { get } from '@/lib/api'
import type { MeetingBrief } from '@/lib/types-work'
import { cn, fmtDate, fmtDateTime, fmtTime } from '@/lib/utils'

import { DueText, HEALTH_EXPLAINER, HealthSignals, relShort } from './shared'

function Section({ title, count, children, className, hint }: { title: string; count?: number; children: ReactNode; className?: string; hint?: ReactNode }) {
  return (
    <section className={cn('min-w-0', className)}>
      <div className="mb-2 flex items-baseline justify-between gap-2 border-b border-line pb-1.5">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-2">
          {title}
          {count !== undefined && <span className="ml-1.5 font-normal tabular-nums text-ink-3">{count}</span>}
        </h3>
        {hint && <span className="text-[11px] text-ink-3">{hint}</span>}
      </div>
      {children}
    </section>
  )
}

function Nothing({ children }: { children: ReactNode }) {
  return <p className="text-xs text-ink-3">{children}</p>
}

/** One-page, read-only prep sheet for a meeting (GET /api/events/{id}/brief). */
export function MeetingBriefView({ eventId, now }: { eventId: string; now: string | undefined }) {
  const q = useQuery({ queryKey: ['brief', eventId], queryFn: () => get<MeetingBrief>(`/api/events/${eventId}/brief`) })
  if (q.isLoading)
    return (
      <Card>
        <LoadingRows rows={10} />
      </Card>
    )
  if (q.error || !q.data)
    return (
      <Card>
        <ErrorState error={q.error} retry={() => q.refetch()} />
      </Card>
    )
  const b = q.data
  const ev = b.event
  const overdue = b.open_commitments.filter((c) => c.status === 'OVERDUE').length
  return (
    <Card className="overflow-hidden">
      <header className="border-b border-line px-5 py-4 sm:px-6">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-3">Meeting brief</p>
        <h2 className="mt-1 font-serif text-[22px] font-medium leading-tight tracking-tight text-ink">{ev.title}</h2>
        <p className="mt-1 text-sm text-ink-2">
          {fmtDate(ev.start_at, { weekday: 'long', month: 'long', day: 'numeric' })} · {fmtTime(ev.start_at)}–{fmtTime(ev.end_at)}
          {relShort(ev.start_at, now) && <span className="text-ink-3"> · {relShort(ev.start_at, now)}</span>}
          {ev.location && <span className="text-ink-3"> · {ev.location}</span>}
        </p>
        {ev.description && <p className="mt-2 max-w-2xl text-sm text-ink-2">{ev.description}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
          <span>
            <strong className="font-semibold tabular-nums text-ink">{b.participants.length}</strong> other participant{b.participants.length === 1 ? '' : 's'}
          </span>
          <span>
            <strong className="font-semibold tabular-nums text-ink">{b.open_commitments.length}</strong> open item{b.open_commitments.length === 1 ? '' : 's'}
            {overdue > 0 && <span className="text-danger"> ({overdue} overdue)</span>}
          </span>
          <span>
            <strong className="font-semibold tabular-nums text-ink">{b.decisions.length}</strong> recent decision{b.decisions.length === 1 ? '' : 's'}
          </span>
        </div>
        <p className="mt-3 inline-flex items-center gap-1.5 rounded border border-line bg-surface-2 px-2 py-1 text-[11px] text-ink-2">
          <Lock className="h-3 w-3 text-ink-3" aria-hidden />
          Read-only brief. Nothing is sent or changed automatically.
        </p>
      </header>

      <div className="grid gap-x-8 gap-y-6 px-5 py-5 sm:px-6 lg:grid-cols-2">
        <Section title="Who’s attending" count={b.participants.length}>
          {b.participants.length === 0 ? (
            <Nothing>Only you.</Nothing>
          ) : (
            <ul className="space-y-2">
              {b.participants.map((p) => (
                <li key={p.ref.id} className="flex items-start gap-2.5">
                  <Avatar name={p.name} className="mt-0.5" />
                  <div className="min-w-0 text-xs">
                    <Link href={`/people/${p.ref.id}`} className="text-sm font-medium text-ink hover:text-accent">
                      {p.name}
                    </Link>
                    <div className="text-ink-3">{[p.title, p.organization].filter(Boolean).join(' · ') || 'No title on record'}</div>
                    <div className="text-ink-3">Last interaction: {p.last_interaction_at ? `${fmtDate(p.last_interaction_at, { month: 'short', day: 'numeric' })}${relShort(p.last_interaction_at, now) ? ` (${relShort(p.last_interaction_at, now)})` : ''}` : 'none recorded'}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Project health" hint={b.project ? undefined : 'No project linked'}>
          {b.project ? (
            <div>
              <div className="mb-2 flex flex-wrap items-center gap-2">
                <Link href={`/projects/${b.project.ref.id}`} className="text-sm font-medium text-ink hover:text-accent">
                  {b.project.project}
                </Link>
                <StatusBadge status={b.project.status} />
              </div>
              <HealthSignals signals={b.project.signals} />
              <p className="mt-2 text-[11px] text-ink-3">{HEALTH_EXPLAINER}</p>
            </div>
          ) : (
            <Nothing>This meeting isn’t linked to a project, so there is no health signal.</Nothing>
          )}
        </Section>

        <Section title="Open commitments" count={b.open_commitments.length} className="lg:col-span-2" hint="Involving attendees or this project">
          {b.open_commitments.length === 0 ? (
            <Nothing>Nothing open between you and these people.</Nothing>
          ) : (
            <ul className="divide-y divide-line">
              {b.open_commitments.map((c) => (
                <li key={c.ref.id} className="py-2.5 first:pt-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={c.status} />
                    <Link href={`/commitments?id=${c.ref.id}`} className="text-sm text-ink hover:text-accent">
                      {c.title}
                    </Link>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                    {c.actor && (
                      <span className="inline-flex items-center gap-1 text-ink-2">
                        {c.actor}
                        {c.recipient && (
                          <>
                            <ArrowRight className="h-3 w-3 text-ink-3" aria-label="to" /> {c.recipient}
                          </>
                        )}
                      </span>
                    )}
                    <DueText due={c.due_at} now={now} />
                    <Confidence value={c.confidence} label="extraction confidence" />
                    {c.evidence.map((e) => (
                      <EvidenceChip key={e.source_id} type={e.source_type} id={e.source_id} span={e.span} label={e.label} />
                    ))}
                  </div>
                  {c.reason && c.status === 'OVERDUE' && <p className="mt-1 text-xs text-ink-3">{c.reason}</p>}
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Decisions" count={b.decisions.length}>
          {b.decisions.length === 0 ? (
            <Nothing>No recorded decisions for this project.</Nothing>
          ) : (
            <ul className="space-y-2.5">
              {b.decisions.map((d) => (
                <li key={d.ref.id}>
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <StatusBadge status={d.status} />
                    <span className={cn('font-medium', d.status === 'superseded' ? 'text-ink-3 line-through' : 'text-ink')}>{d.chosen}</span>
                    {d.rejected.length > 0 && <span className="text-xs text-ink-3">over {d.rejected.join(', ')}</span>}
                  </div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">
                    <span>
                      {d.topic} · {fmtDate(d.decided_at)}
                    </span>
                    {d.evidence.map((e) => (
                      <EvidenceChip key={e.source_id} type={e.source_type} id={e.source_id} span={e.span} label="Source" />
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Previous meeting">
          {b.previous_meeting ? (
            <div>
              <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-3">
                <span>{fmtDateTime(b.previous_meeting.start_at)}</span>
                <EvidenceChip type="event" id={b.previous_meeting.ref.id} label="Open notes" />
              </div>
              {b.previous_meeting.notes ? <Quote className="not-italic whitespace-pre-wrap text-sm">{b.previous_meeting.notes}</Quote> : <Nothing>No notes were taken.</Nothing>}
            </div>
          ) : (
            <Nothing>No earlier meeting with this title has notes.</Nothing>
          )}
        </Section>

        <Section title="Related documents" count={b.related_documents.length}>
          {b.related_documents.length === 0 ? (
            <Nothing>None found.</Nothing>
          ) : (
            <ul className="space-y-1.5">
              {b.related_documents.map((d) => (
                <li key={d.ref.id} className="flex items-center justify-between gap-2 text-sm">
                  <Link href={`/documents/${d.ref.id}`} className="inline-flex min-w-0 items-center gap-1.5 text-ink hover:text-accent">
                    <FileText className="h-3.5 w-3.5 shrink-0 text-ink-3" aria-hidden />
                    <span className="truncate">{d.title}</span>
                  </Link>
                  <span className="flex shrink-0 items-center gap-1.5 text-[11px] text-ink-3">
                    {d.retrieved && (
                      <span className="inline-flex items-center gap-0.5" title="Not linked to the project; found by searching for the meeting title">
                        <Search className="h-3 w-3" aria-hidden /> search match
                      </span>
                    )}
                    {d.authored_at && fmtDate(d.authored_at, { month: 'short', day: 'numeric' })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Section>

        <Section title="Recent emails" count={b.recent_emails.length} hint="Last 30 days">
          {b.recent_emails.length === 0 ? (
            <Nothing>No recent email with these people.</Nothing>
          ) : (
            <ul className="space-y-2">
              {b.recent_emails.map((e) => (
                <li key={e.ref.id} className="text-xs">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm text-ink">{e.subject}</span>
                    <span className="shrink-0 tabular-nums text-ink-3">{fmtDate(e.sent_at, { month: 'short', day: 'numeric' })}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-ink-3">
                    <span className="truncate">{e.from}</span>
                    <EvidenceChip type="email" id={e.ref.id} label="Read" />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </div>
      <footer className="border-t border-line px-5 py-2.5 text-[11px] text-ink-3 sm:px-6">Assembled {fmtDateTime(b.generated_at)} from your memory. Every item links to its source.</footer>
    </Card>
  )
}

export function NoBrief() {
  return <EmptyState title="Select a meeting" description="Pick a meeting to see its details or prepare a brief." />
}
