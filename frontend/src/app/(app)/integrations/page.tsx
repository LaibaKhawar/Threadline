'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderPlus, RefreshCw, Trash2, Unplug } from 'lucide-react'
import Link from 'next/link'
import { useCallback, useState } from 'react'

import { ConnectorCatalog, connectorIcon } from '@/components/system/connectors'
import { ConfirmDialog, JobProgress, JobStatusBadge, LocalFolderDialog, Table, fmtNum, fmtStamp, humanize, td, th } from '@/components/system/shared'
import { TERMINAL, useJob } from '@/components/system/use-job'
import { useToast } from '@/components/toast'
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, LoadingRows, PageHeader } from '@/components/ui/primitives'
import { del, errorMessage, get, post } from '@/lib/api'
import type { CatalogItem, Integration, Job, JobStart, JobsResponse } from '@/lib/types-system'
import { cn } from '@/lib/utils'

const INTERNAL = new Set(['notes', 'uploads'])

function statusTone(s: string) {
  if (s === 'connected') return 'success' as const
  if (s === 'error') return 'danger' as const
  if (s === 'pending') return 'warning' as const
  return 'neutral' as const
}
function statusLabel(s: string) {
  return s === 'revoked' ? 'Disconnected' : s === 'pending' ? 'Awaiting authorisation' : humanize(s)
}

