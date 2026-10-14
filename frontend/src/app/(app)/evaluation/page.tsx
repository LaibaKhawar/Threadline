'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FlaskConical, Play } from 'lucide-react'
import { type ReactNode, useMemo, useState } from 'react'

import { JobProgress, Table, fmtStamp, humanize, td, th } from '@/components/system/shared'
import { useJob } from '@/components/system/use-job'
import { useToast } from '@/components/toast'
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, LoadingRows, PageHeader, Tabs } from '@/components/ui/primitives'
import { errorMessage, get, post } from '@/lib/api'
import type { EvalDetail, EvalRun, Evaluation, JobStart } from '@/lib/types-system'
import { cn } from '@/lib/utils'

// ------------------------------------------------------------------------------------------ metric formatting

const COUNT_KEY = /(^n$|^n_|_n$|count|total|cases|examples|num|items|queries|questions|passed|failed|errors|merges$|mentions$|suggestions$|commitments$|statements$|documents$|checks$|calls$|runs$|extracted$|executions$|proposals$|leaks$|claims$|^support$|tp$|fp$|fn$|^tp|^fp|^fn)/i
const MS_KEY = /(_ms$|_ms_|latency)/i
const SEC_KEY = /(^seconds$|_seconds$|_s$)/i

function isRate(key: string, v: number) {
  if (MS_KEY.test(key) || SEC_KEY.test(key) || COUNT_KEY.test(key)) return false
  return v >= 0 && v <= 1
}

function fmtMetric(key: string, v: unknown): string {
  if (typeof v === 'number') {
    if (Number.isNaN(v)) return '—'
    if (MS_KEY.test(key)) return `${Math.round(v)} ms`
    if (SEC_KEY.test(key)) return `${v.toFixed(2)} s`
    if (isRate(key, v)) return `${(v * 100).toFixed(1)}%`
    if (Number.isInteger(v)) return v.toLocaleString('en-US')
    return v.toFixed(3)
  }
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

/** Flatten nested metric objects to dotted keys so they render as one table. */
function flatten(obj: Record<string, unknown>, prefix = ''): [string, unknown][] {
  const out: [string, unknown][] = []
  for (const [k, v] of Object.entries(obj ?? {})) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) out.push(...flatten(v as Record<string, unknown>, key))
    else out.push([key, v])
  }
  return out
}

const variantOf = (r: { config?: Record<string, unknown> | null; variant?: string | null }) =>
  (r.variant ?? (r.config?.variant as string | undefined) ?? null) || null

const SUITE_ORDER = ['entity_extraction', 'entity_resolution', 'commitment_extraction', 'commitment_resolution', 'retrieval', 'qa', 'temporal_qa', 'prompt_injection', 'permissions', 'agent_tools']
const suiteRank = (s: string) => {
  const i = SUITE_ORDER.indexOf(s)
  return i < 0 ? 99 : i
}

// ------------------------------------------------------------------------------------------ page

export default function EvaluationPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['evaluation'], queryFn: () => get<Evaluation>('/api/evaluation') })
  const [jobId, setJobId] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const evalJob = useJob(jobId)
  const run = useMutation({
    mutationFn: () => post<JobStart>('/api/evaluation/run', { suites: null, use_llm: false }),
    onSuccess: (r) => setJobId(r.job_id),
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const latest = useMemo(() => [...(q.data?.latest ?? [])].sort((a, b) => suiteRank(a.suite) - suiteRank(b.suite) || (variantOf(a) ?? '').localeCompare(variantOf(b) ?? '')), [q.data])
  const retrieval = latest.filter((r) => r.suite === 'retrieval')
  const others = latest.filter((r) => r.suite !== 'retrieval')

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title="Evaluation"
        description="Measured quality of extraction, resolution, retrieval, question answering and safety on the labelled synthetic dataset. Numbers are what the last run produced, not targets."
        actions={
          <Button variant="primary" loading={run.isPending} disabled={evalJob.isActive} onClick={() => run.mutate()}>
            <Play className="h-4 w-4" /> Run evaluations
          </Button>
        }
      />

      {jobId && (
        <JobProgress
          jobId={jobId}
          label="Running all evaluation suites (deterministic, no LLM)"
          onDone={(j) => {
            qc.invalidateQueries({ queryKey: ['evaluation'] })
            toast(j.status === 'succeeded' ? 'Evaluation finished.' : `Evaluation failed: ${j.error ?? 'unknown error'}`, j.status === 'succeeded' ? 'success' : 'error')
          }}
        />
      )}

      {q.isLoading ? (
        <Card>
          <LoadingRows rows={8} />
        </Card>
      ) : q.error || !q.data ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : latest.length === 0 ? (
        <Card>
          <EmptyState
            icon={<FlaskConical className="h-4 w-4" />}
            title="No evaluation runs yet"
            description={
              <>
                Run <code className="font-mono">make eval</code> from the repository root, or use “Run evaluations” above. Each suite scores the pipeline against hand-labelled synthetic data and stores its metrics here.
              </>
            }
          />
        </Card>
      ) : (
        <>
          {retrieval.length > 0 && <RetrievalComparison runs={retrieval} onOpen={setOpenId} />}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {others.map((r) => (
              <SuiteCard key={r.id} run={r} onOpen={() => setOpenId(r.id)} />
            ))}
          </div>
          <History items={q.data.history} onOpen={setOpenId} />
        </>
      )}

      <DetailDialog id={openId} onClose={() => setOpenId(null)} />
    </div>
  )
}

