'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Cloud, HardDrive, Pencil, X } from 'lucide-react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { Table, fmtMs, fmtNum, fmtStamp, fmtUsd, humanize, td, th } from '@/components/system/shared'
import { useToast } from '@/components/toast'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Input, Label, LoadingRows, PageHeader, Tabs, Textarea } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'
import type { AuditItem, CostBucket, Costs, LlmItem, Proposal, RunItem, ToolItem, ToolManifest } from '@/lib/types-system'
import { cn } from '@/lib/utils'

type Tab = 'audit' | 'runs' | 'tools' | 'llm' | 'manifest'
const TABS: { value: Tab; label: string }[] = [
  { value: 'audit', label: 'Audit log' },
  { value: 'runs', label: 'Assistant runs' },
  { value: 'tools', label: 'Tool executions' },
  { value: 'llm', label: 'LLM calls' },
  { value: 'manifest', label: 'Tool permissions' },
]

function ActivityInner() {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const raw = params.get('tab') as Tab | null
  const tab: Tab = raw && TABS.some((t) => t.value === raw) ? raw : 'audit'
  const setTab = (t: Tab) => router.replace(`${pathname}?tab=${t}`, { scroll: false })
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title="AI activity"
        description="Every AI run, tool call and model call, plus the actions waiting for your approval. Nothing external happens without you."
      />
      <Proposals />
      <CostsCard />
      <Card>
        <Tabs className="px-2" value={tab} onChange={setTab} tabs={TABS} />
        {tab === 'audit' && <AuditTab />}
        {tab === 'runs' && <RunsTab />}
        {tab === 'tools' && <ToolsTab />}
        {tab === 'llm' && <LlmTab />}
        {tab === 'manifest' && <ManifestTab />}
      </Card>
    </div>
  )
}

export default function ActivityPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <ActivityInner />
    </Suspense>
  )
}

// ------------------------------------------------------------------------------------------ proposals

const EDITABLE: { key: string; label: string; multiline?: boolean }[] = [
  { key: 'to', label: 'To' },
  { key: 'to_name', label: 'Recipient name' },
  { key: 'subject', label: 'Subject' },
  { key: 'body', label: 'Body', multiline: true },
  { key: 'title', label: 'Title' },
  { key: 'due_at', label: 'Due (ISO date)' },
]

