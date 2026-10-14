'use client'

import { useQuery } from '@tanstack/react-query'
import { Handshake, Inbox, Paperclip, Search } from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import { Avatar } from '@/components/ui/ai'
import { Card, EmptyState, ErrorState, Input, LoadingRows, PageHeader, Select } from '@/components/ui/primitives'
import { AwaitingBadge, ProjectTag, Segmented, useNow, useProjects } from '@/components/work/shared'
import { get } from '@/lib/api'
import type { ThreadSummary } from '@/lib/types-work'
import { cn, relDays } from '@/lib/utils'

export default function InboxPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <InboxView />
    </Suspense>
  )
}

const AWAITING = [
  { value: '', label: 'All threads' },
  { value: 'me', label: 'Awaiting me' },
  { value: 'them', label: 'Awaiting them' },
]

function InboxView() {
  const sp = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const project = sp.get('project') ?? ''
  const awaiting = sp.get('awaiting') ?? ''
  const qParam = sp.get('q') ?? ''
  const [q, setQ] = useState(qParam)
  const now = useNow()
  const projects = useProjects()

  const setParam = (k: string, v: string) => {
    const next = new URLSearchParams(sp.toString())
    if (v) next.set(k, v)
    else next.delete(k)
    router.replace(`${pathname}${next.toString() ? `?${next}` : ''}`, { scroll: false })
  }

  // debounce the search box into the URL
  useEffect(() => {
    if (q === qParam) return
    const t = setTimeout(() => setParam('q', q.trim()), 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q])

  const params = new URLSearchParams()
  if (project) params.set('project_id', project)
  if (awaiting) params.set('awaiting', awaiting)
  if (qParam) params.set('q', qParam)
  const threads = useQuery({ queryKey: ['threads', params.toString()], queryFn: () => get<{ items: ThreadSummary[] }>(`/api/threads?${params}`) })

  return (
    <div>
      <PageHeader title="Inbox" description="Email threads with what Threadline extracted from them: commitments, decisions and who is waiting on whom." />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
          <label htmlFor="inbox-q" className="sr-only">
            Search subjects
          </label>
          <Input id="inbox-q" className="pl-8" placeholder="Search subjects" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <label htmlFor="inbox-project" className="sr-only">
          Project
        </label>
        <Select id="inbox-project" value={project} onChange={(e) => setParam('project', e.target.value)}>
          <option value="">All projects</option>
          {projects.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
        <Segmented label="Waiting on" value={awaiting} onChange={(v) => setParam('awaiting', v)} options={AWAITING} />
      </div>

      <Card>
        {threads.isLoading ? (
          <LoadingRows rows={8} />
        ) : threads.error ? (
          <ErrorState error={threads.error} retry={() => threads.refetch()} />
        ) : !threads.data?.items.length ? (
          <EmptyState
            icon={<Inbox className="h-4 w-4" />}
            title={project || awaiting || qParam ? 'No threads match these filters' : 'No email yet'}
            description={project || awaiting || qParam ? 'Try clearing a filter.' : 'Connect an email account in Integrations to see threads here.'}
          />
        ) : (
          <ul className="divide-y divide-line">
            {threads.data.items.map((t) => (
              <ThreadRow key={t.id} t={t} now={now} />
            ))}
          </ul>
        )}
      </Card>
      {threads.data && threads.data.items.length > 0 && <p className="mt-2 text-xs text-ink-3">{threads.data.items.length} threads</p>}
    </div>
  )
}

function ThreadRow({ t, now }: { t: ThreadSummary; now: string | undefined }) {
  const last = t.last
  const sender = last?.direction === 'outbound' ? 'You' : (last?.from_name ?? last?.from_addr ?? 'Unknown')
  const attachments = last?.attachments.length ?? 0
  return (
    <li>
      <Link href={`/inbox/${t.id}`} className="flex gap-3 px-4 py-3 hover:bg-surface-2 focus-visible:bg-surface-2">
        <Avatar name={sender} className="mt-0.5 h-7 w-7" />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-3">
            <span className={cn('truncate text-sm', t.awaiting === 'me' ? 'font-semibold text-ink' : 'font-medium text-ink')}>
              {sender}
              {t.message_count > 1 && <span className="ml-1.5 text-xs font-normal text-ink-3">{t.message_count}</span>}
            </span>
            <span className="shrink-0 text-xs tabular-nums text-ink-3" title={t.last_at ?? ''}>
              {relDays(t.last_at, now)}
            </span>
          </div>
          <div className="truncate text-sm text-ink">{t.subject}</div>
          {last?.snippet && <div className="truncate text-xs text-ink-3">{last.snippet.replace(/\s+/g, ' ')}</div>}
          {(t.project || t.awaiting || t.commitments > 0 || attachments > 0) && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <AwaitingBadge awaiting={t.awaiting} />
              <ProjectTag project={t.project} />
              {t.commitments > 0 && (
                <span className="inline-flex items-center gap-1 text-[11px] text-ink-3">
                  <Handshake className="h-3 w-3" aria-hidden />
                  {t.commitments} commitment{t.commitments === 1 ? '' : 's'}
                </span>
              )}
              {attachments > 0 && (
                <span className="inline-flex items-center gap-1 text-[11px] text-ink-3">
                  <Paperclip className="h-3 w-3" aria-hidden />
                  {attachments}
                </span>
              )}
            </div>
          )}
        </div>
      </Link>
    </li>
  )
}
