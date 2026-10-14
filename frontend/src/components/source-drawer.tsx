'use client'

import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText, X } from 'lucide-react'
import Link from 'next/link'
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { ErrorState, LoadingRows } from '@/components/ui/primitives'
import { get } from '@/lib/api'
import type { CalendarEvent, DocumentItem, Email, Note } from '@/lib/types'
import { SOURCE_LABEL, findSpan, fmtDateTime } from '@/lib/utils'

type SourceRef = { type: string; id: string; span?: string }
const Ctx = createContext<{ open: (r: SourceRef) => void; close: () => void }>({ open: () => {}, close: () => {} })

export function useSource() {
  return useContext(Ctx)
}

export function SourceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<SourceRef | null>(null)
  const open = useCallback((r: SourceRef) => setRef(r), [])
  const close = useCallback(() => setRef(null), [])
  const value = useMemo(() => ({ open, close }), [open, close])
  return (
    <Ctx.Provider value={value}>
      {children}
      {ref && <SourceDrawer source={ref} onClose={close} />}
    </Ctx.Provider>
  )
}

const ENDPOINT: Record<string, (id: string) => string> = {
  email: (id) => `/api/emails/${id}`,
  event: (id) => `/api/events/${id}`,
  document: (id) => `/api/documents/${id}`,
  note: (id) => `/api/notes/${id}`,
}

const PAGE: Record<string, (d: { id: string; thread_id?: string | null }) => string> = {
  email: (d) => (d.thread_id ? `/inbox/${d.thread_id}` : '/inbox'),
  event: (d) => `/calendar?event=${d.id}`,
  document: (d) => `/documents/${d.id}`,
  note: (d) => `/notes?id=${d.id}`,
}

/** Renders text with the evidence span highlighted (and scrolled into view). */
export function Highlighted({ text, span }: { text: string; span?: string }) {
  const range = findSpan(text, span)
  useEffect(() => {
    document.getElementById('evidence-mark')?.scrollIntoView?.({ block: 'center' })
  }, [text, span])
  if (!range) return <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{text}</p>
  const [s, e] = range
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">
      {text.slice(0, s)}
      <mark id="evidence-mark" className="evidence">
        {text.slice(s, e)}
      </mark>
      {text.slice(e)}
    </p>
  )
}

function SourceDrawer({ source, onClose }: { source: SourceRef; onClose: () => void }) {
  const ep = ENDPOINT[source.type]
  const q = useQuery({ queryKey: ['source', source.type, source.id], queryFn: () => get<Record<string, unknown>>(ep(source.id)), enabled: !!ep })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const d = q.data
  return (
    <div className="fixed inset-0 z-40" onMouseDown={onClose}>
      <aside
        role="dialog"
        aria-label="Source"
        className="animate-fade-in absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l border-line bg-surface shadow-pop"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-ink-3">
            <FileText className="h-3.5 w-3.5" />
            {SOURCE_LABEL[source.type] ?? source.type} · source
          </div>
          <div className="flex items-center gap-1">
            {d && PAGE[source.type] && (
              <Link href={PAGE[source.type](d as { id: string; thread_id?: string })} onClick={onClose} className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs text-ink-2 hover:bg-sunken">
                Open <ExternalLink className="h-3 w-3" />
              </Link>
            )}
            <button onClick={onClose} aria-label="Close source" className="rounded p-1 text-ink-3 hover:bg-sunken hover:text-ink">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="scrollbar-thin flex-1 overflow-y-auto p-5">
          {!ep && <p className="text-sm text-ink-3">This source type can’t be previewed.</p>}
          {q.isLoading && <LoadingRows rows={6} />}
          {q.error && <ErrorState error={q.error} retry={() => q.refetch()} />}
          {d && source.type === 'email' && <EmailView e={d as unknown as Email} span={source.span} />}
          {d && source.type === 'event' && <EventView e={d as unknown as CalendarEvent} span={source.span} />}
          {d && source.type === 'document' && <DocView d={d as unknown as DocumentItem & { chunks: { page: number | null; section: string | null; text: string }[] }} span={source.span} />}
          {d && source.type === 'note' && <NoteView n={d as unknown as Note} span={source.span} />}
          {source.span && (
            <p className="mt-6 border-t border-line pt-3 text-[11px] text-ink-3">
              Highlighted text is the exact passage the AI used. Source content is treated as data, never as instructions.
            </p>
          )}
        </div>
      </aside>
    </div>
  )
}

function Meta({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="mb-4 grid grid-cols-[80px_1fr] gap-x-3 gap-y-1 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="text-ink-2">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function EmailView({ e, span }: { e: Email; span?: string }) {
  return (
    <div>
      <h2 className="mb-3 font-serif text-lg font-medium">{e.subject}</h2>
      <Meta
        rows={[
          ['From', `${e.from_name ?? ''} <${e.from_addr}>`],
          ['To', e.to.map((t) => t.name || t.email).join(', ')],
          ['Sent', fmtDateTime(e.sent_at)],
          ...(e.attachments.length ? ([['Attached', e.attachments.map((a) => a.filename).join(', ')]] as [string, ReactNode][]) : []),
        ]}
      />
      <Highlighted text={e.body ?? ''} span={span} />
    </div>
  )
}

function EventView({ e, span }: { e: CalendarEvent; span?: string }) {
  return (
    <div>
      <h2 className="mb-3 font-serif text-lg font-medium">{e.title}</h2>
      <Meta rows={[['When', fmtDateTime(e.start_at)], ['Attendees', e.attendees.map((a) => a.name || a.email).join(', ')]]} />
      {e.description && <Highlighted text={e.description} span={span} />}
      {e.notes && (
        <div className="mt-4">
          <div className="mb-1 text-xs font-medium text-ink-3">Meeting notes</div>
          <Highlighted text={e.notes} span={span} />
        </div>
      )}
    </div>
  )
}

function DocView({ d, span }: { d: DocumentItem & { chunks: { page: number | null; section: string | null; text: string }[] }; span?: string }) {
  const hit = d.chunks.find((c) => findSpan(c.text, span))
  return (
    <div>
      <h2 className="mb-3 font-serif text-lg font-medium">{d.title}</h2>
      <Meta rows={[['File', d.filename], ['Author', d.author?.name ?? '—'], ...(hit ? ([['Location', `${hit.page ? `page ${hit.page}` : ''}${hit.section ? ` · ${hit.section}` : ''}`]] as [string, ReactNode][]) : [])]} />
      <Highlighted text={d.text ?? ''} span={span} />
    </div>
  )
}

function NoteView({ n, span }: { n: Note; span?: string }) {
  return (
    <div>
      <h2 className="mb-3 font-serif text-lg font-medium">{n.title}</h2>
      <Highlighted text={n.body} span={span} />
    </div>
  )
}