function Proposals() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['proposals', 'pending'], queryFn: () => get<{ items: Proposal[] }>('/api/proposals?status=pending') })
  const [editing, setEditing] = useState<Proposal | null>(null)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const decide = useMutation({
    mutationFn: ({ id, decision, payload }: { id: string; decision: 'approve' | 'reject'; payload?: Record<string, string> }) => post<Proposal>(`/api/proposals/${id}`, { decision, payload }),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: ['proposals'] })
      qc.invalidateQueries({ queryKey: ['activity'] })
      setEditing(null)
      const msg = typeof p.result?.message === 'string' ? p.result.message : null
      toast(p.status === 'rejected' ? 'Proposal rejected.' : p.status === 'executed' ? `Approved and executed${p.tool === 'create_task' ? ': task created.' : '.'}` : msg ?? 'Approved.')
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })
  const openEdit = (p: Proposal) => {
    const d: Record<string, string> = {}
    for (const f of EDITABLE) if (f.key in p.payload) d[f.key] = String(p.payload[f.key] ?? '')
    setDraft(d)
    setEditing(p)
  }
  const items = q.data?.items ?? []
  return (
    <Card>
      <CardHeader title="Pending approvals" description="Write actions the assistant proposed. Approve, edit, or reject; external sends are never automatic." action={items.length > 0 ? <Badge tone="warning">{items.length} pending</Badge> : undefined} />
      {q.isLoading ? (
        <LoadingRows rows={2} />
      ) : q.error ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title="Nothing awaiting approval" description="When the assistant proposes an email draft or a task, it waits here for your decision." />
      ) : (
        <ul className="divide-y divide-line">
          {items.map((p) => {
            const pl = p.payload as Record<string, unknown>
            const busy = decide.isPending && decide.variables?.id === p.id
            return (
              <li key={p.id} className="px-4 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-ink-2">{p.tool}</span>
                      {p.permission && <AccessBadge access={p.permission.access} />}
                      {p.permission?.requires_approval && <Badge tone="warning">Requires approval</Badge>}
                      <span className="text-xs text-ink-3">{fmtStamp(p.created_at)}</span>
                    </div>
                    {(pl.to || pl.to_name) ? (
                      <p className="mt-1.5 text-sm text-ink">
                        <span className="text-ink-3">To </span>
                        {String(pl.to_name ?? '')} {pl.to ? <span className="text-ink-2">&lt;{String(pl.to)}&gt;</span> : null}
                      </p>
                    ) : null}
                    {pl.subject ? (
                      <p className="text-sm font-medium text-ink">
                        <span className="font-normal text-ink-3">Subject </span>
                        {String(pl.subject)}
                      </p>
                    ) : null}
                    {pl.title ? <p className="mt-1 text-sm font-medium text-ink">{String(pl.title)}</p> : null}
                    {pl.body ? <pre className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-md bg-surface-2 p-2.5 font-sans text-xs text-ink-2">{String(pl.body)}</pre> : null}
                    {p.reason && <p className="mt-1.5 text-xs text-ink-2"><span className="text-ink-3">Why: </span>{p.reason}</p>}
                    {p.permission && (
                      <p className="mt-1 text-[11px] text-ink-3">
                        Permission: {p.permission.access} · scope {p.permission.scope} · sensitivity {p.permission.sensitivity} · {p.permission.description}
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 gap-1.5">
                    <Button size="sm" variant="primary" loading={busy && decide.variables?.decision === 'approve' && !editing} onClick={() => decide.mutate({ id: p.id, decision: 'approve' })}>
                      <Check className="h-3.5 w-3.5" /> Approve
                    </Button>
                    <Button size="sm" onClick={() => openEdit(p)} disabled={busy}>
                      <Pencil className="h-3.5 w-3.5" /> Edit
                    </Button>
                    <Button size="sm" variant="ghost" loading={busy && decide.variables?.decision === 'reject'} onClick={() => decide.mutate({ id: p.id, decision: 'reject' })}>
                      <X className="h-3.5 w-3.5" /> Reject
                    </Button>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
      <Dialog
        open={!!editing}
        onClose={() => setEditing(null)}
        title="Edit before approving"
        wide
        footer={
          <>
            <Button variant="ghost" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={decide.isPending} onClick={() => editing && decide.mutate({ id: editing.id, decision: 'approve', payload: draft })}>
              Approve edited version
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {EDITABLE.filter((f) => f.key in draft).map((f) => (
            <div key={f.key}>
              <Label htmlFor={`edit-${f.key}`}>{f.label}</Label>
              {f.multiline ? (
                <Textarea id={`edit-${f.key}`} rows={9} value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
              ) : (
                <Input id={`edit-${f.key}`} value={draft[f.key]} onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
              )}
            </div>
          ))}
          {Object.keys(draft).length === 0 && <p className="text-sm text-ink-3">This proposal has no editable fields.</p>}
          {editing?.tool === 'draft_email' || editing?.tool === 'send_email' ? (
            <p className="text-xs text-ink-3">Threadline has read-only mail access: approving records the final draft for you to copy into your mail client. Nothing is sent.</p>
          ) : null}
        </div>
      </Dialog>
    </Card>
  )
}

function AccessBadge({ access }: { access: string }) {
  return <Badge tone={access === 'WRITE' ? 'warning' : 'neutral'}>{access}</Badge>
}

// ------------------------------------------------------------------------------------------ costs

function CostsCard() {
  const q = useQuery({ queryKey: ['activity', 'costs'], queryFn: () => get<Costs>('/api/costs') })
  return (
    <Card>
      <CardHeader title="Cost & compute" description={q.data?.note ?? 'Model usage by locality.'} />
      {q.isLoading ? (
        <LoadingRows rows={2} />
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : (
        <div className="space-y-4 p-4">
          <div className="grid gap-3 sm:grid-cols-3">
            {(['today', 'week', 'month'] as const).map((k) => (
              <Period key={k} label={k === 'today' ? 'Last 24 hours' : k === 'week' ? 'Last 7 days' : 'Last 30 days'} data={q.data.periods[k] ?? {}} />
            ))}
          </div>
          {q.data.per_run.length > 0 && (
            <Table label="Cost per assistant run" className="rounded-md border border-line">
              <thead className="border-b border-line bg-surface-2">
                <tr>
                  <th className={th}>Run</th>
                  <th className={cn(th, 'text-right')}>Tokens</th>
                  <th className={cn(th, 'text-right')}>Latency</th>
                  <th className={cn(th, 'text-right')}>Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {q.data.per_run.map((r) => (
                  <tr key={r.run_id}>
                    <td className={cn(td, 'max-w-[420px] truncate')}>{r.question}</td>
                    <td className={cn(td, 'text-right tabular-nums')}>{fmtNum(r.tokens)}</td>
                    <td className={cn(td, 'text-right tabular-nums')}>{fmtMs(r.latency_ms)}</td>
                    <td className={cn(td, 'text-right tabular-nums')}>{fmtUsd(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </div>
      )}
    </Card>
  )
}

function Period({ label, data }: { label: string; data: Record<string, CostBucket> }) {
  const locs: ('local' | 'cloud')[] = ['local', 'cloud']
  return (
    <div className="rounded-md border border-line p-3">
      <div className="text-xs font-medium text-ink-2">{label}</div>
      <dl className="mt-2 space-y-2">
        {locs.map((l) => {
          const b = data[l]
          return (
            <div key={l} className="flex items-start justify-between gap-2 text-xs">
              <dt className="flex items-center gap-1.5 text-ink-3">
                {l === 'local' ? <HardDrive className="h-3.5 w-3.5" /> : <Cloud className="h-3.5 w-3.5" />}
                {l === 'local' ? 'Local' : 'Cloud'}
              </dt>
              <dd className="text-right tabular-nums text-ink">
                {b ? (
                  <>
                    <div>
                      {fmtNum(b.calls)} calls · {fmtNum(b.input_tokens + b.output_tokens)} tokens
                    </div>
                    <div className="text-ink-3">
                      avg {fmtMs(b.avg_latency_ms)} · {l === 'local' ? '$0 (compute only)' : fmtUsd(b.cost_usd)}
                    </div>
                  </>
                ) : (
                  <span className="text-ink-3">No calls</span>
                )}
              </dd>
            </div>
          )
        })}
      </dl>
    </div>
  )
}

// ------------------------------------------------------------------------------------------ tabs

function useActivity<T>(kind: string) {
  return useQuery({ queryKey: ['activity', kind], queryFn: () => get<{ items: T[] }>(`/api/activity?kind=${kind}&limit=200`) })
}

function TabBody<T>({ q, empty, children }: { q: ReturnType<typeof useActivity<T>>; empty: string; children: (items: T[]) => React.ReactNode }) {
  if (q.isLoading) return <LoadingRows rows={5} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  if (q.data.items.length === 0) return <EmptyState title={empty} />
  return <>{children(q.data.items)}</>
}

function detailText(d: Record<string, unknown> | null) {
  if (!d) return ''
  return Object.entries(d)
    .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join(' · ')
}

function AuditTab() {
  const q = useActivity<AuditItem>('audit')
  return (
    <TabBody q={q} empty="No audit entries yet">
      {(items) => (
        <Table label="Audit log">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Actor</th>
              <th className={th}>Action</th>
              <th className={th}>Target</th>
              <th className={th}>Details</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((a) => (
              <tr key={a.id}>
                <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(a.created_at)}</td>
                <td className={td}>
                  <Badge tone={a.actor === 'user' ? 'neutral' : 'info'}>{a.actor}</Badge>
                </td>
                <td className={cn(td, 'whitespace-nowrap font-medium text-ink')}>{humanize(a.action)}</td>
                <td className={cn(td, 'text-xs')}>{a.target.type ? `${a.target.type}${a.target.id ? ` ${a.target.id.slice(0, 8)}` : ''}` : '—'}</td>
                <td className={cn(td, 'max-w-[420px] truncate font-mono text-[11px]')} title={detailText(a.details)}>
                  {detailText(a.details) || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </TabBody>
  )
}

const MODE_TONE: Record<string, 'success' | 'info' | 'warning' | 'neutral'> = { llm: 'success', extractive: 'info', policy: 'warning' }

function RunsTab() {
  const q = useActivity<RunItem>('runs')
  return (
    <TabBody q={q} empty="No assistant runs yet">
      {(items) => (
        <Table label="Assistant runs">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Question</th>
              <th className={th}>Mode</th>
              <th className={cn(th, 'text-right')}>Citations</th>
              <th className={th}>Verification</th>
              <th className={cn(th, 'text-right')}>Latency</th>
              <th className={cn(th, 'text-right')}>Tokens</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((r) => {
              const v = r.verification ?? {}
              const nums = Object.entries(v).filter(([, x]) => typeof x === 'number') as [string, number][]
              return (
                <tr key={r.id}>
                  <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(r.created_at)}</td>
                  <td className={cn(td, 'max-w-[320px]')}>
                    <span className="line-clamp-2 text-ink">{r.question}</span>
                    {r.model && <span className="text-[11px] text-ink-3">{r.model}</span>}
                  </td>
                  <td className={td}>
                    {r.mode ? <Badge tone={MODE_TONE[r.mode] ?? 'neutral'}>{r.mode}</Badge> : '—'}
                    {r.status !== 'completed' && r.status !== 'succeeded' && <div className="mt-0.5 text-[11px] text-ink-3">{r.status}</div>}
                  </td>
                  <td className={cn(td, 'text-right tabular-nums')}>{r.citations}</td>
                  <td className={cn(td, 'text-xs')}>
                    {nums.length ? (
                      <ul>
                        {nums.map(([k, x]) => (
                          <li key={k} className={cn(k.includes('removed') || k.includes('invalid') ? (x > 0 ? 'text-warning' : '') : '')}>
                            {humanize(k)}: <span className="tabular-nums">{x}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className={cn(td, 'text-right tabular-nums')}>{fmtMs(r.latency_ms)}</td>
                  <td className={cn(td, 'text-right tabular-nums')}>{fmtNum(r.tokens)}</td>
                </tr>
              )
            })}
          </tbody>
        </Table>
      )}
    </TabBody>
  )
}

function ToolsTab() {
  const q = useActivity<ToolItem>('tools')
  return (
    <TabBody q={q} empty="No tool executions yet">
      {(items) => (
        <Table label="Tool executions">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Tool</th>
              <th className={th}>Access</th>
              <th className={th}>Status</th>
              <th className={cn(th, 'text-right')}>Results</th>
              <th className={cn(th, 'text-right')}>Latency</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((t) => (
              <tr key={t.id}>
                <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(t.created_at)}</td>
                <td className={cn(td, 'font-mono text-xs text-ink')}>{t.tool}</td>
                <td className={td}>
                  <AccessBadge access={t.access} />
                </td>
                <td className={td}>
                  <Badge tone={t.status === 'ok' || t.status === 'succeeded' ? 'success' : t.status === 'error' || t.status === 'failed' ? 'danger' : t.status === 'denied' ? 'warning' : 'neutral'}>{t.status}</Badge>
                </td>
                <td className={cn(td, 'text-right tabular-nums')}>{fmtNum(t.result_count)}</td>
                <td className={cn(td, 'text-right tabular-nums')}>{fmtMs(t.latency_ms)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </TabBody>
  )
}

function LlmTab() {
  const q = useActivity<LlmItem>('llm')
  return (
    <TabBody q={q} empty="No model calls yet">
      {(items) => (
        <Table label="LLM calls">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>When</th>
              <th className={th}>Operation</th>
              <th className={th}>Provider / model</th>
              <th className={th}>Locality</th>
              <th className={cn(th, 'text-right')}>Tokens in / out</th>
              <th className={cn(th, 'text-right')}>Latency</th>
              <th className={cn(th, 'text-right')}>Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {items.map((c) => (
              <tr key={c.id}>
                <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(c.created_at)}</td>
                <td className={td}>
                  <span className="text-ink">{c.operation ? humanize(c.operation) : '—'}</span>
                  {c.status !== 'ok' && c.status !== 'succeeded' && <div className="text-[11px] text-ink-3">{c.status}</div>}
                  {c.source_types && c.source_types.length > 0 && <div className="text-[11px] text-ink-3">sources: {c.source_types.join(', ')}</div>}
                </td>
                <td className={cn(td, 'text-xs')}>
                  <div className="text-ink">{c.provider}</div>
                  <div className="font-mono text-[11px] text-ink-3">{c.model}</div>
                </td>
                <td className={td}>
                  <Badge tone={c.locality === 'cloud' ? 'info' : 'success'}>
                    {c.locality === 'cloud' ? <Cloud className="h-3 w-3" /> : <HardDrive className="h-3 w-3" />}
                    {c.locality}
                  </Badge>
                </td>
                <td className={cn(td, 'whitespace-nowrap text-right tabular-nums')}>
                  {fmtNum(c.input_tokens)} / {fmtNum(c.output_tokens)}
                </td>
                <td className={cn(td, 'text-right tabular-nums')}>{fmtMs(c.latency_ms)}</td>
                <td className={cn(td, 'text-right tabular-nums')}>{c.locality === 'cloud' ? fmtUsd(c.cost_usd) : '$0'}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </TabBody>
  )
}

function ManifestTab() {
  const q = useQuery({ queryKey: ['assistant-tools'], queryFn: () => get<{ tools: ToolManifest[] }>('/api/assistant/tools'), staleTime: 300_000 })
  if (q.isLoading) return <LoadingRows rows={5} />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  return (
    <>
      <p className="px-4 pt-3 text-xs text-ink-3">The assistant can only call these tools. READ tools query your local memory; WRITE tools only create proposals that wait for your approval.</p>
      <Table label="Tool permission manifest">
        <thead className="border-b border-line">
          <tr>
            <th className={th}>Tool</th>
            <th className={th}>Access</th>
            <th className={th}>Scope</th>
            <th className={th}>Sensitivity</th>
            <th className={th}>Approval</th>
            <th className={th}>Description</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {q.data.tools.map((t) => (
            <tr key={t.name}>
              <td className={cn(td, 'whitespace-nowrap font-mono text-xs text-ink')}>{t.name}</td>
              <td className={td}>
                <AccessBadge access={t.access} />
              </td>
              <td className={cn(td, 'text-xs')}>{t.scope}</td>
              <td className={td}>
                <Badge tone={t.sensitivity === 'high' ? 'danger' : t.sensitivity === 'medium' ? 'warning' : 'neutral'}>{t.sensitivity}</Badge>
              </td>
              <td className={cn(td, 'text-xs')}>{t.requires_approval ? <span className="font-medium text-warning">Required</span> : 'Not needed'}</td>
              <td className={cn(td, 'min-w-[240px] text-xs')}>{t.description}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  )
}
