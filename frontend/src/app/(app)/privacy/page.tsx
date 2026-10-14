'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Cpu, Download, Eye, HardDrive, ShieldCheck, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'

import { connectorIcon } from '@/components/system/connectors'
import { ConfirmDialog, MiniSwitch, ModeOptions, OPERATION_LABEL, SwitchRow, Table, fmtNum, fmtStamp, humanize, td, th } from '@/components/system/shared'
import { useToast } from '@/components/toast'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingRows, PageHeader } from '@/components/ui/primitives'
import { errorMessage, get, patch, post, put } from '@/lib/api'
import type { AiMode, Integration, Inventory, Privacy } from '@/lib/types-system'
import { cn } from '@/lib/utils'

type Flags = Partial<Pick<Integration, 'store_locally' | 'local_ai_allowed' | 'cloud_ai_allowed'>>
type ClearScope = 'ai_memories' | 'conversations' | 'everything'

const CLEAR: Record<ClearScope, { label: string; title: string; body: string[] }> = {
  ai_memories: {
    label: 'Clear AI memories',
    title: 'Clear AI memories?',
    body: [
      'Deletes everything Threadline inferred: memories, insights, notifications, evidence links, timeline entries, merge suggestions, AI-inferred relationships, and commitments, decisions and suggested tasks you have not edited or confirmed.',
      'Your source data (emails, meetings, documents, notes) is kept, so memory can be rebuilt from Settings → Rebuild memory.',
    ],
  },
  conversations: {
    label: 'Clear conversations',
    title: 'Clear assistant conversations?',
    body: ['Deletes every assistant conversation and run, including their answers and citations.'],
  },
  everything: {
    label: 'Delete everything',
    title: 'Delete all your data?',
    body: [
      'Deletes all imported content (emails, meetings, documents and their files, notes, chunks), all AI memories, tasks, commitments, decisions and conversations, and resets every sync cursor.',
      'Your account and source connections remain; syncing again would re-import data.',
    ],
  },
}

