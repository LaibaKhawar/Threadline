'use client'

import { useQuery } from '@tanstack/react-query'
import { Search as SearchIcon } from 'lucide-react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { type FormEvent, Suspense, useEffect, useState } from 'react'

import { useSource } from '@/components/source-drawer'
import { ChannelBadges, SOURCE_ICON, StatusBadge } from '@/components/ui/ai'
import { Badge, Card, CardHeader, EmptyState, ErrorState, Input, LoadingRows, PageHeader, Tabs } from '@/components/ui/primitives'
import { get } from '@/lib/api'
import type { SearchHit } from '@/lib/types'
import { fmtDate } from '@/lib/utils'

type Mode = 'hybrid' | 'vector' | 'keyword' | 'graph'
type SearchResponse = {
  query: { keywords: string; people: string[]; projects: string[]; types: string[]; intents: string[]; time_text: string | null; time_start: string | null; time_end: string | null }
  mode: Mode
  timings_ms: Record<string, number>
  groups: Record<string, SearchHit[]>
  total: number
}

const GROUP_ORDER: [string, string][] = [
  ['person', 'People'],
  ['project', 'Projects'],
  ['commitment', 'Commitments'],
  ['decision', 'Decisions'],
  ['task', 'Tasks'],
  ['email', 'Emails'],
  ['event', 'Meetings'],
  ['document', 'Documents'],
  ['note', 'Notes'],
]

const EXAMPLES = ['Everything related to Project Atlas', 'Documents Sarah sent me last month', 'Decisions about database architecture', 'What am I waiting on Ahmed for?', 'What tasks are blocked?', 'Show discussions with Sarah regarding pricing', 'cutover plan']