export default function IntegrationsPage() {
  const qc = useQueryClient()
  const toast = useToast()
  const [folderOpen, setFolderOpen] = useState(false)
  const [syncJobs, setSyncJobs] = useState<Record<string, string>>({})
  const [demoJob, setDemoJob] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<{ kind: 'disconnect' | 'delete'; integ: Integration } | null>(null)

  const list = useQuery({ queryKey: ['integrations'], queryFn: () => get<{ items: Integration[] }>('/api/integrations') })

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['integrations'] })
    qc.invalidateQueries({ queryKey: ['jobs'] })
    qc.invalidateQueries({ queryKey: ['privacy'] })
  }, [qc])

  const sync = useMutation({
    mutationFn: (id: string) => post<JobStart>(`/api/integrations/${id}/sync`),
    onSuccess: (r, id) => {
      setSyncJobs((s) => ({ ...s, [id]: r.job_id }))
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const disconnect = useMutation({
    mutationFn: (id: string) => post<Integration>(`/api/integrations/${id}/disconnect`),
    onSuccess: (i) => {
      toast(`${i.name} disconnected. Stored credentials were deleted; imported data is kept until you delete it.`)
      setConfirm(null)
      refresh()
    },
  })
  const deleteData = useMutation({
    mutationFn: (id: string) => del<{ deleted_items: number }>(`/api/integrations/${id}/data`),
    onSuccess: (r) => {
      toast(`Deleted ${fmtNum(r.deleted_items)} imported item${r.deleted_items === 1 ? '' : 's'} and everything derived from them.`)
      setConfirm(null)
      refresh()
      qc.invalidateQueries({ queryKey: ['inventory'] })
    },
  })
  const importDemo = useMutation({
    mutationFn: () => post<JobStart>('/api/onboarding/demo'),
    onSuccess: (r) => setDemoJob(r.job_id),
    onError: (e) => toast(errorMessage(e), 'error'),
  })

  const items = list.data?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title="Integrations"
        description="Sources Threadline reads from. Everything imported is stored on this machine; per-source AI permissions live in the Privacy center."
        actions={
          <Button variant="primary" onClick={() => setFolderOpen(true)}>
            <FolderPlus className="h-4 w-4" /> Add local folder
          </Button>
        }
      />

      <Card>
        <CardHeader title="Connected sources" description="Sync status, item counts and the result of each source’s last sync." action={<Link href="/privacy" className="text-xs text-accent hover:underline">AI permissions</Link>} />
        {list.isLoading ? (
          <LoadingRows rows={3} />
        ) : list.error ? (
          <ErrorState error={list.error} retry={() => list.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState title="No sources yet" description="Add a local folder or import the demo workspace from the catalog below." />
        ) : (
          <ul className="divide-y divide-line">
            {items.map((i) => (
              <SourceRow
                key={i.id}
                integ={i}
                jobId={syncJobs[i.id]}
                syncing={sync.isPending && sync.variables === i.id}
                onSync={() => sync.mutate(i.id)}
                onJobDone={(j) => {
                  refresh()
                  if (j.status === 'succeeded') toast(`${i.name} synced.`)
                  else toast(`${i.name} sync failed: ${j.error ?? 'unknown error'}`, 'error')
                }}
                onDisconnect={() => setConfirm({ kind: 'disconnect', integ: i })}
                onDelete={() => setConfirm({ kind: 'delete', integ: i })}
              />
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <CardHeader title="Connector catalog" description="Implemented connectors can be connected now. Planned ones are listed honestly; they do not work yet." />
        <div className="p-4">
          {demoJob && (
            <JobProgress
              className="mb-3"
              jobId={demoJob}
              label="Importing the demo workspace"
              onDone={(j) => {
                refresh()
                qc.invalidateQueries()
                toast(j.status === 'succeeded' ? 'Demo workspace imported.' : `Demo import failed: ${j.error ?? ''}`, j.status === 'succeeded' ? 'success' : 'error')
              }}
            />
          )}
          <ConnectorCatalog
            connected={items}
            onLocalFolder={() => setFolderOpen(true)}
            renderDemo={(c: CatalogItem) =>
              items.some((i) => i.kind === c.kind && i.status !== 'revoked') ? null : (
                <Button size="sm" variant="subtle" loading={importDemo.isPending} onClick={() => importDemo.mutate()}>
                  Import
                </Button>
              )
            }
          />
        </div>
      </Card>

      <JobsCard />

      <LocalFolderDialog open={folderOpen} onClose={() => setFolderOpen(false)} />

      <ConfirmDialog
        open={confirm?.kind === 'disconnect'}
        onClose={() => {
          setConfirm(null)
          disconnect.reset()
        }}
        title={`Disconnect ${confirm?.integ.name ?? ''}?`}
        confirmLabel="Disconnect"
        pending={disconnect.isPending}
        error={disconnect.error}
        onConfirm={() => confirm && disconnect.mutate(confirm.integ.id)}
      >
        <p>Threadline will stop syncing this source and delete its stored credentials (and revoke the token with the provider where supported).</p>
        <p>Data already imported stays in your memory. Use “Delete imported data” to remove it.</p>
      </ConfirmDialog>

      <ConfirmDialog
        open={confirm?.kind === 'delete'}
        onClose={() => {
          setConfirm(null)
          deleteData.reset()
        }}
        title={`Delete data imported from ${confirm?.integ.name ?? ''}?`}
        confirmLabel="Delete imported data"
        pending={deleteData.isPending}
        error={deleteData.error}
        requireText="DELETE"
        onConfirm={() => confirm && deleteData.mutate(confirm.integ.id)}
      >
        <p>
          This permanently deletes the {fmtNum(confirm?.integ.item_count ?? 0)} item{confirm?.integ.item_count === 1 ? '' : 's'} imported from this source and everything derived from them (chunks, extracted commitments, evidence, memories), and resets its sync cursor.
        </p>
        <p>The source stays connected; syncing again re-imports it.</p>
      </ConfirmDialog>
    </div>
  )
}

function SourceRow({
  integ: i,
  jobId,
  syncing,
  onSync,
  onJobDone,
  onDisconnect,
  onDelete,
}: {
  integ: Integration
  jobId?: string
  syncing: boolean
  onSync: () => void
  onJobDone: (j: Job) => void
  onDisconnect: () => void
  onDelete: () => void
}) {
  const internal = INTERNAL.has(i.kind)
  const running = useJob(jobId).isActive
  const revoked = i.status === 'revoked'
  const s = i.sync
  const path = typeof i.config.path === 'string' ? i.config.path : null
  return (
    <li className="px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-sunken text-ink-2">{connectorIcon(i.kind)}</span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-ink">{i.name}</span>
              <Badge tone={statusTone(i.status)}>{statusLabel(i.status)}</Badge>
              {internal && <Badge tone="neutral">Built-in</Badge>}
              {!i.store_locally && (
                <Badge tone="warning" title="Store locally is off in the Privacy center; syncs are skipped">
                  Not storing
                </Badge>
              )}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-3">
              <span>{i.kind}</span>
              {path && (
                <span className="max-w-[260px] truncate font-mono" title={path}>
                  {path}
                </span>
              )}
              <span>{fmtNum(i.item_count ?? 0)} items</span>
              {!internal && <span>Last sync {i.last_sync_at ? fmtStamp(i.last_sync_at) : 'never'}</span>}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {!internal && (
            <Button size="sm" onClick={onSync} loading={syncing} disabled={revoked || i.status === 'pending' || running} aria-label={`Sync ${i.name} now`}>
              <RefreshCw className="h-3.5 w-3.5" /> Sync now
            </Button>
          )}
          {!internal && !revoked && (
            <Button size="sm" variant="ghost" onClick={onDisconnect} aria-label={`Disconnect ${i.name}`}>
              <Unplug className="h-3.5 w-3.5" /> Disconnect
            </Button>
          )}
          <Button size="sm" variant="ghost" className="text-danger hover:text-danger" onClick={onDelete} disabled={(i.item_count ?? 0) === 0} aria-label={`Delete data imported from ${i.name}`}>
            <Trash2 className="h-3.5 w-3.5" /> Delete data
          </Button>
        </div>
      </div>

      {!internal && (
        <dl className="mt-2.5 grid grid-cols-3 gap-2 rounded-md bg-surface-2 px-3 py-2 text-xs sm:grid-cols-6">
          {(
            [
              ['Created', s.items_created],
              ['Updated', s.items_updated],
              ['Unchanged', s.items_unchanged],
              ['Deleted', s.items_deleted],
              ['Errors', s.error_count],
            ] as const
          ).map(([k, v]) => (
            <div key={k}>
              <dt className="text-ink-3">{k}</dt>
              <dd className={cn('tabular-nums font-medium text-ink', k === 'Errors' && v > 0 && 'text-danger')}>{fmtNum(v)}</dd>
            </div>
          ))}
          <div>
            <dt className="text-ink-3">Next sync</dt>
            <dd className="font-medium text-ink" title={s.cursor_present ? 'A sync cursor is saved: only changes since the last sync are fetched' : 'No cursor saved: the next sync scans everything'}>
              {s.cursor_present ? 'Incremental' : 'Full scan'}
            </dd>
          </div>
        </dl>
      )}
      {i.last_error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          Last error: {i.last_error}
        </p>
      )}
      {jobId && <JobProgress className="mt-2.5" jobId={jobId} label={`Syncing ${i.name}`} onDone={onJobDone} />}
    </li>
  )
}

function JobsCard() {
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => get<JobsResponse>('/api/jobs'),
    refetchInterval: (q) => (q.state.data?.items.some((j) => !TERMINAL.has(j.status)) || (q.state.data?.events.pending ?? 0) > 0 ? 3000 : false),
  })
  const d = jobs.data
  return (
    <Card>
      <CardHeader
        title="Recent jobs"
        description="Background work: syncs, imports, memory rebuilds, proactive analysis and evaluations."
        action={
          d ? (
            <div className="flex gap-1.5">
              <Badge tone={d.events.pending > 0 ? 'info' : 'neutral'} title="Domain events waiting to be processed into memory">
                {fmtNum(d.events.pending)} events queued
              </Badge>
              <Badge tone={d.events.failed > 0 ? 'danger' : 'neutral'} title="Domain events that failed or were dead-lettered">
                {fmtNum(d.events.failed)} failed
              </Badge>
            </div>
          ) : undefined
        }
      />
      {jobs.isLoading ? (
        <LoadingRows rows={3} />
      ) : jobs.error || !d ? (
        <ErrorState error={jobs.error} retry={() => jobs.refetch()} />
      ) : d.items.length === 0 ? (
        <EmptyState title="No jobs yet" description="Syncs and rebuilds you start will appear here with their status." />
      ) : (
        <Table label="Recent jobs">
          <thead className="border-b border-line">
            <tr>
              <th className={th}>Job</th>
              <th className={th}>Status</th>
              <th className={th}>Progress</th>
              <th className={th}>Attempts</th>
              <th className={th}>Started</th>
              <th className={th}>Finished</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {d.items.slice(0, 15).map((j) => (
              <tr key={j.id}>
                <td className={cn(td, 'font-medium text-ink')}>{humanize(j.kind)}</td>
                <td className={td}>
                  <JobStatusBadge status={j.status} />
                </td>
                <td className={cn(td, 'max-w-[320px] text-xs')}>
                  {j.error ? <span className="text-danger">{j.error}</span> : j.status === 'succeeded' ? 'Done' : j.progress?.percent !== undefined ? `${j.progress.percent}%${j.progress.message ? ` · ${j.progress.message}` : ''}` : '—'}
                </td>
                <td className={cn(td, 'tabular-nums')}>{j.attempts}</td>
                <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(j.created_at)}</td>
                <td className={cn(td, 'whitespace-nowrap text-xs')}>{fmtStamp(j.finished_at)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}
