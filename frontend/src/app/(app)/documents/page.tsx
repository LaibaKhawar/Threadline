'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Search, Upload } from 'lucide-react'
import Link from 'next/link'
import { useDeferredValue, useRef, useState } from 'react'

import { ACCEPTED_EXT, DocStatus, fileKind } from '@/components/memory/doc-status'
import { useToast } from '@/components/toast'
import { PersonChip, ProjectChip } from '@/components/ui/ai'
import { Button, Card, EmptyState, ErrorState, Input, LoadingRows, PageHeader, Select, Spinner } from '@/components/ui/primitives'
import { api, errorMessage, get } from '@/lib/api'
import type { DocumentItem, ProjectSummary } from '@/lib/types'
import type { UploadResponse } from '@/lib/types-memory'
import { bytes, cn, fmtDate } from '@/lib/utils'

export default function DocumentsPage() {
  const [q, setQ] = useState('')
  const [projectId, setProjectId] = useState('')
  const dq = useDeferredValue(q.trim())
  const qs = new URLSearchParams()
  if (dq) qs.set('q', dq)
  if (projectId) qs.set('project_id', projectId)
  const docs = useQuery({
    queryKey: ['documents', dq, projectId],
    queryFn: () => get<{ items: DocumentItem[] }>(`/api/documents${qs.size ? `?${qs}` : ''}`),
    placeholderData: (prev) => prev,
    refetchInterval: (query) => (query.state.data?.items.some((d) => d.status !== 'ready' && d.status !== 'error') ? 3000 : false),
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ items: ProjectSummary[] }>('/api/projects') })

  return (
    <div className="animate-fade-in">
      <PageHeader title="Documents" description="Files you’ve added to memory. Threadline keeps page and section structure, so every answer can point to the exact passage." />

      <UploadZone />

      <Card>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <h2 className="mr-auto text-sm font-semibold text-ink">Library</h2>
          <div className="relative w-56 max-w-full">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title or filename" aria-label="Search documents" className="h-8 pl-8 text-xs" />
          </div>
          <Select aria-label="Filter by project" className="h-8 text-xs" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.items.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </div>
        {docs.isLoading ? (
          <LoadingRows rows={6} />
        ) : docs.error ? (
          <ErrorState error={docs.error} retry={() => docs.refetch()} />
        ) : !docs.data || docs.data.items.length === 0 ? (
          <EmptyState icon={<FileText className="h-4 w-4" />} title={dq || projectId ? 'No documents match' : 'No documents yet'} description={dq || projectId ? 'Try another search or project.' : 'Drop a PDF, Word, Markdown, CSV or Excel file above to add it to memory.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] font-medium uppercase tracking-wide text-ink-3">
                  <th scope="col" className="px-4 py-2 font-medium">Document</th>
                  <th scope="col" className="px-4 py-2 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2 font-medium">Project</th>
                  <th scope="col" className="px-4 py-2 font-medium">Author</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Pages</th>
                  <th scope="col" className="px-4 py-2 text-right font-medium">Added</th>
                </tr>
              </thead>
              <tbody className={cn('divide-y divide-line', docs.isFetching && !docs.isLoading && 'opacity-80')}>
                {docs.data.items.map((d) => (
                  <tr key={d.id} className="hover:bg-surface-2">
                    <td className="px-4 py-2.5">
                      <Link href={`/documents/${d.id}`} className="flex items-center gap-2.5 hover:text-accent">
                        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-sunken text-ink-3">
                          <FileText className="h-3.5 w-3.5" aria-hidden />
                        </span>
                        <span className="min-w-0">
                          <span className="block truncate font-medium text-ink">{d.title}</span>
                          <span className="block truncate text-xs text-ink-3">
                            {d.filename} · {fileKind(d.mime_type, d.filename)} · {bytes(d.size_bytes)}
                          </span>
                        </span>
                      </Link>
                    </td>
                    <td className="px-4 py-2.5">
                      <DocStatus status={d.status} error={d.error} />
                    </td>
                    <td className="px-4 py-2.5">{d.project ? <ProjectChip project={d.project} /> : <span className="text-xs text-ink-3">—</span>}</td>
                    <td className="px-4 py-2.5 text-xs">{d.author ? <PersonChip person={d.author} /> : <span className="text-ink-3">{(d.metadata?.author as string | undefined) ?? '—'}</span>}</td>
                    <td className="px-4 py-2.5 text-right text-xs tabular-nums text-ink-2">{d.page_count ?? '—'}</td>
                    <td className="px-4 py-2.5 text-right text-xs tabular-nums text-ink-3">{fmtDate(d.created_at, { month: 'short', day: 'numeric' })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function UploadZone() {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [current, setCurrent] = useState<string | null>(null)
  const qc = useQueryClient()
  const toast = useToast()
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      const results: { name: string; ok: boolean; res?: UploadResponse; error?: string }[] = []
      for (const f of files) {
        setCurrent(f.name)
        const form = new FormData()
        form.append('file', f)
        try {
          const res = await api<UploadResponse>('/api/documents', { method: 'POST', form })
          results.push({ name: f.name, ok: true, res })
        } catch (e) {
          results.push({ name: f.name, ok: false, error: errorMessage(e) })
        }
      }
      setCurrent(null)
      return results
    },
    onSuccess: (results) => {
      for (const r of results) {
        if (!r.ok) toast(`${r.name}: ${r.error}`, 'error')
        else if (r.res?.duplicate)
          toast(
            <span>
              {r.name} is already in your library.{' '}
              {r.res.document && (
                <Link className="text-accent underline" href={`/documents/${r.res.document.id}`}>
                  Open it
                </Link>
              )}
            </span>,
            'info',
          )
        else
          toast(
            <span>
              Added {r.name}.{' '}
              {r.res?.document && (
                <Link className="text-accent underline" href={`/documents/${r.res.document.id}`}>
                  View
                </Link>
              )}
            </span>,
          )
      }
      qc.invalidateQueries({ queryKey: ['documents'] })
      qc.invalidateQueries({ queryKey: ['timeline'] })
      qc.invalidateQueries({ queryKey: ['graph'] })
    },
  })
  const send = (list: FileList | null) => {
    const files = list ? Array.from(list) : []
    if (files.length) upload.mutate(files)
  }
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault()
        setOver(false)
        send(e.dataTransfer.files)
      }}
      className={cn('mb-5 flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-7 text-center transition-colors', over ? 'border-accent bg-accent-wash' : 'border-line-strong bg-surface-2')}
    >
      {upload.isPending ? (
        <div className="flex items-center gap-2 text-sm text-ink-2" role="status">
          <Spinner /> Uploading {current ?? ''}…
        </div>
      ) : (
        <>
          <Upload className="h-5 w-5 text-ink-3" aria-hidden />
          <p className="text-sm text-ink">Drag files here to add them to memory</p>
          <p className="text-xs text-ink-3">PDF, Word, Excel, CSV, Markdown, text, .eml, .ics, .mbox · up to 25 MB each. Files are checked by content, not just extension.</p>
        </>
      )}
      <input
        ref={input}
        type="file"
        multiple
        className="sr-only"
        aria-label="Upload documents"
        accept={ACCEPTED_EXT.join(',')}
        onChange={(e) => {
          send(e.target.files)
          e.target.value = ''
        }}
      />
      {!upload.isPending && (
        <Button size="sm" variant="secondary" className="mt-1" onClick={() => input.current?.click()}>
          <Upload className="h-3.5 w-3.5" /> Choose files
        </Button>
      )}
    </div>
  )
}