function SearchInner() {
  const params = useSearchParams()
  const router = useRouter()
  const { open } = useSource()
  const q = params.get('q') ?? ''
  const mode = (params.get('mode') as Mode) ?? 'hybrid'
  const [text, setText] = useState(q)
  useEffect(() => setText(q), [q])
  useEffect(() => {
    const o = params.get('open')
    if (o) {
      const [type, id] = o.split(':')
      if (type && id) open({ type, id })
    }
  }, [params, open])

  const res = useQuery({
    queryKey: ['search', q, mode],
    queryFn: () => get<SearchResponse>(`/api/search?k=40&mode=${mode}&q=${encodeURIComponent(q)}`),
    enabled: q.length > 0,
  })
  const go = (nq: string, nm: Mode = mode) => router.push(`/search?q=${encodeURIComponent(nq)}&mode=${nm}`)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (text.trim()) go(text.trim())
  }
  const parsed = res.data?.query

  return (
    <div>
      <PageHeader title="Search" description="One search across emails, meetings, documents, notes, people, projects, commitments and decisions. Each result shows which retrieval channels found it." />
      <form onSubmit={submit} className="relative mb-3" role="search">
        <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-3" />
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search your memory…" aria-label="Search" className="h-11 pl-9 text-[15px]" autoFocus />
      </form>
      <Tabs<Mode>
        value={mode}
        onChange={(m) => q && go(q, m)}
        tabs={[
          { value: 'hybrid', label: 'Hybrid' },
          { value: 'vector', label: 'Semantic only' },
          { value: 'keyword', label: 'Keyword only' },
          { value: 'graph', label: 'Graph only' },
        ]}
        className="mb-4"
      />
      {!q && (
        <Card className="p-5">
          <p className="mb-3 text-sm text-ink-2">Examples</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((e) => (
              <button key={e} onClick={() => go(e)} className="rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-ink-2 hover:border-accent hover:text-accent">
                {e}
              </button>
            ))}
          </div>
        </Card>
      )}
      {res.isLoading && <LoadingRows rows={6} />}
      {res.error && <ErrorState error={res.error} retry={() => res.refetch()} />}
      {parsed && (
        <div className="mb-5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3" aria-label="How the query was understood">
          <span>Understood as:</span>
          {parsed.people.map((p, i) => (
            <Badge key={`${p}-${i}`} tone="info">person: {p}</Badge>
          ))}
          {parsed.projects.map((p) => (
            <Badge key={p} tone="accent">project: {p}</Badge>
          ))}
          {parsed.types.map((t) => (
            <Badge key={t}>type: {t}</Badge>
          ))}
          {parsed.time_text && (
            <Badge tone="warning">
              time: {parsed.time_text} ({fmtDate(parsed.time_start, { month: 'short', day: 'numeric' })} – {fmtDate(parsed.time_end)})
            </Badge>
          )}
          {parsed.intents.map((i) => (
            <Badge key={i} tone="uncertain">intent: {i.replace('_', ' ')}</Badge>
          ))}
          {parsed.keywords && <Badge>keywords: {parsed.keywords}</Badge>}
          <span className="ml-auto tabular-nums">
            {Object.entries(res.data?.timings_ms ?? {})
              .map(([k, v]) => `${k} ${Math.round(v)}ms`)
              .join(' · ')}
          </span>
        </div>
      )}
      {res.data && res.data.total === 0 && Object.keys(res.data.groups).length === 0 && (
        <EmptyState title="No results" description="Try fewer words, or switch to semantic search for paraphrases." />
      )}
      {res.data && (
        <div className="grid gap-4 lg:grid-cols-2">
          {GROUP_ORDER.filter(([k]) => res.data!.groups[k]?.length).map(([k, label]) => (
            <Card key={k} className={k === 'email' || k === 'document' ? 'lg:col-span-1' : ''}>
              <CardHeader title={`${label}`} description={`${res.data!.groups[k].length} result(s)`} />
              <ul className="divide-y divide-line">
                {res.data!.groups[k].slice(0, 10).map((h) => (
                  <li key={h.id}>
                    <HitRow hit={h} onOpen={() => open({ type: h.source_type ?? h.type, id: h.source_id ?? h.id, span: h.type === 'commitment' || h.type === 'decision' ? h.snippet : undefined })} />
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

function HitRow({ hit, onOpen }: { hit: SearchHit; onOpen: () => void }) {
  const loc = hit.location as { page?: number | null; section?: string | null } | undefined
  const content = ['email', 'event', 'document', 'note', 'commitment', 'decision'].includes(hit.type)
  const inner = (
    <>
      <div className="flex items-center gap-2">
        <span className="text-ink-3">{SOURCE_ICON[hit.type]}</span>
        <span className="truncate text-sm font-medium text-ink">{hit.title}</span>
        {hit.status && <StatusBadge status={hit.status} />}
        {hit.occurred_at && <span className="ml-auto shrink-0 text-[11px] text-ink-3">{fmtDate(hit.occurred_at)}</span>}
      </div>
      <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{hit.snippet}</p>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <ChannelBadges channels={hit.channels} />
        {loc?.page && <span className="text-[10px] text-ink-3">page {loc.page}</span>}
        {loc?.section && <span className="truncate text-[10px] text-ink-3">§ {loc.section}</span>}
      </div>
    </>
  )
  if (hit.type === 'person') return <Link href={`/people/${hit.id}`} className="block px-4 py-2.5 hover:bg-sunken">{inner}</Link>
  if (hit.type === 'project') return <Link href={`/projects/${hit.id}`} className="block px-4 py-2.5 hover:bg-sunken">{inner}</Link>
  if (hit.type === 'task') return <Link href="/tasks" className="block px-4 py-2.5 hover:bg-sunken">{inner}</Link>
  return (
    <button onClick={onOpen} className="block w-full px-4 py-2.5 text-left hover:bg-sunken" disabled={!content}>
      {inner}
    </button>
  )
}

export default function SearchPage() {
  return (
    <Suspense fallback={<LoadingRows />}>
      <SearchInner />
    </Suspense>
  )
}