function SuiteCard({ run, onOpen }: { run: EvalRun; onOpen: () => void }) {
  const entries = flatten(run.metrics)
  const v = variantOf(run)
  return (
    <Card className="flex flex-col">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            {humanize(run.suite)}
            {v && v !== 'default' && <Badge tone="neutral">{v}</Badge>}
          </span>
        }
        description={fmtStamp(run.created_at)}
        action={
          <Button size="sm" variant="ghost" onClick={onOpen} aria-label={`Details for ${humanize(run.suite)}`}>
            Details
          </Button>
        }
      />
      {entries.length === 0 ? (
        <p className="p-4 text-xs text-ink-3">No metrics recorded.</p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 p-4">
          {entries.slice(0, 12).map(([k, val]) => (
            <div key={k} className="min-w-0">
              <dt className="truncate text-[11px] text-ink-3" title={k}>
                {k}
              </dt>
              <dd className={cn('text-sm font-semibold tabular-nums text-ink', typeof val === 'number' && isRate(k, val) && 'text-base')}>{fmtMetric(k, val)}</dd>
            </div>
          ))}
          {entries.length > 12 && <p className="col-span-2 text-[11px] text-ink-3">+{entries.length - 12} more in details</p>}
        </dl>
      )}
    </Card>
  )
}

