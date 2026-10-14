'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { DocStatus, fileKind } from '@/components/memory/doc-status'
import { CommitmentRow, DecisionRow } from '@/components/memory/records'
import { useWorkspaceNow } from '@/components/memory/use-now'
import { useToast } from '@/components/toast'
import { PersonChip, ProjectChip } from '@/components/ui/ai'
import { Button, Card, CardHeader, Dialog, EmptyState, ErrorState, LoadingRows } from '@/components/ui/primitives'
import { del, errorMessage, get } from '@/lib/api'
import type { DocChunk, DocumentDetail } from '@/lib/types-memory'
import { bytes, fmtDate } from '@/lib/utils'

type PageGroup = { page: number | null; sections: { section: string | null; chunks: DocChunk[] }[] }

function structure(chunks: DocChunk[]): PageGroup[] {
  const out: PageGroup[] = []
  for (const c of [...chunks].sort((a, b) => a.ordinal - b.ordinal)) {
    let pg = out[out.length - 1]
    if (!pg || pg.page !== c.page) {
      pg = { page: c.page, sections: [] }
      out.push(pg)
    }
    let sec = pg.sections[pg.sections.length - 1]
    if (!sec || sec.section !== c.section) {
      sec = { section: c.section, chunks: [] }
      pg.sections.push(sec)
    }
    sec.chunks.push(c)
  }
  return out
}

