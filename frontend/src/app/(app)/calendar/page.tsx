'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, CalendarDays, ClipboardList, MapPin, Users } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useMemo } from 'react'

import { Confidence, EvidenceChip, ProjectChip, StatusBadge } from '@/components/ui/ai'
import { Badge, Button, Card, EmptyState, ErrorState, LoadingRows, PageHeader } from '@/components/ui/primitives'
import { CommitmentSummary } from '@/components/work/commitments'
import { MeetingBriefView, NoBrief } from '@/components/work/meeting-brief'
import { ProjectTag, SectionLabel, relShort } from '@/components/work/shared'
import { get } from '@/lib/api'
import type { CalendarEvent } from '@/lib/types'
import type { EventDetail } from '@/lib/types-work'
import { cn, fmtDate, fmtTime } from '@/lib/utils'

export default function CalendarPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <CalendarView />
    </Suspense>
  )
}

function dayKey(iso: string) {
  return iso.slice(0, 10)
}

function CalendarView() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const q = useQuery({ queryKey: ['events'], queryFn: () => get<{ now: string; items: CalendarEvent[] }>('/api/events') })
  const now = q.data?.now
  const items = useMemo(() => q.data?.items ?? [], [q.data])
  const nowMs = now ? new Date(now).getTime() : Date.now()
  const upcoming = useMemo(() => items.filter((e) => new Date(e.end_at).getTime() >= nowMs).sort((a, b) => a.start_at.localeCompare(b.start_at)), [items, nowMs])
  const past = useMemo(() => items.filter((e) => new Date(e.end_at).getTime() < nowMs), [items, nowMs])

  const explicit = sp.get('event')
  const selected = explicit ?? upcoming[0]?.id ?? null
  const brief = sp.get('brief') === '1'

  const go = (event: string | null, withBrief: boolean) => {
    const next = new URLSearchParams()
    if (event) next.set('event', event)
    if (withBrief) next.set('brief', '1')
    router.push(`${pathname}${next.toString() ? `?${next}` : ''}`, { scroll: false })
  }

  return (
    <div>
      <PageHeader title="Calendar" description="Meetings with what was agreed in them. Prepare a brief before any meeting to see open items, decisions and recent context." />
      {q.isLoading ? (
        <Card>
          <LoadingRows rows={8} />
        </Card>
      ) : q.error ? (
        <Card>
          <ErrorState error={q.error} retry={() => q.refetch()} />
        </Card>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState icon={<CalendarDays className="h-4 w-4" />} title="No meetings yet" description="Connect a calendar in Integrations to see meetings here." />
        </Card>
      ) : (
        <div className={cn('grid gap-5', !brief && 'lg:grid-cols-[320px_minmax(0,1fr)]')}>
          <nav aria-label="Meetings" className={cn('min-w-0 space-y-5', brief ? 'hidden' : explicit && 'hidden lg:block')}>
            <EventGroup title="Upcoming" events={upcoming} selected={selected} now={now} onPick={(id) => go(id, false)} />
            <EventGroup title="Past" events={past} selected={selected} now={now} onPick={(id) => go(id, false)} />
          </nav>
          <div className={cn('min-w-0', brief && 'mx-auto w-full max-w-4xl', !explicit && 'hidden lg:block')}>
            {explicit && !brief && (
              <button onClick={() => go(null, false)} className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink lg:hidden">
                <ArrowLeft className="h-3 w-3" /> All meetings
              </button>
            )}
            {!selected ? (
              <Card>
                <NoBrief />
              </Card>
            ) : brief ? (
              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <Button size="sm" variant="ghost" onClick={() => go(selected, false)}>
                    <ArrowLeft className="h-3 w-3" /> Back to calendar
                  </Button>
                </div>
                <MeetingBriefView eventId={selected} now={now} />
              </div>
            ) : (
              <EventPanel id={selected} now={now} onBrief={() => go(selected, true)} />
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function EventGroup({ title, events, selected, now, onPick }: { title: string; events: CalendarEvent[]; selected: string | null; now: string | undefined; onPick: (id: string) => void }) {
  const days: [string, CalendarEvent[]][] = []
  for (const e of events) {
    const k = dayKey(e.start_at)
    const last = days[days.length - 1]
    if (last && last[0] === k) last[1].push(e)
    else days.push([k, [e]])
  }
  return (
    <section>
      <SectionLabel count={events.length}>{title}</SectionLabel>
      {events.length === 0 ? (
        <p className="text-xs text-ink-3">Nothing {title.toLowerCase()}.</p>
      ) : (
        <Card>
          <ul className="divide-y divide-line">
            {days.map(([k, evs]) => (
              <li key={k}>
                <div className="flex items-baseline justify-between bg-surface-2 px-3 py-1.5 text-[11px] font-medium text-ink-3">
                  <span>{fmtDate(evs[0].start_at, { weekday: 'short', month: 'short', day: 'numeric' })}</span>
                  <span>{relShort(evs[0].start_at, now)}</span>
                </div>
                <ul>
                  {evs.map((e) => (
                    <li key={e.id}>
                      <button
                        onClick={() => onPick(e.id)}
                        aria-current={selected === e.id ? 'true' : undefined}
                        className={cn('flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-surface-2', selected === e.id && 'bg-accent-wash hover:bg-accent-wash')}
                      >
                        <span className="w-16 shrink-0 pt-px text-xs tabular-nums text-ink-3">{fmtTime(e.start_at)}</span>
                        <span className="min-w-0 flex-1">
                          <span className={cn('block truncate text-sm', selected === e.id ? 'font-medium text-ink' : 'text-ink')}>{e.title}</span>
                          <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                            <ProjectTag project={e.project} />
                            <span className="text-[11px] text-ink-3">
                              {e.attendees.length} attendee{e.attendees.length === 1 ? '' : 's'}
                            </span>
                            {e.notes && <span className="text-[11px] text-ink-3">· notes</span>}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  )
}

const RESPONSE_TONE: Record<string, 'success' | 'danger' | 'neutral' | 'warning'> = { accepted: 'success', declined: 'danger', tentative: 'warning' }

function EventPanel({ id, now, onBrief }: { id: string; now: string | undefined; onBrief: () => void }) {
  const q = useQuery({ queryKey: ['event', id], queryFn: () => get<EventDetail>(`/api/events/${id}`) })
  if (q.isLoading)
    return (
      <Card>
        <LoadingRows rows={6} />
      </Card>
    )
  if (q.error || !q.data)
    return (
      <Card>
        <ErrorState error={q.error} retry={() => q.refetch()} />
      </Card>
    )
  const e = q.data
  const isPast = now ? new Date(e.end_at).getTime() < new Date(now).getTime() : false
  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink">{e.title}</h2>
          <p className="mt-0.5 text-sm text-ink-2">
            {fmtDate(e.start_at, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })} · {fmtTime(e.start_at)}–{fmtTime(e.end_at)}
            {relShort(e.start_at, now) && <span className="text-ink-3"> · {relShort(e.start_at, now)}</span>}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
            {e.project && <ProjectChip project={e.project} />}
            {e.location && (
              <span className="inline-flex items-center gap-1">
                <MapPin className="h-3 w-3" aria-hidden /> {e.location}
              </span>
            )}
            {e.status !== 'confirmed' && <Badge tone="warning">{e.status}</Badge>}
          </div>
        </div>
        <Button variant={isPast ? 'secondary' : 'primary'} onClick={onBrief}>
          <ClipboardList className="h-3.5 w-3.5" /> {isPast ? 'View brief' : 'Prepare brief'}
        </Button>
      </div>
      <div className="grid gap-6 px-5 py-4 md:grid-cols-[minmax(0,1fr)_220px]">
        <div className="min-w-0 space-y-5">
          {e.description && (
            <section>
              <SectionLabel>Agenda</SectionLabel>
              <p className="whitespace-pre-wrap text-sm text-ink-2">{e.description}</p>
            </section>
          )}
          <section>
            <SectionLabel>Meeting notes</SectionLabel>
            {e.notes ? (
              <div className="rounded-md border border-line bg-surface-2 p-3">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{e.notes}</p>
                <div className="mt-2">
                  <EvidenceChip type="event" id={e.id} label="Open as source" />
                </div>
              </div>
            ) : (
              <p className="text-xs text-ink-3">{isPast ? 'No notes were recorded for this meeting.' : 'Notes appear here after the meeting.'}</p>
            )}
          </section>
          <section>
            <SectionLabel count={e.commitments.length}>Commitments made here</SectionLabel>
            {e.commitments.length === 0 ? (
              <p className="text-xs text-ink-3">None extracted.</p>
            ) : (
              <ul className="space-y-3">
                {e.commitments.map((c) => (
                  <li key={c.id}>
                    <Link href={`/commitments?id=${c.id}`} className="block rounded-md hover:bg-surface-2">
                      <CommitmentSummary c={c} now={now} showProject={false} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <SectionLabel count={e.decisions.length}>Decisions made here</SectionLabel>
            {e.decisions.length === 0 ? (
              <p className="text-xs text-ink-3">None extracted.</p>
            ) : (
              <ul className="space-y-2">
                {e.decisions.map((d) => (
                  <li key={d.id} className="text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={d.status} />
                      <span className="font-medium text-ink">{d.chosen}</span>
                      <span className="text-xs text-ink-3">({d.topic})</span>
                      <Confidence value={d.confidence} />
                      <EvidenceChip type={d.source.type} id={d.source.id} span={d.source.span} label="Source" />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
        <aside>
          <SectionLabel count={e.attendees.length}>
            <span className="inline-flex items-center gap-1">
              <Users className="h-3 w-3" aria-hidden /> Attendees
            </span>
          </SectionLabel>
          <ul className="space-y-1.5">
            {e.attendees.map((a) => (
              <li key={a.email} className="flex items-center justify-between gap-2 text-xs">
                <span className="min-w-0 truncate text-ink-2" title={a.email}>
                  {a.name || a.email}
                  {e.organizer === a.email && <span className="text-ink-3"> · organizer</span>}
                </span>
                {a.response && <Badge tone={RESPONSE_TONE[a.response] ?? 'neutral'}>{a.response}</Badge>}
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </Card>
  )
}