export default function PrivacyPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['privacy'], queryFn: () => get<Privacy>('/api/privacy') })

  const save = useMutation({
    mutationFn: (body: { ai_mode?: AiMode; cloud_allowed_operations?: string[]; telemetry_opt_in?: boolean }) => put<Privacy>('/api/privacy', body),
    onMutate: (body) => {
      // Optimistic: reflect the choice immediately, roll back on error.
      const prev = qc.getQueryData<Privacy>(['privacy'])
      if (prev) qc.setQueryData<Privacy>(['privacy'], { ...prev, ...body })
      return { prev }
    },
    onSuccess: (d, body) => {
      qc.setQueryData(['privacy'], d)
      qc.invalidateQueries({ queryKey: ['me'] })
      if (body.ai_mode) toast(`AI mode set to ${body.ai_mode === 'LOCAL' ? 'Local only' : humanize(body.ai_mode.toLowerCase())}.`)
      else toast('Privacy settings saved.')
    },
    onError: (e, _b, c) => {
      if (c?.prev) qc.setQueryData(['privacy'], c.prev)
      toast(errorMessage(e), 'error')
    },
  })

  if (q.isLoading) return <LoadingRows rows={10} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const p = q.data
  const allowed = new Set(p.cloud_allowed_operations)
  const localCalls = p.llm_calls_by_locality.local ?? 0
  const cloudCalls = p.llm_calls_by_locality.cloud ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title="Privacy center"
        description={`What Threadline stores, where AI runs, and which sources may be sent to which model. Data is stored on ${p.stored_at}.`}
      />

      <Card>
        <CardHeader
          title="AI mode"
          description="Decides where language-model calls may run. Enforced by a single policy gate before every call."
          action={
            p.cloud_configured ? (
              <Badge tone="info" title="Cloud provider configured on the server">
                Cloud model: {p.cloud_model}
              </Badge>
            ) : (
              <Badge tone="neutral">No cloud provider configured</Badge>
            )
          }
        />
        <div className="space-y-4 p-4">
          <ModeOptions name="ai-mode" value={p.ai_mode} disabled={save.isPending} onChange={(m) => m !== p.ai_mode && save.mutate({ ai_mode: m })} />
          {!p.cloud_configured && p.ai_mode !== 'LOCAL' && (
            <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-ink-2">
              No cloud provider is configured on this server, so every call still runs locally whatever mode you pick. A provider is configured by the operator via environment variables; nothing is sent until then.
            </p>
          )}
          {p.ai_mode === 'HYBRID' && (
            <fieldset className="rounded-md border border-line p-3">
              <legend className="px-1 text-xs font-medium text-ink-2">Operations allowed to use the cloud model</legend>
              <p className="mb-2 text-xs text-ink-3">An allowed operation still stays local unless every source whose content is in that prompt has Cloud AI on (below).</p>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {p.cloud_eligible_operations.map((op) => (
                  <label key={op} className="flex items-center gap-2 text-sm text-ink">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-[var(--accent)]"
                      checked={allowed.has(op)}
                      disabled={save.isPending}
                      onChange={(e) => {
                        const next = new Set(allowed)
                        if (e.target.checked) next.add(op)
                        else next.delete(op)
                        save.mutate({ cloud_allowed_operations: [...next] })
                      }}
                    />
                    {OPERATION_LABEL[op] ?? humanize(op)}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </div>
      </Card>

      <SourcesCard sources={p.sources} />

      <div className="grid gap-5 lg:grid-cols-3">
        <Card>
          <CardHeader title="Embeddings" />
          <div className="flex items-start gap-3 p-4">
            <Cpu className="mt-0.5 h-4 w-4 shrink-0 text-success" />
            <p className="text-sm text-ink-2">
              <span className="font-medium text-ink">Always computed locally.</span> Semantic search vectors are created on this machine in every AI mode.
            </p>
          </div>
        </Card>
        <Card>
          <CardHeader title="LLM calls by locality" description="All recorded calls for this account." action={<Link href="/activity?tab=llm" className="text-xs text-accent hover:underline">Details</Link>} />
          <div className="grid grid-cols-2 gap-3 p-4">
            <div>
              <div className="text-xs text-ink-3">Local</div>
              <div className="text-2xl font-semibold tabular-nums">{fmtNum(localCalls)}</div>
            </div>
            <div>
              <div className="text-xs text-ink-3">Cloud</div>
              <div className={cn('text-2xl font-semibold tabular-nums', cloudCalls > 0 && 'text-info')}>{fmtNum(cloudCalls)}</div>
            </div>
          </div>
        </Card>
        <Card>
          <CardHeader title="Telemetry" />
          <div className="space-y-2 p-4">
            <SwitchRow
              label="Share anonymous usage telemetry"
              description="Opt-in. Currently transmits nothing: no telemetry endpoint exists."
              checked={p.telemetry_opt_in}
              disabled={save.isPending}
              onChange={(v) => save.mutate({ telemetry_opt_in: v })}
            />
            <p className="text-[11px] text-ink-3">Transmits data: {p.telemetry_transmits ? 'yes' : 'no'}.</p>
          </div>
        </Card>
      </div>

      <DataControls />

      <p className="flex items-start gap-2 text-xs text-ink-3">
        <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        These controls are good data-control practice, not a claim of legal compliance with any regulation.
      </p>
    </div>
  )
}

function SourcesCard({ sources }: { sources: Integration[] }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const update = useMutation({
    mutationFn: ({ id, flags }: { id: string; flags: Flags }) => patch<Integration>(`/api/integrations/${id}`, flags),
    onMutate: ({ id, flags }) => {
      setPendingKey(`${id}:${Object.keys(flags)[0]}`)
      const prev = qc.getQueryData<Privacy>(['privacy'])
      if (prev) {
        qc.setQueryData<Privacy>(['privacy'], {
          ...prev,
          sources: prev.sources.map((src) => {
            if (src.id !== id) return src
            const next = { ...src, ...flags }
            if (!next.local_ai_allowed) next.cloud_ai_allowed = false // cloud implies local (mirrors the backend)
            return next
          }),
        })
      }
      return { prev }
    },
    onSettled: () => setPendingKey(null),
    onSuccess: (i) => {
      qc.invalidateQueries({ queryKey: ['privacy'] })
      qc.invalidateQueries({ queryKey: ['integrations'] })
      toast(`Updated AI permissions for ${i.name}.`)
    },
    onError: (e, _v, c) => {
      if (c?.prev) qc.setQueryData(['privacy'], c.prev)
      toast(errorMessage(e), 'error')
    },
  })
  const set = (i: Integration, flags: Flags) => update.mutate({ id: i.id, flags })
  return (
    <Card>
      <CardHeader
        title="Per-source permissions"
        description="Local AI off: the source is never placed in any prompt. Cloud AI requires Local AI. Store locally off: future syncs of that source are stopped."
      />
      {sources.length === 0 ? (
        <EmptyState title="No sources connected" description="Connect a source from Integrations to control it here." />
      ) : (
        <Table label="Per-source privacy permissions">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>Source</th>
              <th className={cn(th, 'text-right')}>Items</th>
              <th className={th}>Last synced</th>
              <th className={th}>
                <span className="inline-flex items-center gap-1">
                  <HardDrive className="h-3 w-3" /> Stored locally
                </span>
              </th>
              <th className={th}>Local AI</th>
              <th className={th}>Cloud AI</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {sources.map((i) => {
              const busy = (k: string) => pendingKey === `${i.id}:${k}`
              return (
                <tr key={i.id}>
                  <td className={td}>
                    <div className="flex items-center gap-2">
                      <span className="text-ink-3">{connectorIcon(i.kind)}</span>
                      <span className="font-medium text-ink">{i.name}</span>
                      {i.status === 'revoked' && <Badge tone="neutral">Disconnected</Badge>}
                    </div>
                  </td>
                  <td className={cn(td, 'text-right tabular-nums')}>{fmtNum(i.items ?? i.item_count ?? 0)}</td>
                  <td className={cn(td, 'whitespace-nowrap text-xs')}>{i.kind === 'notes' || i.kind === 'uploads' ? 'Live (in-app)' : i.last_sync_at ? fmtStamp(i.last_sync_at) : 'Never'}</td>
                  <td className={td}>
                    <MiniSwitch label={`Store ${i.name} locally`} checked={i.store_locally} disabled={busy('store_locally')} onChange={(v) => set(i, { store_locally: v })} />
                  </td>
                  <td className={td}>
                    <MiniSwitch label={`Allow local AI on ${i.name}`} checked={i.local_ai_allowed} disabled={busy('local_ai_allowed')} onChange={(v) => set(i, { local_ai_allowed: v })} />
                  </td>
                  <td className={td}>
                    <MiniSwitch
                      label={`Allow cloud AI on ${i.name}`}
                      title={i.local_ai_allowed ? `Allow cloud AI on ${i.name}` : 'Cloud AI requires Local AI to be on'}
                      checked={i.cloud_ai_allowed}
                      disabled={!i.local_ai_allowed || busy('cloud_ai_allowed')}
                      onChange={(v) => set(i, { cloud_ai_allowed: v })}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function DataControls() {
  const qc = useQueryClient()
  const toast = useToast()
  const inv = useQuery({ queryKey: ['inventory'], queryFn: () => get<Inventory>('/api/privacy/inventory') })
  const [scope, setScope] = useState<ClearScope | null>(null)
  const clear = useMutation({
    mutationFn: (s: ClearScope) => post<{ deleted: Record<string, number>; note: string }>('/api/privacy/clear', { scope: s, confirm: 'DELETE' }),
    onSuccess: (r) => {
      const total = Object.values(r.deleted).reduce((a, b) => a + b, 0)
      toast(`Deleted ${fmtNum(total)} records. ${r.note}`)
      setScope(null)
      qc.invalidateQueries()
    },
  })
  return (
    <Card>
      <CardHeader title="Your data" description="Everything stored about you, by type. Export it or delete it at any time." />
      <div className="p-4">
        {inv.isLoading ? (
          <LoadingRows rows={2} />
        ) : inv.error || !inv.data ? (
          <ErrorState error={inv.error} retry={() => inv.refetch()} />
        ) : (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4 lg:grid-cols-6">
            {Object.entries(inv.data.counts).map(([k, v]) => (
              <div key={k} className="min-w-0">
                <dt className="truncate text-xs text-ink-3">{humanize(k)}</dt>
                <dd className="text-sm font-semibold tabular-nums text-ink">{fmtNum(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
          <a
            href="/api/privacy/export"
            download="threadline-export.zip"
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-sunken"
          >
            <Download className="h-4 w-4" /> Export all data (.zip)
          </a>
          <Link href="/activity" className="inline-flex h-9 items-center gap-1.5 rounded-md px-3.5 text-sm font-medium text-ink-2 hover:bg-sunken hover:text-ink">
            <Eye className="h-4 w-4" /> Audit log
          </Link>
          <span className="flex-1" />
          {(Object.keys(CLEAR) as ClearScope[]).map((s) => (
            <Button key={s} variant="danger" onClick={() => setScope(s)}>
              {s === 'everything' && <Trash2 className="h-4 w-4" />}
              {CLEAR[s].label}
            </Button>
          ))}
        </div>
        <p className="mt-2 text-xs text-ink-3">The export contains JSON files for every table (credentials excluded). Original uploaded files are downloadable from Documents.</p>
      </div>
      <ConfirmDialog
        open={scope !== null}
        onClose={() => {
          setScope(null)
          clear.reset()
        }}
        title={scope ? CLEAR[scope].title : ''}
        confirmLabel={scope ? CLEAR[scope].label : 'Delete'}
        requireText="DELETE"
        pending={clear.isPending}
        error={clear.error}
        onConfirm={() => scope && clear.mutate(scope)}
      >
        {scope && CLEAR[scope].body.map((b) => <p key={b}>{b}</p>)}
        <p className="font-medium text-danger">This cannot be undone. Consider exporting first.</p>
      </ConfirmDialog>
    </Card>
  )
}
