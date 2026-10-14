'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Paperclip, Quote as QuoteIcon } from 'lucide-react'
import Link from 'next/link'
import { use, useEffect, useState } from 'react'

import { Avatar, Confidence, ProjectChip, StatusBadge } from '@/components/ui/ai'
import { Button, Card, CardHeader, ErrorState, LoadingRows } from '@/components/ui/primitives'
import { CommitmentSummary } from '@/components/work/commitments'
import { ProjectInference } from '@/components/work/inference'
import { AwaitingBadge, MarkedText, relShort, useNow } from '@/components/work/shared'
import { TaskLine } from '@/components/work/tasks'
import { get } from '@/lib/api'
import type { ThreadDetail } from '@/lib/types-work'
import { fmtDate, fmtDateTime } from '@/lib/utils'

export default function ThreadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const now = useNow()
  const q = useQuery({ queryKey: ['thread', id], queryFn: () => get<ThreadDetail>(`/api/threads/${id}`) })
  const [focus, setFocus] = useState<string | null>(null)

  useEffect(() => {
    if (focus) document.getElementById(`mark-${focus}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focus])

  if (q.isLoading) return <LoadingRows rows={10} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const t = q.data

  const spansFor = (emailId: string) => [
    ...t.commitments.filter((c) => c.source.id === emailId).map((c) => ({ key: c.id, span: c.source.span, title: `Commitment: ${c.description}` })),
    ...t.decisions.filter((d) => d.source.id === emailId).map((d) => ({ key: d.id, span: d.source.span, title: `Decision: ${d.chosen}` })),
    ...t.tasks.filter((x) => x.source?.id === emailId).map((x) => ({ key: x.id, span: x.source?.span, title: `Task: ${x.title}` })),
  ]
  const emailLabel = (eid: string) => {
    const e = t.emails.find((x) => x.id === eid)
    return e ? `${e.direction === 'outbound' ? 'You' : (e.from_name ?? e.from_addr)}, ${fmtDate(e.sent_at, { month: 'short', day: 'numeric' })}` : 'message'
  }
  const showBtn = (key: string) => (
    <Button size="sm" variant="ghost" onClick={() => setFocus(key)} aria-label="Show the source sentence in the message">
      <QuoteIcon className="h-3 w-3" /> Show in message
    </Button>
  )
  const pending = t.inferences.filter((i) => i.status === 'pending')

  return (
    <div>
      <Link href="/inbox" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-ink">
        <ArrowLeft className="h-3 w-3" /> Inbox
      </Link>
      <header className="mb-5">
        <h1 className="font-serif text-[26px] font-medium leading-tight tracking-tight text-ink">{t.subject}</h1>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
          <span>
            {t.emails.length} message{t.emails.length === 1 ? '' : 's'}
          </span>
          {t.project ? <ProjectChip project={t.project} /> : <span>No project</span>}
          <AwaitingBadge awaiting={t.awaiting} />
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
        <ol className="space-y-3" aria-label="Messages">
          {t.emails.map((e) => (
            <li key={e.id}>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
                  <div className="flex min-w-0 items-start gap-2.5">
                    <Avatar name={e.from_name ?? e.from_addr} className="h-7 w-7" />
                    <div className="min-w-0 text-xs">
                      <div className="text-sm font-medium text-ink">
                        {e.direction === 'outbound' ? 'You' : (e.from_name ?? e.from_addr)}
                        <span className="ml-1.5 font-normal text-ink-3">&lt;{e.from_addr}&gt;</span>
                      </div>
                      <div className="text-ink-3">
                        To {e.to.map((x) => x.name || x.email).join(', ')}
                        {e.cc.length > 0 && <> · Cc {e.cc.map((x) => x.name || x.email).join(', ')}</>}
                      </div>
                    </div>
                  </div>
                  <time className="shrink-0 text-xs tabular-nums text-ink-3" dateTime={e.sent_at} title={fmtDateTime(e.sent_at)}>
                    {fmtDateTime(e.sent_at)}
                    {relShort(e.sent_at, now) && ` · ${relShort(e.sent_at, now)}`}
                  </time>
                </div>
                <div className="px-4 py-3">
                  <MarkedText text={e.body ?? e.snippet} spans={spansFor(e.id)} activeKey={focus} />
                  {e.attachments.length > 0 && (
                    <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Attachments">
                      {e.attachments.map((a) => (
                        <li key={a.filename} className="inline-flex items-center gap-1 rounded border border-line bg-surface-2 px-2 py-1 text-xs text-ink-2">
                          <Paperclip className="h-3 w-3 text-ink-3" aria-hidden />
                          {a.filename}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ol>
          <p className="mt-2 px-1 text-[11px] text-ink-3">Dotted underlines mark sentences Threadline extracted something from. Use “Show in message” to highlight one.</p>
        </div>

        <aside className="space-y-4" aria-label="What Threadline extracted">
          <Card>
            <CardHeader title="Project" description={pending.length ? 'AI-inferred association. Confirm, change or ignore it.' : undefined} />
            <div className="space-y-2 p-3">
              {t.inferences.length === 0 ? (
                <p className="px-1 text-xs text-ink-3">{t.project ? `Filed under ${t.project.name}.` : 'No project inferred for this thread.'}</p>
              ) : (
                t.inferences.map((i) => <ProjectInference key={i.id} inf={i} context={t.emails.length > 1 ? `Inferred from the message by ${emailLabel(i.subject_id)}` : undefined} />)
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="Commitments" description="Promises and requests found in these messages." action={<Link href="/commitments" className="text-xs text-accent hover:underline">All</Link>} />
            {t.commitments.length === 0 ? (
              <p className="px-4 py-3 text-xs text-ink-3">None found.</p>
            ) : (
              <ul className="divide-y divide-line">
                {t.commitments.map((c) => (
                  <li key={c.id} className="px-4 py-3">
                    <CommitmentSummary c={c} now={now} showProject={false} />
                    <div className="mt-2 flex flex-wrap items-center gap-1">
                      {showBtn(c.id)}
                      <Link href={`/commitments?id=${c.id}`} className="rounded px-2 py-1 text-xs text-accent hover:bg-sunken">
                        Details and corrections
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Decisions" action={<Link href="/decisions" className="text-xs text-accent hover:underline">History</Link>} />
            {t.decisions.length === 0 ? (
              <p className="px-4 py-3 text-xs text-ink-3">None found.</p>
            ) : (
              <ul className="divide-y divide-line">
                {t.decisions.map((d) => (
                  <li key={d.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge status={d.status} />
                      <span className="text-sm font-medium text-ink">{d.chosen}</span>
                      {d.rejected.length > 0 && <span className="text-xs text-ink-3">over {d.rejected.join(', ')}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-3">
                      <span>Topic: {d.topic}</span>
                      <Confidence value={d.confidence} />
                    </div>
                    <div className="mt-1.5">{showBtn(d.id)}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Tasks" description="AI suggestions need your confirmation before they become tasks." />
            {t.tasks.length === 0 ? (
              <p className="px-4 py-3 text-xs text-ink-3">None suggested.</p>
            ) : (
              <ul className="divide-y divide-line px-4">
                {t.tasks.map((x) => (
                  <li key={x.id}>
                    <TaskLine task={x} now={now} showProject={false} />
                    {x.source?.span && <div className="-mt-1 pb-2 pl-3.5">{showBtn(x.id)}</div>}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </aside>
      </div>
    </div>
  )
}