/** Chunks repeat their section heading as the first line; the heading is already shown above them. */
function stripHeading(text: string, section: string | null) {
  if (!section) return text
  const t = text.trimStart()
  const first = t.split('\n', 1)[0].replace(/^#+\s*/, '').trim()
  return first.toLowerCase() === section.trim().toLowerCase() ? t.slice(t.indexOf('\n') >= 0 ? t.indexOf('\n') + 1 : t.length).trim() : text
}

export default function DocumentPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const qc = useQueryClient()
  const toast = useToast()
  const now = useWorkspaceNow()
  const [confirm, setConfirm] = useState(false)
  const q = useQuery({
    queryKey: ['document', id],
    queryFn: () => get<DocumentDetail>(`/api/documents/${id}`),
    refetchInterval: (query) => (query.state.data && query.state.data.status !== 'ready' && query.state.data.status !== 'error' ? 3000 : false),
  })
  const remove = useMutation({
    mutationFn: () => del(`/api/documents/${id}`),
    onSuccess: () => {
      toast('Document deleted, along with its passages, extracted items and graph links.')
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['timeline'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
      router.push('/documents')
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const pages = useMemo(() => structure(q.data?.chunks ?? []), [q.data])

  if (q.isLoading) return <LoadingRows rows={8} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const d = q.data
  const meta = d.metadata ?? {}
  const multiPage = pages.some((p) => p.page !== null)

  return (
    <div className="animate-fade-in">
      <Link href="/documents" className="mb-3 inline-flex items-center gap-1 text-xs text-ink-3 hover:text-accent">
        <ArrowLeft className="h-3 w-3" /> Documents
      </Link>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-serif text-[26px] font-medium leading-tight tracking-tight text-ink">{d.title}</h1>
          <p className="mt-1 text-sm text-ink-2">
            {d.filename} · {fileKind(d.mime_type, d.filename)} · {bytes(d.size_bytes)}
            {d.page_count ? ` · ${d.page_count} page${d.page_count === 1 ? '' : 's'}` : ''}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-3">
            <DocStatus status={d.status} error={d.error} />
            <ProjectChip project={d.project} />
            {d.author ? (
              <span className="inline-flex items-center gap-1">
                by <PersonChip person={d.author} />
              </span>
            ) : typeof meta.author === 'string' ? (
              <span>by {meta.author}</span>
            ) : null}
            {d.authored_at && <span>· written {fmtDate(d.authored_at)}</span>}
            <span>· added {fmtDate(d.created_at)}</span>
          </div>
          {d.error && <p className="mt-2 text-xs text-danger">{d.error}</p>}
        </div>
        <div className="flex gap-2">
          <a href={`/api/documents/${d.id}/download`} download={d.filename} className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken">
            <Download className="h-3.5 w-3.5" /> Download
          </a>
          <Button variant="danger" onClick={() => setConfirm(true)}>
            <Trash2 className="h-3.5 w-3.5" /> Delete
          </Button>
        </div>
      </header>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="min-w-0 lg:col-span-2">
          <CardHeader title="Content" description={`${d.chunks.length} passage${d.chunks.length === 1 ? '' : 's'}, grouped by ${multiPage ? 'page and section' : 'section'} as extracted.`} />
          {d.chunks.length === 0 ? (
            d.text ? (
              <p className="whitespace-pre-wrap px-5 py-4 text-sm leading-relaxed text-ink">{d.text}</p>
            ) : (
              <EmptyState title={d.status === 'ready' ? 'No text could be extracted' : 'Still processing'} description={d.status === 'ready' ? 'The file may be scanned images only.' : 'Passages will appear here when processing finishes.'} />
            )
          ) : (
            <div className="divide-y divide-line">
              {pages.map((pg, i) => (
                <section key={`${pg.page}-${i}`} className="px-5 py-4" aria-label={pg.page !== null ? `Page ${pg.page}` : undefined}>
                  {pg.page !== null && <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">Page {pg.page}</div>}
                  <div className="space-y-4">
                    {pg.sections.map((sec, j) => (
                      <div key={`${sec.section}-${j}`}>
                        {sec.section && <h3 className="mb-1.5 text-sm font-semibold text-ink">{sec.section}</h3>}
                        <div className="space-y-2">
                          {sec.chunks.map((c) => {
                            const text = stripHeading(c.text, sec.section)
                            return text ? (
                              <p key={c.id} className="whitespace-pre-wrap text-sm leading-relaxed text-ink-2">
                                {text}
                              </p>
                            ) : null
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </Card>

        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader title="Decisions found" description="Extracted from this document; each links to its passage." />
            {d.decisions.length === 0 ? (
              <p className="px-4 py-4 text-xs text-ink-3">No decisions detected.</p>
            ) : (
              <ul className="divide-y divide-line">
                {d.decisions.map((x) => (
                  <DecisionRow key={x.id} d={x} />
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Commitments found" description="Promises and requests in this document." />
            {d.commitments.length === 0 ? (
              <p className="px-4 py-4 text-xs text-ink-3">No commitments detected.</p>
            ) : (
              <ul className="divide-y divide-line">
                {d.commitments.map((c) => (
                  <CommitmentRow key={c.id} c={c} now={now} />
                ))}
              </ul>
            )}
          </Card>
          {(Array.isArray(meta.columns) || typeof meta.row_count === 'number' || Array.isArray(meta.sheets)) && (
            <Card>
              <CardHeader title="Structure" />
              <dl className="grid grid-cols-[80px_1fr] gap-x-3 gap-y-1.5 px-4 py-3 text-xs">
                {Array.isArray(meta.sheets) && (
                  <>
                    <dt className="text-ink-3">Sheets</dt>
                    <dd className="text-ink-2">{(meta.sheets as unknown[]).map(String).join(', ')}</dd>
                  </>
                )}
                {typeof meta.row_count === 'number' && (
                  <>
                    <dt className="text-ink-3">Rows</dt>
                    <dd className="tabular-nums text-ink-2">{meta.row_count}</dd>
                  </>
                )}
                {Array.isArray(meta.columns) && (
                  <>
                    <dt className="text-ink-3">Columns</dt>
                    <dd className="text-ink-2">{(meta.columns as unknown[]).map(String).join(', ')}</dd>
                  </>
                )}
              </dl>
            </Card>
          )}
        </div>
      </div>

      <Dialog
        open={confirm}
        onClose={() => setConfirm(false)}
        title="Delete this document?"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
              <Trash2 className="h-3.5 w-3.5" /> Delete permanently
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">
          “{d.title}” will be removed from disk and from memory: its passages, search index entries, extracted decisions and commitments (except ones you edited), and graph relationships. This can’t be undone.
        </p>
      </Dialog>
    </div>
  )
}