function RetrievalComparison({ runs, onOpen }: { runs: EvalRun[]; onOpen: (id: string) => void }) {
  // Only metrics expressed as rates are comparable as bars.
  const keys = Array.from(new Set(runs.flatMap((r) => flatten(r.metrics).filter(([k, v]) => typeof v === 'number' && isRate(k, v)).map(([k]) => k))))
  const best: Record<string, number> = {}
  for (const k of keys) best[k] = Math.max(...runs.map((r) => Number(flatten(r.metrics).find(([kk]) => kk === k)?.[1] ?? 0)))
  return (
    <Card>
      <CardHeader title="Retrieval: variant comparison" description="Same labelled queries, four retrieval strategies. Higher is better; the best value per metric is marked." />
      <Table label="Retrieval metrics by variant">
        <thead className="border-b border-line">
          <tr>
            <th className={th}>Variant</th>
            {keys.map((k) => (
              <th key={k} className={th}>
                {k}
              </th>
            ))}
            <th className={th}>
              <span className="sr-only">Details</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {runs.map((r) => {
            const m = Object.fromEntries(flatten(r.metrics))
            return (
              <tr key={r.id}>
                <td className={cn(td, 'font-medium text-ink')}>{variantOf(r) ?? 'default'}</td>
                {keys.map((k) => {
                  const v = typeof m[k] === 'number' ? (m[k] as number) : null
                  const isBest = v !== null && v === best[k] && runs.length > 1
                  return (
                    <td key={k} className={cn(td, 'min-w-[120px]')}>
                      {v === null ? (
                        '—'
                      ) : (
                        <div>
                          <div className={cn('text-xs tabular-nums', isBest ? 'font-semibold text-ink' : 'text-ink-2')}>
                            {fmtMetric(k, v)}
                            {isBest && <span className="sr-only"> (best)</span>}
                          </div>
                          <div className="mt-1 h-1.5 w-full rounded-full bg-sunken" aria-hidden>
                            <div className={cn('h-1.5 rounded-full', isBest ? 'bg-accent' : 'bg-line-strong')} style={{ width: `${Math.max(2, v * 100)}%` }} />
                          </div>
                        </div>
                      )}
                    </td>
                  )
                })}
                <td className={cn(td, 'text-right')}>
                  <Button size="sm" variant="ghost" onClick={() => onOpen(r.id)} aria-label={`Details for retrieval ${variantOf(r) ?? ''}`}>
                    Details
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </Table>
    </Card>
  )
}

function History({ items, onOpen }: { items: Evaluation['history']; onOpen: (id: string) => void }) {
  const [limit, setLimit] = useState(20)
  return (
    <Card>
      <CardHeader title="Run history" description={`${items.length} stored run${items.length === 1 ? '' : 's'} (most recent first).`} />
      <Table label="Evaluation history">
        <thead className="border-b border-line">
          <tr>
            <th className={th}>When</th>
            <th className={th}>Suite</th>
            <th className={th}>Variant</th>
            <th className={th}>Headline metrics</th>
            <th className={th}>
              <span className="sr-only">Open</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {items.slice(0, limit).map((h) => (
            <tr key={h.id}>
              <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(h.created_at)}</td>
              <td className={cn(td, 'whitespace-nowrap text-ink')}>{humanize(h.suite)}</td>
              <td className={cn(td, 'text-xs')}>{h.variant ?? '—'}</td>
              <td className={cn(td, 'text-xs')}>
                {flatten(h.metrics)
                  .filter(([, v]) => typeof v === 'number')
                  .slice(0, 4)
                  .map(([k, v]) => `${k} ${fmtMetric(k, v)}`)
                  .join(' · ') || '—'}
              </td>
              <td className={cn(td, 'text-right')}>
                <Button size="sm" variant="ghost" onClick={() => onOpen(h.id)}>
                  Open
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
      {items.length > limit && (
        <div className="border-t border-line p-2 text-center">
          <Button size="sm" variant="ghost" onClick={() => setLimit(limit + 50)}>
            Show more
          </Button>
        </div>
      )}
    </Card>
  )
}

// ------------------------------------------------------------------------------------------ detail viewer

function DetailDialog({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ['evaluation', id], queryFn: () => get<EvalDetail>(`/api/evaluation/${id}`), enabled: !!id })
  const [view, setView] = useState<'table' | 'json'>('table')
  const d = q.data
  return (
    <Dialog open={!!id} onClose={onClose} wide title={d ? `${humanize(d.suite)}${variantOf(d) ? ` · ${variantOf(d)}` : ''}` : 'Evaluation run'}>
      {q.isLoading ? (
        <LoadingRows rows={6} />
      ) : q.error || !d ? (
        <ErrorState error={q.error} retry={() => q.refetch()} />
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-ink-3">
            Run {d.id.slice(0, 8)} · {fmtStamp(d.created_at)}
            {d.config && Object.keys(d.config).length > 0 ? ` · config ${JSON.stringify(d.config)}` : ''}
          </p>
          <section>
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">Metrics</h3>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
              {flatten(d.metrics).map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="truncate text-[11px] text-ink-3" title={k}>
                    {k}
                  </dt>
                  <dd className="text-sm font-medium tabular-nums">{fmtMetric(k, v)}</dd>
                </div>
              ))}
            </dl>
          </section>
          <section>
            <div className="mb-1.5 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-ink-3">Details</h3>
              <Tabs
                value={view}
                onChange={setView}
                tabs={[
                  { value: 'table', label: 'Table' },
                  { value: 'json', label: 'JSON' },
                ]}
                className="border-b-0"
              />
            </div>
            {view === 'json' ? (
              <pre className="max-h-[45vh] overflow-auto rounded-md bg-surface-2 p-3 font-mono text-[11px] leading-4 text-ink-2">{JSON.stringify(d.details, null, 2)}</pre>
            ) : (
              <DetailsView value={d.details} />
            )}
          </section>
        </div>
      )}
    </Dialog>
  )
}

function cell(v: unknown): ReactNode {
  if (v === null || v === undefined) return <span className="text-ink-3">—</span>
  if (typeof v === 'boolean') return v ? <Badge tone="success">yes</Badge> : <Badge tone="danger">no</Badge>
  if (typeof v === 'number') return <span className="tabular-nums">{Number.isInteger(v) ? v : v.toFixed(3)}</span>
  if (typeof v === 'string') return v
  return <span className="font-mono text-[11px]">{JSON.stringify(v)}</span>
}

function DetailsView({ value }: { value: unknown }) {
  if (value === null || value === undefined || (typeof value === 'object' && Object.keys(value as object).length === 0)) {
    return <p className="text-sm text-ink-3">No per-case details were stored for this run.</p>
  }
  if (Array.isArray(value)) {
    if (value.length > 0 && value.every((x) => x && typeof x === 'object' && !Array.isArray(x))) {
      const rows = value as Record<string, unknown>[]
      const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).slice(0, 10)
      return (
        <div className="max-h-[45vh] overflow-auto rounded-md border border-line">
          <table className="w-full border-collapse text-xs" aria-label="Evaluation cases">
            <thead className="sticky top-0 bg-surface-2">
              <tr>
                {cols.map((c) => (
                  <th key={c} className={th}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.slice(0, 300).map((r, i) => (
                <tr key={i}>
                  {cols.map((c) => (
                    <td key={c} className="max-w-[260px] px-3 py-1.5 align-top text-ink-2">
                      <div className="line-clamp-3 break-words">{cell(r[c])}</div>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length > 300 && <p className="p-2 text-center text-[11px] text-ink-3">Showing 300 of {rows.length}. Switch to JSON for everything.</p>}
        </div>
      )
    }
    return (
      <ul className="max-h-[45vh] space-y-1 overflow-auto text-xs text-ink-2">
        {value.map((x, i) => (
          <li key={i}>{cell(x)}</li>
        ))}
      </ul>
    )
  }
  if (typeof value === 'object') {
    return (
      <div className="space-y-3">
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k}>
            <div className="mb-1 text-xs font-medium text-ink">{humanize(k)}</div>
            {v && typeof v === 'object' ? <DetailsView value={v} /> : <div className="text-sm text-ink-2">{cell(v)}</div>}
          </div>
        ))}
      </div>
    )
  }
  return <div className="text-sm text-ink-2">{cell(value)}</div>
}
